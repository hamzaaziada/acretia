"""Agent library and planner: 14-task coverage, "/" skills, overrides, saved agents, search, admin toggle, plus the document/deck-edit agents. Offline."""
import io
import json
import os
import socket
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_ENV = {}

from om.api import jobs  # noqa: E402
from om.api.agents import catalogue as C  # noqa: E402
from om.api.agents import engines, library, planner  # noqa: E402
from om.api.http import ApiError  # noqa: E402
from tests.test_api_jobs import ctx_for, make_state, wait_status  # noqa: E402

_real_connect = socket.socket.connect


def setUpModule():
    socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network access attempted"))
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


PROMPTS = [
    ("comps", "Spread trading comps for Apple vs peers"), ("comps", "comparable companies analysis for AAPL"), ("comps", "Comps for $MSFT vs AAPL"),
    ("comps", "peer multiples table for Apple"), ("comps", "/comps Apple"),
    ("precedents", "precedent transactions for the sector"), ("precedents", "transaction comps for Apple"), ("precedents", "M&A comps table"),
    ("three_statement", "Build a 3-statement model for Apple"), ("three_statement", "three statement model for AAPL"),
    ("three_statement", "integrated financial model for Microsoft"), ("three_statement", "operating model for ElSewedy"), ("three_statement", "build me a model of MSFT"),
    ("dcf", "DCF for Apple"), ("dcf", "dcf of AAPL at 9% WACC"), ("dcf", "discounted cash flow valuation of Microsoft"), ("dcf", "What is Apple worth?"),
    ("dcf", "intrinsic value of $AAPL with terminal growth 2.5%"), ("dcf", "valuation of Apple"),
    ("lbo", "LBO for Apple"), ("lbo", "leveraged buyout model for AAPL"), ("lbo", "sponsor returns on ElSewedy"), ("lbo", "paper LBO of Microsoft"),
    ("merger", "Merger model Apple acquires Microsoft"), ("merger", "accretion dilution analysis AAPL MSFT"), ("merger", "pro forma EPS for Apple buying Microsoft"),
    ("vdr_review", "First pass review of the data room"), ("vdr_review", "Red flags in the VDR"), ("vdr_review", "Review the CIM and flag missing documents"),
    ("profile", "Company profile for Apple"), ("profile", "One-pager on Microsoft"), ("profile", "company overview of ElSewedy"),
    ("pitchbook_section", "Pitchbook section on Apple's financial profile"), ("pitchbook_section", "pitch book pages for AAPL"),
    ("teaser", "Draft a teaser for ElSewedy"), ("teaser", "teaser deck Apple"),
    ("ic_memo", "IC memo for Apple"), ("ic_memo", "Investment committee memo on Microsoft"), ("ic_memo", "draft an investment memo"),
    ("earnings_update", "Roll forward the Apple model"), ("earnings_update", "earnings model update for AAPL"), ("earnings_update", "update the model for the latest 10-K"),
    ("earnings_recap", "Earnings recap for Apple"), ("earnings_recap", "summarize the earnings call for MSFT"), ("earnings_recap", "Q3 results summary for AAPL"),
    ("buyer_list", "Buyer list for ElSewedy"), ("buyer_list", "Who would buy Apple?"), ("buyer_list", "potential acquirers of Microsoft"),
    ("deck_edit", "Make slide 2 a waterfall"), ("deck_edit", "Retitle slide 3 to 'Margins expanded'"),
    ("model_edit", "Set WACC to 9% in the model"), ("model_edit", "Change terminal growth to 2%"),
    ("diligence_grid", "Diligence grid of change of control clauses"), ("diligence_grid", "Ask these questions of every document"),
    ("tick_and_tie", "Tick and tie the deck"), ("tick_and_tie", "Cross-check numbers between the model and the deck"), ("tick_and_tie", "tie out the numbers"),
]


