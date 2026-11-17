"""Job runtime: agent runs as resumable, observable, cancellable jobs (SPEC section 5).

Lifecycle: queued -> planning -> running -> (awaiting_approval -> running)* -> done | failed | cancelled.
Every event is persisted (monotonic per-job `seq`) before it is sent; SSE replays from Last-Event-ID, then tails.
Each step's output is checkpointed in `steps_json`; a restart or `resume` continues from the first step that is not `done`.
Telemetry (D-032): per step started_at, finished_at, seconds, tokens, cost_usd (adapter Ledger delta for the job id), engine;
per job wall_seconds and, on done, an estimated `time_saved` from eval.tsb.baselines.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .db import new_id, now
from .http import SSE, ApiError, Route

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, deal_id TEXT, user_id TEXT, agent_id TEXT, kind TEXT NOT NULL DEFAULT 'run',
  prompt TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, plan_json TEXT, steps_json TEXT, inputs_json TEXT,
  tokens INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  error TEXT, hint TEXT, source TEXT NOT NULL DEFAULT 'app' CHECK(source IN ('app','email','schedule','api')),
  resume_from INTEGER NOT NULL DEFAULT 0, wall_seconds REAL NOT NULL DEFAULT 0, time_saved_json TEXT, schedule_json TEXT, parent_id TEXT);
CREATE INDEX IF NOT EXISTS jobs_org ON jobs(org_id, kind, created_at);
CREATE INDEX IF NOT EXISTS jobs_deal ON jobs(org_id, deal_id);
CREATE TABLE IF NOT EXISTS job_events(
  job_id TEXT NOT NULL, seq INTEGER NOT NULL, at TEXT NOT NULL, type TEXT NOT NULL, data_json TEXT NOT NULL, PRIMARY KEY(job_id, seq));
"""

TERMINAL = ("done", "failed", "cancelled")
ACTIVE = ("queued", "planning", "running")
EVENT_TYPES = ("plan", "step", "source", "log", "approval", "deliverable", "cost", "status")
SERVICE: "JobService | None" = None


def _j(x) -> str:
    return json.dumps(x, separators=(",", ":"), sort_keys=True, default=str)


