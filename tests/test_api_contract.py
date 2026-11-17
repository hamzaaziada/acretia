"""API contract: the exact keys the frontend consumes (frontend/src/api/types.ts mirrors these).

Runs real jobs in-process through `om.api.jobs` (replay mode, AAPL fixture, zero sockets), captures every persisted event and
asserts, per event type and for the job JSON, that the required keys are present and that no undeclared key appears. A rename on
either side fails here before it shows up as `Status.Undefined` or `$NaN` in the browser.
"""
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_ENV = {}

from om.api import jobs  # noqa: E402
from om.api.agents import engines  # noqa: E402
from om.api.http import ApiError  # noqa: E402
from tests.test_api_jobs import ctx_for, make_state, wait_status  # noqa: E402

_real_connect = socket.socket.connect


def _no_net(self, *a, **k):
    raise AssertionError("network access attempted in an offline test")


def setUpModule():
    socket.socket.connect = _no_net
    for k, v in (("ACRETIA_LLM_MODE", "replay"), ("ACRETIA_LLM_FIXTURES", str(engines.REPLAY_DIR))):
        _ENV[k] = os.environ.get(k)
        os.environ[k] = v


def tearDownModule():
    socket.socket.connect = _real_connect
    for k, v in _ENV.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# (required, optional) key sets per event type: required must all be present on every event; nothing outside required|optional may appear.
EVENT_KEYS = {
    "plan": ({"steps", "estimate"}, {"method", "tasks", "overrides", "review_minutes_estimate"}),
    "step": ({"id", "status", "title"}, {"detail", "engine", "started_at", "finished_at", "seconds", "tokens", "cost_usd", "error", "hint", "notes", "badges"}),
    "source": ({"citation_token", "doc_name", "page", "quote", "url", "as_of"}, {"kind", "xbrl_concept"}),
    "cost": ({"tokens", "cost_usd"}, set()),
    "deliverable": ({"deal_id", "name", "version", "kind", "url"}, {"sha256", "size", "badges"}),
    "approval": ({"step_id", "kind", "payload"}, set()),
    "status": ({"status"}, {"error", "hint", "step_id", "approved", "resumed", "deal_id", "wall_seconds", "time_saved", "failed_steps"}),
}
ENVELOPE = {"seq", "at"}                                    # added by the SSE stream to every event's data

JOB_KEYS = {"id", "kind", "status", "prompt", "deal_id", "deal_name", "agent_id", "agent_name", "source", "created_at", "started_at", "finished_at",
            "tokens", "cost_usd", "wall_seconds", "error", "hint", "time_saved", "resume_from", "user_id"}