class PlannerTests(unittest.TestCase):
    def test_catalogue_has_the_14_tasks_and_extras(self):
        for t in C.TASK_IDS_14 + C.EXTRA_TASKS:
            spec = C.CATALOGUE[t]
            self.assertTrue(spec["name"] and len(spec["description"]) > 40, t)
            self.assertTrue(spec["steps"] and spec["outputs"] and spec["review_minutes_estimate"] > 0, t)
            for s in spec["steps"]:
                self.assertIn(s["fn"], engines.STEP_FNS, f"{t}.{s['fn']}")
        self.assertEqual(len(C.TASK_IDS_14), 14)

    def test_planner_maps_at_least_40_varied_prompts_across_all_14_tasks(self):
        self.assertGreaterEqual(len(PROMPTS), 40)
        seen = set()
        for want, p in PROMPTS:
            plan = planner.plan_prompt(p)
            self.assertEqual(plan["tasks"][0]["task_id"], want, p)
            self.assertEqual(plan["tasks"][0]["task_id"], plan["steps"][0]["task"])
            seen.add(want)
        self.assertTrue(set(C.TASK_IDS_14) <= seen)

    def test_entities_tickers_names_and_deal_target(self):
        self.assertEqual(planner.plan_prompt("DCF for $AAPL")["tasks"][0]["inputs"]["ticker"], "AAPL")
        self.assertEqual(planner.plan_prompt("dcf apple")["tasks"][0]["inputs"]["ticker"], "AAPL")
        self.assertEqual(planner.plan_prompt("DCF for El Sewedy")["tasks"][0]["inputs"]["ticker"], "SWDY")
        self.assertEqual(planner.plan_prompt("DCF for Microsoft")["tasks"][0]["inputs"]["ticker"], "MSFT")
        self.assertEqual(planner.plan_prompt("DCF for XYZ")["tasks"][0]["inputs"]["ticker"], "XYZ")
        p = planner.plan_prompt("DCF", deal={"name": "Project Nile — ElSewedy Electric"})
        self.assertEqual(p["tasks"][0]["inputs"]["ticker"], "SWDY")
        c = planner.plan_prompt("Comps for Apple vs MSFT and GOOGL")["tasks"][0]["inputs"]
        self.assertEqual((c["ticker"], c["peers"]), ("AAPL", ["MSFT", "GOOGL"]))
        m = planner.plan_prompt("Merger model Apple acquires Microsoft")["tasks"][0]["inputs"]
        self.assertEqual((m["ticker"], m["target"]), ("AAPL", "MSFT"))

    def test_overrides(self):
        o = planner.extract_overrides("DCF with 9% WACC and terminal growth of 2.5%, 5-year forecast, 12x exit multiple")
        self.assertEqual(o, {"wacc": 0.09, "terminal_growth": 0.025, "years": 5, "exit_multiple": 12.0})
        self.assertEqual(planner.extract_overrides("WACC of 8.5%")["wacc"], 0.085)
        self.assertEqual(planner.extract_overrides("LBO at a 30% premium")["premium"], 0.30)
        ins = planner.plan_prompt("DCF for Apple at 9% WACC")["tasks"][0]["inputs"]
        self.assertEqual(ins["wacc"], 0.09)

    def test_output_asks_and_slash_skills(self):
        p = planner.plan_prompt("Spread trading comps for Apple vs peers and add a football field")
        self.assertEqual(p["outputs"], ["football_field"])
        p = planner.plan_prompt("/comps /football-field Apple")
        self.assertEqual([t["task_id"] for t in p["tasks"]], ["comps"])
        self.assertEqual(p["outputs"], ["football_field"])
        p = planner.plan_prompt("/dcf /football-field Apple")
        self.assertIn("football_field", [s["fn"] for s in p["steps"]])
        p = planner.plan_prompt("/dcf /lbo /merger Apple Microsoft")
        self.assertEqual([t["task_id"] for t in p["tasks"]], ["dcf", "lbo", "merger"])
        self.assertEqual(len({s["id"] for s in p["steps"]}), len(p["steps"]))                 # step ids unique across the combined plan
        self.assertEqual(p["method"], "skills")
        self.assertEqual(planner.plan_prompt("waterfall of revenue /dcf Apple")["outputs"], ["waterfall"])

    def test_unknown_skill_lists_skills(self):
        with self.assertRaises(planner.PlanError) as cm:
            planner.plan_prompt("/frobnicate Apple")
        self.assertIn("/dcf", cm.exception.hint)

    def test_unmatched_prompt_hint_and_adapter_path(self):
        with self.assertRaises(planner.PlanError) as cm:
            planner.plan_prompt("Tell me a joke about elephants")
        self.assertEqual(cm.exception.hint, "Try naming a task, e.g. 'DCF for Apple', or pick an agent from the library.")

        calls = []

        class Fake:
            def chat(self, msgs, **kw):
                calls.append(kw)
                return SimpleNamespace(data={"task_id": "comps"})
        plan = planner.plan_prompt("which listed firms look cheap next to Apple", adapter=Fake())
        self.assertEqual((plan["method"], plan["tasks"][0]["task_id"]), ("adapter", "comps"))
        self.assertIn("json_schema", calls[0])

        class Boom:
            def chat(self, *a, **k):
                raise RuntimeError("no fixture")
        with self.assertRaises(planner.PlanError):
            planner.plan_prompt("which listed firms look cheap", adapter=Boom())

    def test_plan_has_estimates(self):
        p = planner.plan_prompt("DCF for Apple")
        self.assertGreater(p["estimate"]["seconds"], 0)
        self.assertIn("cost_usd", p["estimate"])
        self.assertEqual([s["fn"] for s in p["steps"]], ["resolve", "statements", "build_dcf", "check_model", "deliver"])
        self.assertEqual(p["review_minutes_estimate"], 15)


class LibraryBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.st = make_state(self.tmp)
        self.svc = jobs.init(self.st)

    def tearDown(self):
        jobs.shutdown()
        self.st._conn.close()

    def c(self, uid="usr_1", role="member", org="org_a", **kw):
        return ctx_for(self.st, org=org, role=role, uid=uid, **kw)

    def create(self, uid="usr_1", **body):
        status, out = library._create(self.c(uid, json=body))
        self.assertEqual(status, 201)
        return out["agent"]


class LibraryTests(LibraryBase):
    def test_list_has_all_builtins(self):
        items = library._list(self.c(role="viewer"))["items"]
        ids = {i["id"] for i in items}
        for t in C.TASK_IDS_14 + C.EXTRA_TASKS:
            self.assertIn(C.builtin_id(t), ids)
        dcf = [i for i in items if i["task_id"] == "dcf"][0]
        self.assertTrue(dcf["builtin"] and dcf["enabled"] and dcf["steps"] and dcf["review_minutes_estimate"] == 15)

    def test_search_by_description_and_tag(self):
        names = lambda **q: [i["task_id"] for i in library._list(self.c(query=q))["items"]]
        self.assertEqual(names(q="sources and uses")[0], "lbo")
        self.assertIn("comps", names(q="quartile statistics"))
        self.assertIn("vdr_review", names(q="red flags"))
        self.assertNotIn("dcf", names(q="red flags"))
        self.assertEqual(names(q="zzzz nonsense"), [])
        excel = names(tag="excel")
        self.assertIn("lbo", excel)
        self.assertNotIn("teaser", excel)
        self.assertEqual(names(q="DCF")[0], "dcf")                       # a name hit outranks description hits

    def test_builtins_read_only_but_pin_and_owner_toggle(self):
        aid = C.builtin_id("dcf")
        with self.assertRaises(ApiError) as cm:
            library._patch(self.c(params={"agent_id": aid}, json={"name": "x"}))
        self.assertEqual((cm.exception.status, cm.exception.code), (403, "builtin_read_only"))
        with self.assertRaises(ApiError) as cm:
            library._delete(self.c(params={"agent_id": aid}))
        self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(ApiError) as cm:
            library._enabled(self.c(params={"agent_id": aid}, json={"enabled": False}))                   # a member may not toggle
        self.assertEqual(cm.exception.status, 403)
        out = library._pin(self.c(role="viewer", params={"agent_id": aid}, json={"pinned": True}))
        self.assertTrue(out["agent"]["pinned"])
        first = library._list(self.c())["items"][0]
        self.assertEqual(first["id"], aid)                               # pinned agents sort first
        self.assertFalse(library._list(self.c(uid="usr_2"))["items"][0]["pinned"])                    # pins are per user
        out = library._pin(self.c(params={"agent_id": aid}, json={"pinned": False}))
        self.assertFalse(out["agent"]["pinned"])

    def test_admin_disable_hides_from_search_and_blocks_runs(self):
        aid = C.builtin_id("dcf")
        out = library._enabled(self.c("usr_o", "owner", params={"agent_id": aid}, json={"enabled": False}))
        self.assertFalse(out["agent"]["enabled"])
        self.assertNotIn("dcf", [i["task_id"] for i in library._list(self.c(query={"q": "dcf"}))["items"]])
        self.assertNotIn("dcf", [i["task_id"] for i in library._list(self.c("usr_o", "owner", query={}))["items"]])
        self.assertIn("dcf", [i["task_id"] for i in library._list(self.c("usr_o", "owner", query={"include_disabled": "1"}))["items"]])
        with self.assertRaises(ApiError) as cm:
            library._run(self.c(params={"agent_id": aid}, json={"inputs": {"ticker": "AAPL"}}))
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "agent_disabled"))
        self.assertTrue(cm.exception.hint)
        with self.assertRaises(ApiError):
            self.svc.submit("org_a", "usr_1", "DCF for Apple", agent_id=aid)
        with self.assertRaises(ApiError) as cm:
            library._get(self.c(params={"agent_id": aid}))
        self.assertEqual(cm.exception.status, 404)
        library._enabled(self.c("usr_o", "owner", params={"agent_id": aid}, json={"enabled": True}))
        self.assertIn("dcf", [i["task_id"] for i in library._list(self.c(query={"q": "dcf"}))["items"]])
        with self.assertRaises(ApiError) as cm:
            library._enabled(self.c("usr_o", "owner", params={"agent_id": aid}, json={"enabled": "no"}))
        self.assertEqual(cm.exception.status, 400)

    def test_disable_is_per_org(self):
        aid = C.builtin_id("dcf")
        library._enabled(self.c("usr_o", "owner", params={"agent_id": aid}, json={"enabled": False}))
        self.assertIn("dcf", [i["task_id"] for i in library._list(self.c(org="org_b"))["items"]])

    def test_saved_agent_crud_and_validation(self):
        a = self.create(name="My DCF", description="Our house DCF", prompt="DCF for {ticker}", tags=["valuation"])
        self.assertEqual((a["kind"], a["shared"], a["created_by"]), ("prompt", False, "usr_1"))
        out = library._patch(self.c(params={"agent_id": a["id"]}, json={"name": "House DCF", "description": "Updated"}))["agent"]
        self.assertEqual((out["name"], out["description"], out["prompt"]), ("House DCF", "Updated", "DCF for {ticker}"))
        library._delete(self.c(params={"agent_id": a["id"]}))
        with self.assertRaises(ApiError) as cm:
            library._get(self.c(params={"agent_id": a["id"]}))
        self.assertEqual(cm.exception.status, 404)
        for bad, code in (({"name": "", "prompt": "DCF for Apple"}, "bad_name"), ({"name": "x"}, "bad_prompt"), ({"name": "x", "prompt": "tell a joke"}, "unplannable_prompt"),
                          ({"name": "x", "prompts": []}, "bad_chain"), ({"name": "x", "prompts": ["DCF for Apple", "joke"]}, "unplannable_prompt"),
                          ({"name": "x", "prompt": "DCF", "tags": "no"}, "bad_tags")):
            with self.assertRaises(ApiError, msg=str(bad)) as cm:
                library._create(self.c(json=bad))
            self.assertEqual((cm.exception.status, cm.exception.code), (400, code))
            self.assertTrue(cm.exception.hint)
        with self.assertRaises(ApiError) as cm:
            library._create(self.c(role="viewer", json={"name": "x", "prompt": "DCF for Apple"}))
        self.assertEqual(cm.exception.status, 403)

    def test_shared_visibility_and_ownership(self):
        a = self.create(name="Private agent", prompt="Comps for {ticker}")
        pid = {"agent_id": a["id"]}
        self.assertNotIn(a["id"], [i["id"] for i in library._list(self.c("usr_2"))["items"]])
        with self.assertRaises(ApiError) as cm:
            library._run(self.c("usr_2", params=pid, json={}))
        self.assertEqual(cm.exception.status, 404)
        library._patch(self.c(params=pid, json={"shared": True}))
        self.assertIn(a["id"], [i["id"] for i in library._list(self.c("usr_2"))["items"]])
        self.assertNotIn(a["id"], [i["id"] for i in library._list(self.c(org="org_b"))["items"]])
        with self.assertRaises(ApiError) as cm:
            library._patch(self.c("usr_2", params=pid, json={"name": "hijack"}))
        self.assertEqual((cm.exception.status, cm.exception.code), (403, "not_yours"))
        with self.assertRaises(ApiError) as cm:
            library._delete(self.c("usr_2", params=pid))
        self.assertEqual(cm.exception.status, 403)
        library._patch(self.c("usr_o", "owner", params=pid, json={"description": "reviewed"}))
        with self.assertRaises(ApiError) as cm:
            library._get(self.c(org="org_b", params=pid))
        self.assertEqual(cm.exception.status, 404)
        status, out = library._run(self.c("usr_2", params=pid, json={"inputs": {"ticker": "AAPL", "source_review": False}}))
        self.assertEqual(status, 201)
        r = wait_status(self.svc, out["job"]["id"])
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["user_id"], "usr_2")
        self.assertEqual(r["agent_id"], a["id"])

    def test_builtin_run_and_prompt_chain_run(self):
        status, out = library._run(self.c(params={"agent_id": C.builtin_id("comps")}, json={"inputs": {"ticker": "AAPL", "source_review": False}}))
        r = wait_status(self.svc, out["job"]["id"])
        self.assertEqual(r["status"], "done")
        names = [e["data"]["name"] for e in self.svc.events_after(r["id"], 0) if e["type"] == "deliverable"]
        self.assertEqual(names, ["AAPL_trading_comps.xlsx"])
        chain = self.create(name="Valuation pack", prompts=["Comps for {ticker}", "DCF for {ticker}"], shared=True)
        self.assertEqual(chain["kind"], "chain")
        status, out = library._run(self.c("usr_2", params={"agent_id": chain["id"]}, json={"inputs": {"ticker": "AAPL", "source_review": False}}))
        r = wait_status(self.svc, out["job"]["id"])
        self.assertEqual(r["status"], "done")
        plan = json.loads(r["plan_json"])
        self.assertEqual([t["task_id"] for t in plan["tasks"]], ["comps", "dcf"])
        self.assertEqual(plan["method"], "chain")
        hist = jobs._list(self.c("usr_2", query={}))["items"]
        self.assertEqual(len(hist), 2)                                      # run history lists both runs (P-J8)