def _l(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default


def _iso(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobService:
    def __init__(self, state, workers: int | None = None, clock=time.time, scheduler: bool = True, tick_seconds: float = 20.0):
        from src.harness.ledger import Ledger
        self.state, self.clock = state, clock
        n = workers or int(os.environ.get("ACRETIA_JOB_WORKERS", "2") or 2)
        self.workers = max(1, n)
        dd = getattr(state, "data_dir", None)
        self.ledger = Ledger(Path(dd) / "ledger.jsonl" if dd else None)
        self._dblock = threading.RLock()
        self._cv = threading.Condition()
        self._cancel: dict[str, threading.Event] = {}
        self._active: set[str] = set()
        self._stop = threading.Event()
        self._adapter = None
        self.pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="acretia-job")
        self._sched_thread = None
        if scheduler:
            self._sched_thread = threading.Thread(target=self._sched_loop, args=(tick_seconds,), name="acretia-scheduler", daemon=True)

    # ------------------------------------------------------------------ plumbing
    def _db(self):
        return self.state.conn()

    def _q(self, sql: str, args=()) -> list:
        with self._dblock:
            return self._db().execute(sql, args).fetchall()

    def _x(self, sql: str, args=()):
        with self._dblock:
            return self._db().execute(sql, args)

    def adapter(self):
        if self._adapter is None:
            from src.harness.adapter import Adapter
            from . import agents  # noqa: F401
            from .agents import engines
            mode = getattr(self.state, "llm_mode", None) or os.environ.get("ACRETIA_LLM_MODE") or "replay"
            if mode == "replay" and engines.REPLAY_DIR.is_dir():
                os.environ.setdefault("ACRETIA_LLM_FIXTURES", str(engines.REPLAY_DIR))
            self._adapter = Adapter.from_env(mode=mode, ledger=self.ledger)
        return self._adapter

    def start(self):
        self._recover()
        if self._sched_thread is not None and not self._sched_thread.is_alive():
            self._sched_thread.start()

    def shutdown(self):
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        self.pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ events
    def emit(self, job_id: str, type_: str, data: dict) -> int:
        with self._dblock:
            c = self._db()
            seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM job_events WHERE job_id=?", (job_id,)).fetchone()[0]
            c.execute("INSERT INTO job_events(job_id, seq, at, type, data_json) VALUES(?,?,?,?,?)", (job_id, seq, now(), type_, _j(data)))
        with self._cv:
            self._cv.notify_all()
        return seq

    def events_after(self, job_id: str, seq: int) -> list[dict]:
        rows = self._q("SELECT seq, at, type, data_json FROM job_events WHERE job_id=? AND seq>? ORDER BY seq", (job_id, seq))
        return [{"seq": r["seq"], "at": r["at"], "type": r["type"], "data": _l(r["data_json"], {})} for r in rows]

    def stream(self, job_id: str, last_id: int = 0, wait: float = 15.0):
        """Generator of (event, data) pairs: replay after `last_id`, then tail until the terminal status event."""
        def gen():
            seq = last_id
            while not self._stop.is_set():
                evs = self.events_after(job_id, seq)
                for e in evs:
                    seq = e["seq"]
                    yield e["type"], {**e["data"], "seq": e["seq"], "at": e["at"]}
                    if e["type"] == "status" and e["data"].get("status") in TERMINAL:
                        return
                if evs:
                    continue
                row = self._q("SELECT status FROM jobs WHERE id=?", (job_id,))
                if not row or (row[0]["status"] in TERMINAL and not self.events_after(job_id, seq)):
                    return
                with self._cv:
                    if not self.events_after(job_id, seq):
                        notified = self._cv.wait(timeout=wait)
                        if not notified:
                            yield "ping", {}
        return gen()

    def _publish(self, org_id: str, event: str, data: dict):
        try:
            from . import notify
            notify.publish(org_id, event, data)
        except Exception:                                   # noqa: BLE001  (module absent or no listeners)
            pass

    # ------------------------------------------------------------------ rows
    def _row(self, job_id: str):
        r = self._q("SELECT * FROM jobs WHERE id=?", (job_id,))
        return r[0] if r else None

    def get(self, org_id: str, job_id: str) -> dict:
        r = self._row(job_id)
        if r is None or r["org_id"] != org_id or r["kind"] != "run":
            raise ApiError(404, "not_found", "No such run.")
        return r

    def deal_of(self, job_id: str):
        r = self._row(job_id)
        return r["deal_id"] if r else None

    def set_deal(self, job_id: str, deal_id: str):
        self._x("UPDATE jobs SET deal_id=? WHERE id=?", (deal_id, job_id))

    def approvals(self, job_id: str) -> dict:
        r = self._row(job_id)
        return (_l(r["inputs_json"], {}) or {}).get("_approvals", {}) if r else {}

    def is_cancelled(self, job_id: str) -> bool:
        ev = self._cancel.get(job_id)
        return bool(ev and ev.is_set()) or self._stop.is_set()

    def _set_inputs(self, job_id: str, **kv):
        with self._dblock:
            r = self._row(job_id)
            ins = _l(r["inputs_json"], {}) or {}
            ins.update(kv)
            self._x("UPDATE jobs SET inputs_json=? WHERE id=?", (_j(ins), job_id))

    def view(self, r, detail: bool = True) -> dict:
        steps = _l(r["steps_json"], []) or []
        v = {"id": r["id"], "status": r["status"], "prompt": r["prompt"], "deal_id": r["deal_id"], "agent_id": r["agent_id"], "source": r["source"],
             "created_at": r["created_at"], "started_at": r["started_at"], "finished_at": r["finished_at"], "tokens": r["tokens"], "cost_usd": round(r["cost_usd"], 6),
             "wall_seconds": round(r["wall_seconds"], 3), "error": r["error"], "hint": r["hint"], "time_saved": _l(r["time_saved_json"]),
             "resume_from": r["resume_from"], "user_id": r["user_id"]}
        if detail:
            plan = _l(r["plan_json"])
            v["plan"] = plan and {k: plan[k] for k in ("steps", "estimate", "method", "tasks", "outputs", "overrides", "review_minutes_estimate") if k in plan}
            v["steps"] = [{k: s.get(k) for k in ("id", "task", "title", "engine", "status", "detail", "started_at", "finished_at", "seconds", "tokens",
                                                 "cost_usd", "error", "hint", "notes")} for s in steps]
            v["deliverables"] = [d for s in steps for d in ((s.get("output") or {}).get("deliverables") or [])]
            v["pending_approval"] = (_l(r["inputs_json"], {}) or {}).get("_pending")
        return v

    # ------------------------------------------------------------------ API operations
    def submit(self, org_id: str, user_id: str, prompt: str, deal_id: str | None = None, agent_id: str | None = None, inputs: dict | None = None,
               source: str = "app") -> dict:
        from .agents import library
        inputs = dict(inputs or {})
        prompt = (prompt or "").strip()
        agent = None
        if agent_id:
            agent = library.resolve(self._db(), org_id, user_id, agent_id)
        if not prompt and not agent:
            raise ApiError(400, "missing_prompt", "Say what you want done.", "Send a prompt such as 'DCF for Apple', or pick an agent from the library.")
        if len(prompt) > 8000:
            raise ApiError(400, "prompt_too_long", "The prompt is longer than 8,000 characters.", "Shorten the request.")
        if deal_id:
            try:
                self.state.deal_store(self._db(), org_id).get(deal_id)
            except Exception:                               # noqa: BLE001
                raise ApiError(404, "not_found", "No such deal.") from None
        if source not in ("app", "email", "schedule", "api"):
            source = "app"
        if source in ("schedule", "email") and "source_review" not in inputs:
            inputs["source_review"] = False
        jid = new_id("job")
        self._x("INSERT INTO jobs(id, org_id, deal_id, user_id, agent_id, kind, prompt, status, inputs_json, created_at, source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (jid, org_id, deal_id, user_id, agent_id, "run", prompt, "queued", _j({**inputs, "_agent": agent}), now(), source))
        try:
            self.state.audit(self._db(), org_id, user_id, "job.create", jid, {"agent_id": agent_id, "source": source, "prompt": prompt[:200]})
        except Exception:                                   # noqa: BLE001
            pass
        self._enqueue(jid)
        return self.view(self._row(jid))

    def _enqueue(self, job_id: str):
        self._cancel.setdefault(job_id, threading.Event()).clear()
        try:
            self.pool.submit(self._run, job_id)
        except RuntimeError:                                # pool shut down
            pass

    def cancel(self, org_id: str, job_id: str) -> dict:
        r = self.get(org_id, job_id)
        if r["status"] in TERMINAL:
            raise ApiError(409, "already_finished", f"This run is already {r['status']}.", "Start a new run if you want to repeat it.")
        self._cancel.setdefault(job_id, threading.Event()).set()
        if r["status"] in ("queued", "awaiting_approval") and job_id not in self._active:
            self._finish(job_id, "cancelled", error="Cancelled by the user.", hint="Resume is not available for a cancelled run; start a new one.")
        return self.view(self._row(job_id))

    def resume(self, org_id: str, job_id: str) -> dict:
        r = self.get(org_id, job_id)
        if r["status"] != "failed":
            raise ApiError(409, "not_failed", f"Only a failed run can be resumed; this one is {r['status']}.",
                           "Wait for it to finish, or start a new run.")
        if job_id in self._active:
            raise ApiError(409, "busy", "This run is still winding down.", "Try again in a few seconds.")
        steps = _l(r["steps_json"], []) or []
        for s in steps:
            if s["status"] in ("failed", "skipped", "running"):
                s["status"] = "pending"
                s["error"] = s["hint"] = None
        self._x("UPDATE jobs SET status='queued', steps_json=?, error=NULL, hint=NULL, finished_at=NULL WHERE id=?", (_j(steps), job_id))
        self.emit(job_id, "status", {"status": "running", "resumed": True})
        self._enqueue(job_id)
        return self.view(self._row(job_id))

    def approve(self, org_id: str, job_id: str, step: str, payload: dict | None, user_id: str) -> dict:
        r = self.get(org_id, job_id)
        pend = (_l(r["inputs_json"], {}) or {}).get("_pending")
        if r["status"] != "awaiting_approval" or not pend:
            raise ApiError(409, "not_awaiting_approval", "This run is not waiting for approval.", "Open the run to see its current state.")
        if step != pend["step_id"]:
            raise ApiError(409, "wrong_step", f"The run is waiting on '{pend['step_id']}', not '{step}'.", f"Approve step '{pend['step_id']}'.")
        ap = self.approvals(job_id)
        ap[step] = {**(payload or {}), "by": user_id, "at": now()}
        self._set_inputs(job_id, _approvals=ap, _pending=None)
        self._x("UPDATE jobs SET status='queued' WHERE id=?", (job_id,))
        try:
            self.state.audit(self._db(), org_id, user_id, "job.approve", job_id, {"step": step})
        except Exception:                                   # noqa: BLE001
            pass
        self.emit(job_id, "status", {"status": "running", "approved": step})
        self._enqueue(job_id)
        return self.view(self._row(job_id))

    # ------------------------------------------------------------------ runner
    def _recover(self):
        for r in self._q("SELECT id FROM jobs WHERE kind='run' AND status IN ('queued','planning','running')"):
            self.emit(r["id"], "log", {"level": "info", "message": "Run resumed after a server restart."})
            self._enqueue(r["id"])

    def _run(self, job_id: str):
        if job_id in self._active:
            return
        self._active.add(job_id)
        try:
            self._run_inner(job_id)
        except Exception as e:                              # noqa: BLE001
            try:
                self._finish(job_id, "failed", error=f"Unexpected error ({type(e).__name__}).", hint="Resume the run; if it fails again, send the run id to support.")
            except Exception:                               # noqa: BLE001
                pass
        finally:
            self._active.discard(job_id)

    def _persist_steps(self, job_id: str, steps: list, resume_from: int | None = None):
        if resume_from is None:
            resume_from = next((i for i, s in enumerate(steps) if s["status"] != "done"), len(steps))
        self._x("UPDATE jobs SET steps_json=?, resume_from=? WHERE id=?", (_j(steps), resume_from, job_id))

    def _add_wall(self, job_id: str, t0: float):
        self._x("UPDATE jobs SET wall_seconds=wall_seconds+? WHERE id=?", (max(0.0, time.monotonic() - t0), job_id))

    def _finish(self, job_id: str, status: str, error: str | None = None, hint: str | None = None, extra: dict | None = None):
        r = self._row(job_id)
        steps = _l(r["steps_json"], []) or []
        if status == "cancelled":
            for s in steps:
                if s["status"] in ("pending", "running"):
                    s["status"] = "skipped"
        self._x("UPDATE jobs SET status=?, error=?, hint=?, finished_at=?, steps_json=? WHERE id=?",
                (status, error, hint, now(), _j(steps), job_id))
        data = {"status": status, **({"error": error} if error else {}), **({"hint": hint} if hint else {}), **(extra or {})}
        self.emit(job_id, "status", data)
        self._publish(r["org_id"], "job.status", {"job_id": job_id, "status": status, "deal_id": r["deal_id"]})
        if status in ("done", "failed"):
            self._notify(r, status, error)

    def _notify(self, r, status: str, error: str | None = None, awaiting: bool = False):
        try:
            title = {"done": "Run finished", "failed": "Run failed", "awaiting_approval": "Run needs your approval"}[status]
            body = (r["prompt"] or "")[:140] + (f" ({error})" if error and status == "failed" else "")
            self.state.notify(self._db(), r["org_id"], r["user_id"], f"job.{status}", title, body, f"/runs/{r['id']}")
        except Exception:                                   # noqa: BLE001
            pass

    def _plan(self, r, inputs: dict) -> dict:
        from .agents import library, planner
        agent = inputs.get("_agent")
        deal = None
        if r["deal_id"]:
            try:
                m = self.state.deal_store(self._db(), r["org_id"]).get(r["deal_id"])
                deal = {"name": m.name, "target": inputs.get("target", "")}
            except Exception:                               # noqa: BLE001
                deal = None
        pin = {k: v for k, v in inputs.items() if not k.startswith("_") and k != "source_review"}
        kw = dict(deal=deal, inputs=pin, adapter=self.adapter(), job_id=r["id"])
        if agent and agent.get("prompts"):
            prompts = [library.fill(p, pin) for p in agent["prompts"]]
            return planner.plan_chain(prompts, **{k: v for k, v in kw.items() if k != "inputs"}) if len(prompts) > 1 else \
                planner.plan_prompt(prompts[0], **kw)
        if agent and agent.get("task_id"):
            prompt = r["prompt"] or library.default_prompt(agent, pin)
            return planner.plan_prompt(prompt, task_id=agent["task_id"], **kw)
        return planner.plan_prompt(r["prompt"], **kw)

    def _run_inner(self, job_id: str):
        from .agents import engines, library, planner
        r = self._row(job_id)
        if r is None or r["status"] in TERMINAL:
            return
        t0 = time.monotonic()
        inputs = _l(r["inputs_json"], {}) or {}
        if not r["started_at"]:
            self._x("UPDATE jobs SET started_at=? WHERE id=?", (now(), job_id))
        # ---- planning (once)
        if not r["plan_json"]:
            self._x("UPDATE jobs SET status='planning' WHERE id=?", (job_id,))
            try:
                plan = self._plan(r, inputs)
            except planner.PlanError as e:
                self.emit(job_id, "step", {"id": "plan", "status": "failed", "title": "Understand the request", "detail": e.message, "hint": e.hint})
                self._add_wall(job_id, t0)
                self._finish(job_id, "failed", error=e.message, hint=e.hint)
                return
            except ApiError as e:
                self._add_wall(job_id, t0)
                self._finish(job_id, "failed", error=e.message, hint=e.hint)
                return
            steps = [{"id": s["id"], "task": s["task"], "task_index": s["task_index"], "fn": s["fn"], "title": s["title"], "engine": s["engine"],
                      "status": "pending", "output": None} for s in plan["steps"]]
            self._x("UPDATE jobs SET plan_json=?, steps_json=? WHERE id=?", (_j(plan), _j(steps), job_id))
            self.emit(job_id, "plan", {"steps": [{"id": s["id"], "title": s["title"], "tool": s["tool"], "engine": s["engine"], "task": s["task"]} for s in plan["steps"]],
                                       "estimate": plan["estimate"], "tasks": [{"task_id": t["task_id"]} for t in plan["tasks"]], "method": plan["method"],
                                       "overrides": plan["overrides"], "review_minutes_estimate": plan["review_minutes_estimate"]})
            r = self._row(job_id)
        plan = _l(r["plan_json"])
        steps = _l(r["steps_json"], [])
        # ---- pre-run source review (parity item 24; default on, off with inputs.source_review=false)
        review_on = inputs.get("source_review", os.environ.get("ACRETIA_SOURCE_REVIEW", "1") not in ("0", "false", "off")) is not False
        if review_on and "source_review" not in (inputs.get("_approvals") or {}):
            payload = {"sources": engines.describe_sources(self, dict(r), plan, self._db()),
                       "note": "These are the sources this run will use. Approve to continue, or cancel. Start the run with source_review=false to skip this step."}
            self._pause(job_id, r, "source_review", "sources", payload, t0)
            return
        self._x("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        # ---- steps
        outputs: dict = {}
        failed_tasks: dict[int, str] = {}
        for s in steps:
            if s["status"] == "done":
                outputs[s["id"]] = s["output"]
            elif s["status"] == "failed":
                failed_tasks.setdefault(s["task_index"], s["id"])
        for i, st in enumerate(steps):
            if st["status"] == "done":
                continue
            if self.is_cancelled(job_id):
                if self._stop.is_set() and not self._cancel.get(job_id, threading.Event()).is_set():
                    self._add_wall(job_id, t0)
                    return                                  # server stopping: leave the job resumable
                self._persist_steps(job_id, steps)
                self._add_wall(job_id, t0)
                self._finish(job_id, "cancelled", error="Cancelled by the user.", hint="Start a new run to repeat it.")
                return
            if st["task_index"] in failed_tasks:
                st.update(status="skipped", detail=f"Skipped because '{failed_tasks[st['task_index']]}' failed.")
                self.emit(job_id, "step", {"id": st["id"], "status": "skipped", "title": st["title"], "detail": st["detail"], "engine": st["engine"]})
                self._persist_steps(job_id, steps)
                continue
            task = plan["tasks"][st["task_index"]]
            before = self.ledger.total(job_id)
            st.update(status="running", started_at=now())
            t_step = time.monotonic()
            self.emit(job_id, "step", {"id": st["id"], "status": "running", "title": st["title"], "engine": st["engine"], "started_at": st["started_at"]})
            cx = engines.StepCtx(self, dict(self._row(job_id)), task["task_id"], task["inputs"], outputs, st, self._db())
            err = hint = None
            out = None
            try:
                out = engines.STEP_FNS[st["fn"]](cx) or {}
            except engines.NeedsApproval as na:
                st.update(status="pending", started_at=None)
                self._persist_steps(job_id, steps)
                self._pause(job_id, self._row(job_id), na.step_id, na.kind, na.payload, t0)
                return
            except engines.Cancelled:
                st.update(status="pending", started_at=None)
                self._persist_steps(job_id, steps)
                self._add_wall(job_id, t0)
                if self._stop.is_set():
                    return
                self._finish(job_id, "cancelled", error="Cancelled by the user.", hint="Start a new run to repeat it.")
                return
            except engines.StepFailed as e:
                err, hint = e.message, e.hint
            except KeyError as e:
                err, hint = f"Unknown step '{st['fn']}'.", "This build has no engine for that step."
                if str(e).strip("'") != st["fn"]:
                    err, hint = f"A required value was missing ({e}).", "Retry the run; if it fails again, send the run id to support."
            except Exception as e:                           # noqa: BLE001
                err, hint = f"The step hit an unexpected error ({type(e).__name__}).", "Resume the run to retry this step; if it fails again, send the run id to support."
                self.emit(job_id, "log", {"level": "error", "message": f"{st['id']}: {type(e).__name__}: {str(e)[:300]}"})
            after = self.ledger.total(job_id)
            st["finished_at"], st["seconds"] = now(), round(time.monotonic() - t_step, 4)
            st["tokens"] = (after["input_tokens"] + after["output_tokens"]) - (before["input_tokens"] + before["output_tokens"])
            st["cost_usd"] = round(after["cost_usd"] - before["cost_usd"], 8)
            if err is None:
                out["_task"] = task["task_id"]
                st.update(status="done", output=out, detail=out.get("detail", ""), notes=out.get("notes"), error=None, hint=None)
                outputs[st["id"]] = out
            else:
                st.update(status="failed", error=err, hint=hint, detail=err)
                failed_tasks.setdefault(st["task_index"], st["id"])
            self._persist_steps(job_id, steps)
            self._x("UPDATE jobs SET tokens=?, cost_usd=? WHERE id=?", (after["input_tokens"] + after["output_tokens"], after["cost_usd"], job_id))
            ev = {k: st.get(k) for k in ("id", "status", "title", "detail", "started_at", "finished_at", "seconds", "tokens", "cost_usd", "engine", "error", "hint")}
            if out and out.get("notes"):
                ev["notes"] = out["notes"]
            if out and out.get("badges"):
                ev["badges"] = out["badges"]
            self.emit(job_id, "step", ev)
            for tok in (out or {}).get("citations", []) if err is None else []:
                self._emit_source(job_id, r["org_id"], tok)
            self.emit(job_id, "cost", {"tokens": after["input_tokens"] + after["output_tokens"], "cost_usd": round(after["cost_usd"], 8)})
            try:
                self.state.audit(self._db(), r["org_id"], r["user_id"], "agent.step", job_id,
                                 {"step": st["id"], "status": st["status"], "engine": st["engine"], "seconds": st["seconds"], "cost_usd": st["cost_usd"]})
            except Exception:                               # noqa: BLE001
                pass
        # ---- deliverables, then the final status
        seen = {(d.get("name"), d.get("version")) for e in self.events_after(job_id, 0) if e["type"] == "deliverable" for d in [e["data"]]}
        for s in steps:
            for d in ((s.get("output") or {}).get("deliverables") or []):
                if (d["name"], d["version"]) not in seen:
                    self.emit(job_id, "deliverable", {**d, "url": f"/api/v1/deals/{d['deal_id']}/deliverables/{urllib.parse.quote(d['name'])}/versions/{d['version']}/download"})
                    seen.add((d["name"], d["version"]))
        self._add_wall(job_id, t0)
        bad = [s for s in steps if s["status"] == "failed"]
        if bad:
            self._finish(job_id, "failed", error=bad[0]["error"], hint=bad[0]["hint"], extra={"failed_steps": [b["id"] for b in bad]})
            return
        r = self._row(job_id)
        ts = self._time_saved(r, plan)
        self._x("UPDATE jobs SET time_saved_json=? WHERE id=?", (_j(ts), job_id))
        self._finish(job_id, "done", extra={"wall_seconds": round(r["wall_seconds"], 3), "time_saved": ts})

    def _time_saved(self, r, plan: dict) -> dict:
        from eval.tsb import baselines
        tasks = [t["task_id"] for t in plan["tasks"]]
        t_a = r["wall_seconds"] / 60.0 + float(plan.get("review_minutes_estimate") or 0)
        try:
            bl = baselines.load()
        except Exception as e:                              # noqa: BLE001
            return {"task_id": tasks[0], "baseline": "baselines unavailable", "error": type(e).__name__, "basis": "estimate"}
        if len(tasks) == 1:
            return baselines.time_saved(tasks[0], t_a, bl)
        per = [baselines.time_saved(t, t_a / len(tasks), bl) for t in tasks]
        return {"task_ids": tasks, "basis": "estimate", "t_a_minutes": round(t_a, 2), "per_task": per}

    def _emit_source(self, job_id: str, org_id: str, token: str):
        from . import citations
        if any(e["data"].get("citation_token") == token for e in self.events_after(job_id, 0) if e["type"] == "source"):
            return
        c = citations.resolve(self._db(), org_id, token)
        if c:
            self.emit(job_id, "source", {"citation_token": token, "doc_name": c["doc_name"], "page": c["page"], "quote": c["quote"], "url": c["url"], "as_of": c["as_of"],
                                         "kind": c["kind"], "xbrl_concept": c["xbrl_concept"]})

    def _pause(self, job_id: str, r, step_id: str, kind: str, payload: dict, t0: float):
        self._add_wall(job_id, t0)
        self._set_inputs(job_id, _pending={"step_id": step_id, "kind": kind})
        self._x("UPDATE jobs SET status='awaiting_approval' WHERE id=?", (job_id,))
        self.emit(job_id, "approval", {"step_id": step_id, "kind": kind, "payload": payload})
        self.emit(job_id, "status", {"status": "awaiting_approval", "step_id": step_id})
        self._publish(r["org_id"], "job.status", {"job_id": job_id, "status": "awaiting_approval", "deal_id": r["deal_id"]})
        self._notify(r, "awaiting_approval")

    # ------------------------------------------------------------------ schedules (parity item 25)
    def create_schedule(self, org_id: str, user_id: str, prompt: str, schedule: dict, deal_id: str | None = None, agent_id: str | None = None,
                        inputs: dict | None = None) -> dict:
        kind = schedule.get("kind")
        if kind not in ("once", "daily", "weekly", "interval"):
            raise ApiError(400, "bad_schedule", "The schedule kind must be once, daily, weekly or interval.", "Send schedule: {kind: 'daily', at: '07:30'}.")
        if not (prompt or agent_id):
            raise ApiError(400, "missing_prompt", "Say what should run on this schedule.", "Send a prompt or an agent_id.")
        if agent_id:
            from .agents import library
            library.resolve(self._db(), org_id, user_id, agent_id)
        nxt = self._first_run(schedule)
        sch = {**{k: schedule.get(k) for k in ("kind", "at", "weekday", "run_at", "interval_minutes", "email_summary") if schedule.get(k) is not None},
               "next_run": nxt, "last_run": None, "runs": 0}
        jid = new_id("job")
        self._x("INSERT INTO jobs(id, org_id, deal_id, user_id, agent_id, kind, prompt, status, inputs_json, created_at, schedule_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (jid, org_id, deal_id, user_id, agent_id, "schedule", prompt or "", "scheduled", _j(inputs or {}), now(), _j(sch)))
        try:
            self.state.audit(self._db(), org_id, user_id, "schedule.create", jid, {"schedule": sch})
        except Exception:                                   # noqa: BLE001
            pass
        return self.schedule_view(self._row(jid))

    def schedule_view(self, r) -> dict:
        return {"id": r["id"], "prompt": r["prompt"], "agent_id": r["agent_id"], "deal_id": r["deal_id"], "status": r["status"], "schedule": _l(r["schedule_json"], {}),
                "created_at": r["created_at"], "error": r["error"]}

    def _first_run(self, s: dict) -> str:
        t = self.clock()
        kind = s["kind"]
        try:
            if kind == "once":
                dt = _dt.datetime.fromisoformat(str(s["run_at"]).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_dt.timezone.utc)
                return _iso(dt.timestamp())
            if kind == "interval":
                m = int(s["interval_minutes"])
                if m < 5:
                    raise ValueError
                return _iso(t + m * 60)
            hh, mm = (int(x) for x in str(s.get("at", "07:00")).split(":"))
            base = _dt.datetime.fromtimestamp(t, _dt.timezone.utc).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if kind == "weekly":
                wd = int(s.get("weekday", 0))
                if not 0 <= wd <= 6:
                    raise ValueError
                base += _dt.timedelta(days=(wd - base.weekday()) % 7)
            while base.timestamp() <= t:
                base += _dt.timedelta(days=1 if kind == "daily" else 7)
            return _iso(base.timestamp())
        except (KeyError, ValueError, TypeError):
            raise ApiError(400, "bad_schedule", "The schedule details are not valid.",
                           "Use at 'HH:MM' (UTC), weekday 0-6, run_at as an ISO time, or interval_minutes of at least 5.") from None

    def tick(self, now_ts: float | None = None) -> list[str]:
        """Fire every schedule that is due; returns the job ids started. The scheduler thread calls this every few seconds."""
        t = self.clock() if now_ts is None else now_ts
        fired = []
        for r in self._q("SELECT * FROM jobs WHERE kind='schedule' AND status='scheduled'"):
            s = _l(r["schedule_json"], {})
            due = _dt.datetime.fromisoformat(s["next_run"].replace("Z", "+00:00")).timestamp()
            if due > t:
                continue
            err = None
            try:
                job = self.submit(r["org_id"], r["user_id"], r["prompt"], r["deal_id"], r["agent_id"], _l(r["inputs_json"], {}), source="schedule")
                fired.append(job["id"])
                self._x("UPDATE jobs SET parent_id=? WHERE id=?", (r["id"], job["id"]))
                s["runs"] = s.get("runs", 0) + 1
            except ApiError as e:
                err = e.message
            s["last_run"] = _iso(t)
            kind = s["kind"]
            status = "scheduled"
            if kind == "once":
                status = "finished"
            else:
                step = {"daily": 86400, "weekly": 7 * 86400, "interval": int(s.get("interval_minutes", 60)) * 60}[kind]
                while due <= t:
                    due += step
                s["next_run"] = _iso(due)
            self._x("UPDATE jobs SET schedule_json=?, status=?, error=? WHERE id=?", (_j(s), status, err, r["id"]))
        return fired

    def _sched_loop(self, every: float):
        while not self._stop.wait(every):
            try:
                self.tick()
            except Exception:                               # noqa: BLE001
                pass


# ====================================================================== module wiring
def init(state) -> JobService:
    global SERVICE
    if SERVICE is not None:
        SERVICE.shutdown()
    SERVICE = JobService(state)
    SERVICE.start()
    return SERVICE


def shutdown():
    global SERVICE
    if SERVICE is not None:
        SERVICE.shutdown()
        SERVICE = None


def svc() -> JobService:
    if SERVICE is None:
        raise ApiError(503, "jobs_unavailable", "The job runtime is not running.", "Start the server with the job service enabled.")
    return SERVICE


def _body(ctx) -> dict:
    b = ctx.json
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError(400, "bad_body", "The request body must be a JSON object.", "Send {\"prompt\": \"...\"}.")
    return b


def _create(ctx):
    ctx.require("member")
    b = _body(ctx)
    ins = b.get("inputs") or {}
    if not isinstance(ins, dict):
        raise ApiError(400, "bad_inputs", "inputs must be an object.", "Send inputs like {\"source_review\": false}.")
    job = svc().submit(ctx.org_id, ctx.user["id"], b.get("prompt", ""), b.get("deal_id"), b.get("agent_id"), ins, source="api" if b.get("source") == "api" else "app")
    return 201, {"job": job}


def _list(ctx):
    q = ctx.query
    try:
        limit = max(1, min(200, int(q.get("limit", 50))))
    except ValueError:
        raise ApiError(400, "bad_limit", "limit must be a number.", "Use ?limit=50.") from None
    sql, args = "SELECT * FROM jobs WHERE org_id=? AND kind='run'", [ctx.org_id]
    if q.get("deal_id"):
        sql += " AND deal_id=?"
        args.append(q["deal_id"])
    if q.get("status"):
        sql += " AND status=?"
        args.append(q["status"])
    if q.get("cursor"):
        ca, _, ci = q["cursor"].partition("|")
        sql += " AND (created_at<? OR (created_at=? AND id<?))"
        args += [ca, ca, ci]
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    rows = svc()._q(sql, args + [limit + 1])
    nxt = f"{rows[limit - 1]['created_at']}|{rows[limit - 1]['id']}" if len(rows) > limit else None
    return {"items": [svc().view(r, detail=False) for r in rows[:limit]], "next_cursor": nxt}


def _get(ctx):
    return {"job": svc().view(svc().get(ctx.org_id, ctx.params["job_id"]))}


def _events(ctx):
    s = svc()
    r = s.get(ctx.org_id, ctx.params["job_id"])
    raw = None
    for k, v in (ctx.headers or {}).items():
        if str(k).lower() == "last-event-id":
            raw = v
    raw = raw or ctx.query.get("last_event_id") or "0"
    try:
        last = max(0, int(raw))
    except ValueError:
        raise ApiError(400, "bad_last_event_id", "Last-Event-ID must be a number.", "Send the last seq you received.") from None
    return SSE(s.stream(r["id"], last), last_event_id=last)


def _cancel(ctx):
    ctx.require("member")
    ctx.audit("job.cancel", ctx.params["job_id"])
    return {"job": svc().cancel(ctx.org_id, ctx.params["job_id"])}


def _resume(ctx):
    ctx.require("member")
    ctx.audit("job.resume", ctx.params["job_id"])
    return {"job": svc().resume(ctx.org_id, ctx.params["job_id"])}


def _approve(ctx):
    ctx.require("member")
    svc().get(ctx.org_id, ctx.params["job_id"])               # 404 across orgs before any body validation
    b = _body(ctx)
    if not b.get("step"):
        raise ApiError(400, "missing_step", "Say which step you are approving.", "Send {\"step\": \"<step_id>\", \"payload\": {...}}; the step id is in the approval event.")
    if b.get("payload") is not None and not isinstance(b["payload"], dict):
        raise ApiError(400, "bad_payload", "payload must be an object.", "Send e.g. {\"titles\": {\"s2\": \"New title\"}}.")
    return {"job": svc().approve(ctx.org_id, ctx.params["job_id"], b["step"], b.get("payload"), ctx.user["id"])}


def _sched_create(ctx):
    ctx.require("member")
    b = _body(ctx)
    if not isinstance(b.get("schedule"), dict):
        raise ApiError(400, "missing_schedule", "Send a schedule.", "Use schedule: {kind: 'daily'|'weekly'|'once'|'interval', at: 'HH:MM', ...}.")
    return 201, {"schedule": svc().create_schedule(ctx.org_id, ctx.user["id"], b.get("prompt", ""), b["schedule"], b.get("deal_id"), b.get("agent_id"), b.get("inputs"))}


def _sched_list(ctx):
    rows = svc()._q("SELECT * FROM jobs WHERE org_id=? AND kind='schedule' ORDER BY created_at DESC", (ctx.org_id,))
    return {"items": [svc().schedule_view(r) for r in rows], "next_cursor": None}


def _sched_delete(ctx):
    ctx.require("member")
    s = svc()
    r = s._row(ctx.params["schedule_id"])
    if r is None or r["org_id"] != ctx.org_id or r["kind"] != "schedule":
        raise ApiError(404, "not_found", "No such schedule.")
    s._x("DELETE FROM jobs WHERE id=?", (r["id"],))
    ctx.audit("schedule.delete", r["id"])
    return {"ok": True}


ROUTES = [
    Route("POST", "/api/v1/jobs", _create, role="member"),
    Route("GET", "/api/v1/jobs", _list, role="viewer"),
    Route("GET", "/api/v1/jobs/{job_id}", _get, role="viewer"),
    Route("GET", "/api/v1/jobs/{job_id}/events", _events, role="viewer"),
    Route("POST", "/api/v1/jobs/{job_id}/cancel", _cancel, role="member"),
    Route("POST", "/api/v1/jobs/{job_id}/resume", _resume, role="member"),
    Route("POST", "/api/v1/jobs/{job_id}/approve", _approve, role="member"),
    Route("POST", "/api/v1/schedules", _sched_create, role="member"),
    Route("GET", "/api/v1/schedules", _sched_list, role="viewer"),
    Route("DELETE", "/api/v1/schedules/{schedule_id}", _sched_delete, role="member"),
]
