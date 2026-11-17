"""S6.0 durable research jobs on the SQLiteKV queue ``research``.

Layout in the KV file (``ACRETIA_JOBS_DB``, default ``storage/jobs.sqlite``); every key carries the org id, so
one org can never address another org's rows::

    job:{org}:{id}      Job row (+ request, user, timestamps)      written by submit / worker only
    result:{org}:{id}   ResearchResult JSON                         written once by the worker
    cancel:{org}:{id}   "1" when cancellation was requested
    ev:{org}:{id}:{n}   persisted event n (1-based);  evn:{org}:{id} is the counter
    review:{org}:{id}   source-review decision {decision, approver|reason, at}; written by approve / reject only

Source review (S6.1c, D-S6-07, parity item 24): when a workflow reaches its review gate the worker does not wait.
It persists the plan (``plan:{org}:{id}``: planned sources, deadline, workflow), sets the status to
``awaiting_review`` and ACKs the queue lease, so no worker is held and no lease can expire into a duplicate run.
``approve`` records the decision (``review:{org}:{id}``) and re-enqueues the job; a worker that dequeues it resumes
from the persisted plan: the gate passes at once (the replanned sources must equal the approved ones, otherwise the
job parks again) and the run continues from there. The review gate is the first step, so no completed step is ever
re-run. ``reject``, ``cancel`` and ``review_timeout_s`` (default 86400, checked on every status read and by
``worker_loop`` over the parked-job index) re-enqueue the job with a rejection so a worker ends it ``cancelled``.

    plan:{org}:{id}     {"workflow", "sources", "parked_at", "deadline", "review_timeout_s"}  written when parked
    parked:{n}          "org:id" index of parked jobs (``parkedn`` is the counter); swept by worker_loop
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

from om.contracts import Job, JobStep
from om.storage import SQLiteKV
from .api import API_VERSION, ResearchRequest, ResearchResult, run_research
from .workflows.base import Cancelled

QUEUE = "research"
MAX_ATTEMPTS = 3
_TERMINAL = ("succeeded", "failed", "cancelled")
SWEEP_S = 1.0
_kvs: dict[str, SQLiteKV] = {}
_kv_lock = threading.Lock()


class JobNotFound(KeyError):
    """Unknown job id, or a job that belongs to another org (deliberately indistinguishable)."""


def _kv(path: str | None = None) -> SQLiteKV:
    path = path or os.environ.get("ACRETIA_JOBS_DB", "storage/jobs.sqlite")
    with _kv_lock:
        if path not in _kvs:
            _kvs[path] = SQLiteKV(path)
        return _kvs[path]


def close_all() -> None:
    with _kv_lock:
        for kv in _kvs.values():
            kv.close()
        _kvs.clear()


def _now() -> str:
    from .api import _now as n
    return n()


def _load(kv, job_id, org_id) -> dict:
    raw = kv.get(f"job:{org_id}:{job_id}")
    if raw is None:
        raise JobNotFound(job_id)
    return json.loads(raw)


def _save(kv, org_id, row) -> None:
    row["updated_at"] = _now()
    kv.set(f"job:{org_id}:{row['job']['id']}", json.dumps(row, sort_keys=True))


def submit(request, *, org_id: str | None = None) -> str:
    """Persist a queued Job and enqueue it. The org comes from ``request.org_id`` (``org_id=`` must agree if given)."""
    if isinstance(request, dict):
        request = ResearchRequest.from_dict(request)
    request.validate()
    if org_id is not None and org_id != request.org_id:
        raise ValueError("org_id differs from request.org_id")
    kv, org = _kv(), request.org_id
    job_id = "res_" + uuid.uuid4().hex[:16]
    row = {"v": API_VERSION, "org_id": org, "user_id": request.user_id, "request": request.to_dict(),
           "created_at": _now(), "job": Job(id=job_id, kind="research", status="queued").to_dict()}
    _save(kv, org, row)
    kv.enqueue(QUEUE, json.dumps({"org_id": org, "job_id": job_id}))
    return job_id


def status(job_id: str, *, org_id: str = "local") -> Job:
    kv = _kv()
    row = _load(kv, job_id, org_id)
    if row["job"]["status"] == "awaiting_review" and _expire(kv, org_id, job_id):
        row = _load(kv, job_id, org_id)
    return Job.from_dict(row["job"])


def result(job_id: str, *, org_id: str = "local") -> ResearchResult | None:
    kv = _kv()
    _load(kv, job_id, org_id)
    raw = kv.get(f"result:{org_id}:{job_id}")
    return None if raw is None else ResearchResult.from_json(raw)


def cancel(job_id: str, *, org_id: str = "local") -> bool:
    """Request cancellation. Returns False if the job already finished. The worker honours it between steps."""
    kv = _kv()
    row = _load(kv, job_id, org_id)
    if row["job"]["status"] in _TERMINAL:
        return False
    kv.set(f"cancel:{org_id}:{job_id}", "1")
    if row["job"]["status"] == "awaiting_review":       # parked: no worker holds it, so queue it to be ended
        _decide(job_id, org_id, "rejected", "reason", "cancelled")
    return True


def _decide(job_id, org_id, decision, who_key, who) -> bool:
    """Record the review decision of a parked job and put the job back on the queue (a worker finishes it)."""
    kv = _kv()
    row = _load(kv, job_id, org_id)                     # JobNotFound for an unknown job or another org's job
    if row["job"]["status"] != "awaiting_review" or kv.get(f"review:{org_id}:{job_id}") is not None:
        return False
    rec = {"decision": decision, who_key: who, "at": _now()}
    kv.set(f"review:{org_id}:{job_id}", json.dumps(rec, sort_keys=True))
    if decision != "approved":
        kv.set(f"cancel:{org_id}:{job_id}", "1")        # the worker that picks it up ends it as cancelled
    row["job"]["status"] = "queued"
    row["review"] = rec
    _save(kv, org_id, row)
    _persist_event(kv, org_id, {"v": API_VERSION, "type": "source_review", "job_id": job_id, "ts": _now(),
                                "data": {"status": decision, **{who_key: who}}})
    kv.enqueue(QUEUE, json.dumps({"org_id": org_id, "job_id": job_id}))
    return True


def approve(job_id: str, org_id: str = "local", approver: str | None = None) -> bool:
    """Approve the planned sources of a job in ``awaiting_review``; the job resumes. False if it is not waiting."""
    return _decide(job_id, org_id, "approved", "approver", approver)


def reject(job_id: str, reason: str | None = None, *, org_id: str = "local") -> bool:
    """Reject the planned sources: the job ends ``cancelled``. False if it is not waiting."""
    return _decide(job_id, org_id, "rejected", "reason", reason)


def review_sources(job_id: str, *, org_id: str = "local") -> list | None:
    """Planned sources of the latest ``source_review`` request, or None when the job never reached the gate."""
    for e in reversed(events(job_id, org_id=org_id)):
        if e["type"] == "source_review" and (e.get("data") or {}).get("status") == "awaiting_review":
            return e["data"].get("sources")
    return None


def _persist_event(kv, org_id, ev: dict) -> dict:
    n = kv.incr(f"evn:{org_id}:{ev['job_id']}")
    ev = dict(ev, seq=n)
    kv.set(f"ev:{org_id}:{ev['job_id']}:{n}", json.dumps(ev, sort_keys=True))
    return ev


def events(job_id: str, after_seq: int = 0, *, org_id: str = "local", limit: int = 500) -> list[dict]:
    kv = _kv()
    _load(kv, job_id, org_id)
    top = int(kv.get(f"evn:{org_id}:{job_id}", 0) or 0)
    out = []
    for n in range(max(after_seq, 0) + 1, top + 1):
        raw = kv.get(f"ev:{org_id}:{job_id}:{n}")
        if raw is not None:
            out.append(json.loads(raw))
        if len(out) >= limit:
            break
    return out


class _KVCancel:
    """threading.Event look-alike backed by the persisted cancel flag (cancel may come from another process)."""

    def __init__(self, kv, org_id, job_id):
        self._kv, self._key = kv, f"cancel:{org_id}:{job_id}"

    def is_set(self) -> bool:
        return self._kv.get(self._key) is not None


def _expire(kv, org, job_id) -> bool:
    """Reject a parked job whose review deadline has passed (it is then queued to be cancelled). True if it did."""
    raw = kv.get(f"plan:{org}:{job_id}")
    if raw is None or kv.get(f"review:{org}:{job_id}") is not None:
        return False
    if time.time() <= float(json.loads(raw).get("deadline", float("inf"))):
        return False
    return _decide(job_id, org, "rejected", "reason", "review timeout")


def _sweep_parked(kv) -> None:
    """Expire parked jobs past their deadline; drop index entries of jobs that are no longer parked."""
    for n in range(1, int(kv.get("parkedn", 0) or 0) + 1):
        ref = kv.get(f"parked:{n}")
        if ref is None:
            continue
        org, job_id = ref.split(":", 1)
        try:
            row = _load(kv, job_id, org)
        except JobNotFound:
            kv.delete(f"parked:{n}")
            continue
        if row["job"]["status"] != "awaiting_review":
            kv.delete(f"parked:{n}")
        else:
            _expire(kv, org, job_id)


def _park(kv, lease, org, job_id, row, sources) -> None:
    """The review gate was reached: persist the plan, mark the job awaiting_review and release the queue lease."""
    timeout = float(row["request"].get("options", {}).get("review_timeout_s", 86400))
    kv.set(f"plan:{org}:{job_id}", json.dumps(
        {"workflow": row["request"].get("workflow"), "sources": sources, "parked_at": _now(),
         "deadline": time.time() + timeout, "review_timeout_s": timeout}, sort_keys=True))
    cur = _load(kv, job_id, org)
    cur["job"]["status"] = "awaiting_review"
    _save(kv, org, cur)
    kv.set(f"parked:{kv.incr('parkedn')}", f"{org}:{job_id}")
    kv.ack(lease)


def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, default=str)


def _process(kv, lease, adapter, tools, evidence_dir) -> None:
    msg = json.loads(lease.payload)
    org, job_id = msg["org_id"], msg["job_id"]
    try:
        row = _load(kv, job_id, org)
    except JobNotFound:
        kv.ack(lease)
        return
    if kv.get(f"result:{org}:{job_id}") is not None:
        kv.ack(lease)                       # idempotent: a duplicate delivery of a finished job
        return
    if lease.attempts > MAX_ATTEMPTS:
        row["job"].update(status="failed", attempts=lease.attempts, error="max attempts exceeded")
        _save(kv, org, row)
        kv.ack(lease)
        return
    raw_rev = kv.get(f"review:{org}:{job_id}")
    decision = json.loads(raw_rev)["decision"] if raw_rev is not None else None
    if row["job"]["status"] == "awaiting_review" and decision is None:
        kv.ack(lease)                       # already parked: a stale delivery holds nothing
        return
    raw_plan = kv.get(f"plan:{org}:{job_id}")
    plan = json.loads(raw_plan) if raw_plan is not None else None
    resuming = decision == "approved" and plan is not None
    row["job"].update(status="running", attempts=lease.attempts)
    _save(kv, org, row)
    cancel = _KVCancel(kv, org, job_id)
    parked: dict = {}

    def on_event(e):
        if parked:
            return None                     # the parked run's trailing step/done events are not job history
        if resuming and e.get("type") == "source_review" and (e.get("data") or {}).get("status") == "awaiting_review":
            return None                     # already recorded when the job parked
        return _persist_event(kv, org, e)

    def review(sources) -> bool:
        if resuming and _canon(sources) == _canon(plan["sources"]):
            return True                     # approved sources == the planned ones: carry on, never ask twice
        if decision == "rejected":
            return False
        if resuming:                        # the plan changed since approval: the approval no longer covers it
            kv.delete(f"review:{org}:{job_id}")
        parked["sources"] = sources
        raise Cancelled()                   # park: the run stops here; _process releases the lease below
    ev_dir = evidence_dir or os.environ.get("ACRETIA_EVIDENCE_DIR", "storage/evidence")
    res = run_research(ResearchRequest.from_dict(row["request"]), adapter=adapter, tools=tools,
                       evidence_dir=ev_dir, job_id=job_id, cancel=cancel,
                       on_event=on_event, review=review)
    if parked:
        _park(kv, lease, org, job_id, row, parked["sources"])
        return
    kv.set(f"result:{org}:{job_id}", res.to_json())
    row = _load(kv, job_id, org)                        # approve/reject may have added a "review" record meanwhile
    row["job"].update(status=res.status, steps=[s.to_dict() for s in res.steps], tokens=res.tokens,
                      cost_usd=res.cost_usd, error=res.error)
    Job.from_dict(row["job"])
    _save(kv, org, row)
    kv.ack(lease)


def worker_loop(stop_event: threading.Event, adapter=None, *, tools=None, evidence_dir=None, lease: float = 300.0,
                poll: float = 0.2, db_path: str | None = None) -> None:
    """Dequeue -> run_research -> ack. A crash leaves the item leased; once the lease expires it is delivered
    again and re-run (same job_id, evidence chain continues, result written once). A job that reaches its review
    gate is parked (lease released), so ``lease`` only has to cover one run, never a human's review time."""
    kv = _kv(db_path)
    last_sweep = 0.0
    while not stop_event.is_set():
        if time.monotonic() - last_sweep >= SWEEP_S:
            last_sweep = time.monotonic()
            try:
                _sweep_parked(kv)
            except Exception:       # noqa: BLE001 - a sweep failure must not stop the worker
                pass
        item = kv.dequeue(QUEUE, lease=lease)
        if item is None:
            stop_event.wait(poll)
            continue
        try:
            _process(kv, item, adapter, tools, evidence_dir)
        except Exception:
            kv.nack(item, delay=1.0)
            time.sleep(0)