class DocumentAndEditAgentTests(LibraryBase):
    def add_docs(self, deal_id):
        conn = self.st._conn
        docs = [("doc_a", "Management Presentation.pdf", ["Revenue was $120.0 million in 2024.\nThis Agreement shall be governed by the laws of England and Wales."]),
                ("doc_b", "Customer Contract.pdf", ["Either party may terminate on 90 days written notice.\nThe customer has a change of control termination right.",
                                                    "Revenue was $98.0 million in 2024."])]
        for did, name, pages in docs:
            conn.execute("INSERT INTO documents(id, org_id, deal_id, name, folder, kind, status, sha256) VALUES(?,?,?,?,?,?,?,?)", (did, "org_a", deal_id, name, "", "pdf", "ready", None))
            for i, t in enumerate(pages, 1):
                conn.execute("INSERT INTO document_pages(org_id, doc_id, page, text) VALUES(?,?,?,?)", ("org_a", did, i, t))

    def deal(self):
        return self.st.deal_store(self.st._conn, "org_a").create_deal("Project Atlas").deal_id

    def test_vdr_review_over_deal_documents(self):
        d = self.deal()
        self.add_docs(d)
        j = self.svc.submit("org_a", "usr_1", "First pass review of the data room", deal_id=d, inputs={"source_review": False})
        r = wait_status(self.svc, j["id"])
        self.assertEqual(r["status"], "done", r["error"])
        dl = [e["data"] for e in self.svc.events_after(j["id"], 0) if e["type"] == "deliverable"][0]
        body = json.loads(self.st.deal_store(self.st._conn, "org_a").get_version(d, dl["name"], dl["version"]))
        self.assertIn("findings", body)
        self.assertEqual(body["summary"]["documents"], 2)

    def test_vdr_review_without_documents_has_hint(self):
        d = self.deal()
        j = self.svc.submit("org_a", "usr_1", "Review the data room", deal_id=d, inputs={"source_review": False})
        r = wait_status(self.svc, j["id"])
        self.assertEqual(r["status"], "failed")
        self.assertIn("Upload", r["hint"])

    def test_diligence_grid_quotes_with_citations(self):
        d = self.deal()
        self.add_docs(d)
        j = self.svc.submit("org_a", "usr_1", "Diligence grid", deal_id=d,
                            inputs={"source_review": False, "questions": ["What is the governing law?", "Is there a change of control provision?"]})
        r = wait_status(self.svc, j["id"])
        self.assertEqual(r["status"], "done", r["error"])
        dl = [e["data"] for e in self.svc.events_after(j["id"], 0) if e["type"] == "deliverable"][0]
        grid = json.loads(self.st.deal_store(self.st._conn, "org_a").get_version(d, dl["name"], dl["version"]))
        cells = {(row["doc_id"], c["question"]): c for row in grid["rows"] for c in row["cells"]}
        gov = cells[("doc_a", "What is the governing law?")]
        self.assertEqual(gov["status"], "ok")
        self.assertIn("England", gov["answer"])
        self.assertEqual(gov["page"], 1)
        self.assertEqual(cells[("doc_b", "What is the governing law?")]["status"], "not_found")
        srcs = [e["data"] for e in self.svc.events_after(j["id"], 0) if e["type"] == "source"]
        self.assertTrue(any(s["doc_name"] == "Management Presentation.pdf" and s["page"] == 1 for s in srcs))

    def test_tick_and_tie_and_deck_edit(self):
        j1 = self.svc.submit("org_a", "usr_1", "Company profile for Apple", inputs={"source_review": False})
        wait_status(self.svc, j1["id"], ("awaiting_approval",))
        self.svc.approve("org_a", j1["id"], "profile.approve_outline", {}, "usr_1")
        r1 = wait_status(self.svc, j1["id"])
        deal = r1["deal_id"]
        j2 = self.svc.submit("org_a", "usr_1", "DCF for Apple", deal_id=deal, inputs={"source_review": False})
        wait_status(self.svc, j2["id"])
        j3 = self.svc.submit("org_a", "usr_1", "Tick and tie the deck", deal_id=deal, inputs={"source_review": False})
        r3 = wait_status(self.svc, j3["id"])
        self.assertEqual(r3["status"], "done", r3["error"])
        dl = [e["data"] for e in self.svc.events_after(j3["id"], 0) if e["type"] == "deliverable"][0]
        rep = json.loads(self.st.deal_store(self.st._conn, "org_a").get_version(deal, dl["name"], dl["version"]))
        self.assertGreater(rep["facts_read"], 20)
        self.assertIn("conflicts", rep)
        j4 = self.svc.submit("org_a", "usr_1", "Retitle slide 2 to \"Revenue grew 6% to $479bn on services\"", deal_id=deal, inputs={"source_review": False})
        r4 = wait_status(self.svc, j4["id"])
        self.assertEqual(r4["status"], "done", r4["error"])
        d4 = [e["data"] for e in self.svc.events_after(j4["id"], 0) if e["type"] == "deliverable"][0]
        self.assertEqual((d4["name"], d4["version"]), ("AAPL_company_profile.pptx", 2))
        j5 = self.svc.submit("org_a", "usr_1", "Retitle slide 9 to something", deal_id=deal, inputs={"source_review": False})
        r5 = wait_status(self.svc, j5["id"])
        self.assertEqual(r5["status"], "failed")
        self.assertIn("slide", r5["hint"].lower() + r5["error"].lower())

    def test_tick_and_tie_without_deliverables_has_hint(self):
        d = self.deal()
        j = self.svc.submit("org_a", "usr_1", "Tick and tie", deal_id=d, inputs={"source_review": False})
        r = wait_status(self.svc, j["id"])
        self.assertEqual(r["status"], "failed")
        self.assertTrue(r["hint"])

    def test_earnings_update_prefers_the_deals_own_model(self):
        j1 = self.svc.submit("org_a", "usr_1", "Three-statement model for Apple", inputs={"source_review": False})
        r1 = wait_status(self.svc, j1["id"])
        j2 = self.svc.submit("org_a", "usr_1", "Roll forward the Apple model", deal_id=r1["deal_id"], inputs={"source_review": False})
        r2 = wait_status(self.svc, j2["id"])
        # the library model already ends in the latest fiscal year, so there is nothing to roll: the step must say so with a hint
        self.assertEqual(r2["status"], "failed")
        self.assertIn("roll", (r2["error"] + r2["hint"]).lower())


if __name__ == "__main__":
    unittest.main()