JOB_DETAIL_KEYS = {"plan", "steps", "deliverables", "pending_approval", "feedback"}
STEP_KEYS = {"id", "task", "title", "engine", "status", "detail", "started_at", "finished_at", "seconds", "tokens", "cost_usd", "error", "hint", "notes"}
SOURCE_ITEM_KEYS = {"id", "label", "kind", "detail", "available", "task"}
TIME_SAVED_KEYS = {"task_id", "basis", "t_h_minutes", "t_a_minutes", "pct"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.st = make_state(self.tmp)
        self.svc = jobs.init(self.st)

    def tearDown(self):
        jobs.shutdown()
        time.sleep(0.05)
        self.st._conn.close()

    def check_events(self, evs):
        seen = {}
        for e in evs:
            self.assertIn(e["type"], EVENT_KEYS, f"undeclared event type {e['type']}")
            req, opt = EVENT_KEYS[e["type"]]
            keys = set(e["data"])
            self.assertTrue(req <= keys, f"{e['type']} is missing {sorted(req - keys)}")
            self.assertTrue(keys <= req | opt, f"{e['type']} has undeclared keys {sorted(keys - req - opt)}")
            seen.setdefault(e["type"], []).append(e["data"])
        return seen


class FullRun(Base):
    """AAPL 3-statement + DCF, with the pre-run source review in front of it."""

    def setUp(self):
        super().setUp()
        j = self.svc.submit("org_a", "usr_1", "3-statement + DCF for Apple at 9% WACC")
        self.jid = j["id"]
        wait_status(self.svc, self.jid, want=("awaiting_approval",))
        self.pending_events = self.svc.events_after(self.jid, 0)
        self.pending_view = self.svc.view(self.svc._row(self.jid))
        # approve body: {step, payload: {selected: [source id...], skip_next_time}} (see om/api/jobs.py _approve)
        self.svc.approve("org_a", self.jid, "source_review", {"selected": [], "skip_next_time": False}, "usr_1")
        wait_status(self.svc, self.jid)
        self.events = self.svc.events_after(self.jid, 0)
        self.seen = self.check_events(self.events)

    def test_every_event_type_has_exactly_the_consumed_keys(self):
        for t in ("plan", "step", "source", "cost", "deliverable", "approval", "status"):
            self.assertIn(t, self.seen, f"no {t} event in a full run")

    def test_plan_steps_are_id_title_tool_engine(self):
        plan = self.seen["plan"][0]
        for s in plan["steps"]:
            self.assertTrue({"id", "title", "tool", "engine"} <= set(s))
        self.assertTrue({"cost_usd", "seconds"} <= set(plan["estimate"]))

    def test_step_events_walk_running_then_done_with_telemetry(self):
        by = {}
        for d in self.seen["step"]:
            by.setdefault(d["id"], []).append(d["status"])
        plan_ids = [s["id"] for s in self.seen["plan"][0]["steps"]]
        self.assertEqual(list(by), plan_ids)
        for sid, st in by.items():
            self.assertEqual(st, ["running", "done"], sid)
        done = [d for d in self.seen["step"] if d["status"] == "done"]
        for d in done:
            for k in ("seconds", "cost_usd", "tokens", "started_at", "finished_at"):
                self.assertIsNotNone(d[k], f"{d['id']}.{k}")
            self.assertIsInstance(d["seconds"], (int, float))
            self.assertIsInstance(d["cost_usd"], (int, float))

    def test_cost_event_is_finite_numbers(self):
        for c in self.seen["cost"]:
            self.assertIsInstance(c["tokens"], int)
            self.assertIsInstance(c["cost_usd"], (int, float))
            self.assertEqual(c["cost_usd"], c["cost_usd"])   # not NaN

    def test_source_events_resolve_to_documents(self):
        s = self.seen["source"][0]
        self.assertTrue(s["citation_token"] and s["doc_name"] and s["quote"])

    def test_deliverable_event_routes_by_kind(self):
        d = self.seen["deliverable"][0]
        self.assertEqual(d["kind"], "xlsx")
        self.assertTrue(d["deal_id"].startswith("deal"))
        self.assertTrue(d["url"].startswith(f"/api/v1/deals/{d['deal_id']}/deliverables/"))

    def test_source_review_approval_event(self):
        ap = [e for e in self.pending_events if e["type"] == "approval"][0]["data"]
        self.assertEqual((ap["kind"], ap["step_id"]), ("sources", "source_review"))
        self.assertTrue(ap["payload"]["sources"])
        for s in ap["payload"]["sources"]:
            self.assertEqual(set(s), SOURCE_ITEM_KEYS)
            self.assertIsInstance(s["id"], str)
        ids = [s["id"] for s in ap["payload"]["sources"]]
        self.assertEqual(len(ids), len(set(ids)))
        st = [e for e in self.pending_events if e["type"] == "status"][-1]["data"]
        self.assertEqual((st["status"], st["step_id"]), ("awaiting_approval", "source_review"))

    def test_final_status_event_carries_deal_and_time_saved(self):
        st = self.seen["status"][-1]
        self.assertEqual(st["status"], "done")
        self.assertTrue(st["deal_id"])
        self.assertTrue(TIME_SAVED_KEYS <= set(st["time_saved"]))
        self.assertTrue({"low", "mid", "high"} == set(st["time_saved"]["pct"]))      # pct is an object, not a number
        self.assertTrue({"low", "mid", "high", "source"} <= set(st["time_saved"]["t_h_minutes"]))

    def test_job_json_keys_and_resolved_deal(self):
        v = self.svc.view(self.svc._row(self.jid))
        self.assertEqual(set(v), JOB_KEYS | JOB_DETAIL_KEYS)
        self.assertEqual((v["kind"], v["status"]), ("run", "done"))
        self.assertEqual(v["deal_id"], self.seen["deliverable"][0]["deal_id"])      # resolved once known
        self.assertTrue(v["deal_name"] and v["agent_name"])
        self.assertIsInstance(v["cost_usd"], (int, float))
        self.assertIsInstance(v["tokens"], int)
        for s in v["steps"]:
            self.assertEqual(set(s), STEP_KEYS)
            self.assertEqual(s["status"], "done")
        self.assertEqual(v["deliverables"][0]["name"], "AAPL_dcf_model.xlsx")
        self.assertTrue(TIME_SAVED_KEYS <= set(v["time_saved"]))
        lst = self.svc.view(self.svc._row(self.jid), detail=False)
        self.assertEqual(set(lst), JOB_KEYS)

    def test_pending_job_json_has_no_deal_yet_and_a_pending_approval(self):
        v = self.pending_view
        self.assertEqual(v["status"], "awaiting_approval")
        self.assertIsNone(v["deal_id"])
        self.assertEqual(v["pending_approval"], {"step_id": "source_review", "kind": "sources"})

    def test_sse_frames_carry_seq_as_event_id(self):
        frames = list(jobs._events(ctx_for(self.st, params={"job_id": self.jid})).iterator)
        self.assertTrue(all(len(f) == 3 for f in frames))
        self.assertEqual([f[0] for f in frames], [e["seq"] for e in self.events])
        for seq, typ, data in frames:
            self.assertEqual(data["seq"], seq)
            self.assertEqual(set(data) - set(EVENT_KEYS[typ][0] | EVENT_KEYS[typ][1]), ENVELOPE)

    def test_approve_body_validation(self):
        with self.assertRaises(ApiError) as cm:
            jobs._approve(ctx_for(self.st, json={"step": "source_review", "payload": {"selected": "all"}}, params={"job_id": self.jid}))
        self.assertEqual(cm.exception.status, 400)


class GhostDeck(Base):
    def test_ghost_deck_approval_shape_and_titles_edit(self):
        j = self.svc.submit("org_a", "usr_1", "Company profile deck for Apple", inputs={"source_review": False})
        wait_status(self.svc, j["id"], want=("awaiting_approval",))
        ap = [e for e in self.svc.events_after(j["id"], 0) if e["type"] == "approval"][-1]["data"]
        self.assertEqual(ap["kind"], "ghost_deck")
        self.assertTrue(ap["payload"]["titles"])
        for t in ap["payload"]["titles"]:
            self.assertTrue({"id", "title", "archetype_hint"} <= set(t))
        ids = [t["id"] for t in ap["payload"]["titles"]]
        keep = ids[:3]
        # approve body: {step, payload: {titles: {slide id: title}, order: [kept slide ids]}}
        self.svc.approve("org_a", j["id"], ap["step_id"], {"titles": {keep[0]: "Edited cover"}, "order": keep}, "usr_1")
        r = wait_status(self.svc, j["id"])
        self.assertEqual(r["status"], "done")
        steps = json.loads(r["steps_json"])
        gd = [s for s in steps if s["id"].endswith("approve_outline")][0]["output"]["ghost"]
        self.assertEqual([s["id"] for s in gd["slides"]], keep)
        self.assertEqual(gd["slides"][0]["title"], "Edited cover")
        self.check_events(self.svc.events_after(j["id"], 0))


class Feedback(Base):
    def run_one(self):
        j = self.svc.submit("org_a", "usr_1", "DCF for Apple", inputs={"source_review": False})
        wait_status(self.svc, j["id"])
        return j["id"]

    def post(self, jid, body, org="org_a", uid="usr_1", role="member"):
        return jobs._feedback(ctx_for(self.st, org=org, uid=uid, role=role, json=body, params={"job_id": jid}))

    def test_feedback_roundtrip_tenancy_and_audit(self):
        jid = self.run_one()
        status, out = self.post(jid, {"rating": "up", "comment": "Great"})
        self.assertEqual(status, 201)
        self.assertEqual(set(out["feedback"]), {"job_id", "rating", "comment", "updated_at", "up", "down"})
        self.assertEqual((out["feedback"]["up"], out["feedback"]["down"]), (1, 0))
        _, out = self.post(jid, {"rating": "down"})                     # replaces this user's rating, keeps the comment
        self.assertEqual((out["feedback"]["up"], out["feedback"]["down"], out["feedback"]["comment"]), (0, 1, "Great"))
        _, out = self.post(jid, {"rating": "up"}, uid="usr_2", role="viewer")   # viewers may rate too
        self.assertEqual((out["feedback"]["up"], out["feedback"]["down"]), (1, 1))
        self.assertEqual(self.svc.view(self.svc._row(jid))["feedback"], {"up": 1, "down": 1})
        with self.assertRaises(ApiError) as cm:                         # another org sees a 404
            self.post(jid, {"rating": "up"}, org="org_b")
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(ApiError) as cm:
            self.post(jid, {"rating": "meh"})
        self.assertEqual(cm.exception.status, 400)
        self.assertTrue(cm.exception.hint)
        self.assertIn("job.feedback", [a[1] for a in self.st.log.audits])


class LibraryAndAgents(unittest.TestCase):
    def test_agent_views_carry_the_keys_the_ui_reads(self):
        from om.api.agents import library
        tmp = Path(tempfile.mkdtemp())
        st = make_state(tmp)
        try:
            items = library._all(st._conn, "org_a", "usr_1")
            for a in items:
                self.assertTrue({"id", "name", "description", "tags", "kind", "builtin", "task_id", "shared", "enabled", "pinned"} <= set(a))
            self.assertTrue(any(a["task_id"] == "dcf" for a in items))
        finally:
            st._conn.close()


if __name__ == "__main__":
    unittest.main()
