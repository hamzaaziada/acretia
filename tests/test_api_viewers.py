"""Viewer endpoints: citation preview, document inspector data, model view / recompute / save / explain / audit / ask."""
import json
import tempfile
import unittest

from om import formula as fx
from om import model3, wbedit, xlsx
from om import statements as stm
from om.api import db as adb
from om.api import viewers as V
from om.api.http import ApiError, RequestContext
from om.deals import DealStore
from om.storage import LocalBlobStore
from tests.test_model3 import synthetic_companyfacts

TABLES = """
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, org_id TEXT, deal_id TEXT, name TEXT, folder TEXT, kind TEXT, sha256 TEXT,
  pages INT, status TEXT, lang TEXT);
CREATE TABLE IF NOT EXISTS document_pages(org_id TEXT, doc_id TEXT, page INT, text TEXT, lines_json TEXT, tables_json TEXT);
CREATE TABLE IF NOT EXISTS citations(org_id TEXT, token TEXT, doc_id TEXT, page INT, bbox_json TEXT, quote TEXT, url TEXT, as_of TEXT,
  xbrl_concept TEXT, cell_locator TEXT, doc_name TEXT, kind TEXT);
"""
QUOTE = "Net sales increased 8% during 2024 compared to 2023"
PAGE_TEXT = "Management discussion. " * 6 + QUOTE + " primarily due to higher unit sales of iPhone and Services. " + "Outlook follows. " * 5


def route(ctx, method, path):
    for r in V.ROUTES:
        p = r.match(method, path)
        if p is not None:
            ctx.params = p
            return r, r.handler(ctx)
    raise AssertionError(f"no route {method} {path}")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.conn = adb.connect(":memory:")
        cls.conn.executescript(TABLES)
        cls.blobs = LocalBlobStore(cls.tmp.name)
        cls.store = DealStore(cls.conn, cls.blobs, "org_a")
        cls.deal = cls.store.create_deal("Project Test").deal_id
        data, cls.meta = model3.build(stm.build(synthetic_companyfacts(), "TEST"))
        cls.data = data
        cls.store.save_deliverable(cls.deal, "model.xlsx", data, "xlsx", "initial")
        cls.conn.execute("INSERT INTO documents VALUES('doc_1','org_a',?, 'TestCo 10-K.pdf','Filings','pdf','x',12,'ready','en')", (cls.deal,))
        cls.conn.execute("INSERT INTO document_pages VALUES('org_a','doc_1',7,?,NULL,NULL)", (PAGE_TEXT,))
        cls.conn.execute("INSERT INTO citations VALUES('org_a','cit_1','doc_1',7,'[0.1,0.2,0.6,0.25]',?, 'https://sec.gov/x','2024-11-01',NULL,NULL,'TestCo 10-K.pdf','document')", (QUOTE,))
        cls.conn.execute("INSERT INTO citations VALUES('org_a','cit_x',NULL,NULL,NULL,'Revenues','https://sec.gov/xbrl','2024-12-31','us-gaap:Revenues','Filings!C11','SEC XBRL','xbrl')")
        cls.conn.execute("INSERT INTO citations VALUES('org_b','cit_other','doc_9',1,'[0,0,1,1]','secret','https://x',NULL,NULL,NULL,'Other.pdf','document')")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ctx(self, org="org_a", role="member", query=None, body=None):
        return RequestContext(conn=self.conn, blobs=self.blobs, org_id=org, role=role, query=query or {}, json=body)

    def call(self, method, path, **kw):
        return route(self.ctx(**kw), method, path)[1]

    @property
    def base(self):
        return f"/api/v1/models/{self.deal}/model.xlsx"


class ModelView(Base):
    def test_get_model_classes_assumptions_checks(self):
        m = self.call("GET", self.base)
        classes = {c["cls"] for c in m["cells"].values()}
        self.assertTrue({"input", "calc", "link", "label", "header"} <= classes, classes)
        self.assertTrue(m["assumptions"])
        self.assertTrue(m["checks"])
        self.assertTrue(all(c["status"] == "pass" for c in m["checks"]), [c for c in m["checks"] if c["status"] != "pass"])
        self.assertEqual(m["checks"][-1]["name"].upper(), "MASTER CHECK")
        self.assertEqual([s["name"] for s in m["sheets"]][:3], ["Cover", "Assumptions", "IS"])
        isw = next(s for s in m["sheets"] if s["name"] == "IS")
        self.assertEqual(isw["freeze"], {"rows": 6, "cols": 2})
        # banking colours: constants are inputs, pure cross-sheet references are links, formulas are calcs
        for k, c in m["cells"].items():
            if c["cls"] == "input":
                self.assertNotIn("f", c, k)
            if c["cls"] == "link":
                self.assertIn("!", c["f"], k)
        # number formats travel with the cells; sources travel as notes
        self.assertTrue(any("%" in c.get("fmt", "") for c in m["cells"].values()))
        self.assertTrue(any(c.get("note") for c in m["cells"].values()))
        self.assertTrue(m["outputs"])

    def test_citation_token_on_hardcoded_cell(self):
        m = self.call("GET", self.base)
        c = m["cells"].get("Filings!C11")
        self.assertIsNotNone(c)
        self.assertEqual(c["cls"], "input")
        self.assertEqual(c.get("citation_token"), "cit_x")
        self.assertEqual(c.get("xbrl_concept"), "us-gaap:Revenues")

    def test_recompute_matches_formula_engine(self):
        m = self.call("GET", self.base)
        a = next(x for x in m["assumptions"] if x["ref"] == "DCF!C24")
        ref, old = a["ref"], a["value"]
        new = old + 0.01
        res = self.call("POST", self.base + "/recompute", body={"changes": {ref: new}})
        self.assertIn(ref, res["changed"])
        self.assertEqual(res["changed"][ref]["v_new"], new)
        self.assertGreater(len(res["changed"]), 1, "dependents must change too")
        self.assertIn("ms", res)
        self.assertTrue(res["checks"])
        # ground truth: evaluate the edited workbook with om.formula from scratch
        edited, _ = wbedit.edit(self.data, {ref: new}, recalc=True)
        eng = fx.from_book(xlsx.read(edited))
        eng.calculate()
        for key, d in res["changed"].items():
            sh, a1 = key.rsplit("!", 1)
            r, c = xlsx.split_ref(a1)
            want = eng.values.get((sh, r, c))
            got = d["v_new"]
            if isinstance(want, (int, float)) and isinstance(got, (int, float)):
                self.assertAlmostEqual(got, want, delta=1e-6 * max(1.0, abs(want)), msg=key)
            else:
                self.assertEqual(got, want, key)
        # not persisted
        self.assertEqual(len(self.store.history(self.deal, "model.xlsx")), 1)

    def test_recompute_a_growth_input_moves_outputs(self):
        m = self.call("GET", self.base)
        g = next(x for x in m["assumptions"] if x["sheet"] == "Assumptions" and "Revenue" in (x["section"] or "") and x["unit"] == "%")
        res = self.call("POST", self.base + "/recompute", body={"changes": {g["ref"]: g["value"] + 0.05}})
        out = {o["ref"] for o in m["outputs"]}
        self.assertTrue(out & set(res["changed"]), "headline outputs should move with a growth driver")

    def test_recompute_rejects_bad_input(self):
        with self.assertRaises(ApiError) as e:
            self.call("POST", self.base + "/recompute", body={"changes": {"Nope!A1": 1}})
        self.assertEqual(e.exception.status, 422)
        self.assertTrue(e.exception.hint)
        with self.assertRaises(ApiError) as e:
            self.call("POST", self.base + "/recompute", body={"changes": {}})
        self.assertEqual(e.exception.code, "no_changes")

    def test_explain_precedents_and_dependents(self):
        m = self.call("GET", self.base)
        f = next(k for k, c in m["cells"].items() if k.startswith("DCF!") and c.get("f") and c["cls"] == "calc")
        ex = self.call("GET", self.base + "/explain", query={"ref": f})
        self.assertTrue(ex["precedents"])
        self.assertTrue(ex["formula"])
        self.assertIn("label", ex)
        a = m["assumptions"][0]["ref"]
        ex2 = self.call("GET", self.base + "/explain", query={"ref": a})
        self.assertTrue(ex2["dependents"], "an input must show what it drives")
        empty = self.call("GET", self.base + "/explain", query={"ref": "IS!Z99"})
        self.assertTrue(empty["empty"])

    def test_audit_lists_links_and_flags_injected_hardcode(self):
        a = self.call("GET", self.base + "/audit")
        self.assertGreater(a["totals"]["links"], 0)
        self.assertEqual(a["totals"]["errors"], 0)
        # inject a hard-coded number into the middle of a calculated IS row and an error value
        m = self.call("GET", self.base)
        row_cell = next(k for k, c in m["cells"].items() if k.startswith("IS!") and c["cls"] == "calc" and k.split("!")[1][0] in "GH")
        bad, _ = wbedit.edit(self.data, {row_cell: 12345.0}, recalc=False)
        self.store.save_deliverable(self.deal, "hard.xlsx", bad, "xlsx", "tampered")
        a2 = route(self.ctx(), "GET", f"/api/v1/models/{self.deal}/hard.xlsx/audit")[1]
        self.assertTrue(any(h["ref"] == row_cell for s in a2["sheets"] for h in s["hardcodes"]))

    def test_ask_reconciles_to_workbook(self):
        r = self.call("POST", self.base + "/ask", body={"question": "What is revenue in 2024?"})
        self.assertTrue(r["cells"], r)
        self.assertTrue(r["reconciled"])
        d = r["cells_detail"][0]
        m = self.call("GET", self.base)
        self.assertEqual(m["cells"][d["ref"]]["v"], d["value"])
        unk = self.call("POST", self.base + "/ask", body={"question": "zzzz qqqq"})
        self.assertEqual(unk["cells"], [])

    def test_save_creates_version_2_and_conflict(self):
        m = self.call("GET", self.base)
        a = m["assumptions"][0]
        out = self.call("POST", self.base + "/save", body={"changes": {a["ref"]: a["value"] * 1.01}, "note": "bump", "version": 1})
        self.assertEqual(out["version"], 2)
        self.assertEqual([h["version"] for h in self.store.history(self.deal, "model.xlsx")], [1, 2])
        m2 = self.call("GET", self.base)
        self.assertEqual(m2["version"], 2)
        self.assertAlmostEqual(m2["cells"][a["ref"]]["v"], a["value"] * 1.01)
        with self.assertRaises(ApiError) as e:
            self.call("POST", self.base + "/save", body={"changes": {a["ref"]: 1.0}, "version": 1})
        self.assertEqual(e.exception.status, 409)
        # older versions stay readable
        self.assertEqual(self.call("GET", self.base, query={"version": "1"})["version"], 1)

    def test_roles_and_tenancy(self):
        with self.assertRaises(ApiError) as e:
            self.call("POST", self.base + "/save", role="viewer", body={"changes": {"DCF!C24": 0.05}})
        self.assertEqual(e.exception.status, 403)
        for method, path, kw in (("GET", self.base, {}), ("GET", self.base + "/audit", {}), ("GET", self.base + "/explain", {"query": {"ref": "IS!C5"}}),
                                 ("POST", self.base + "/recompute", {"body": {"changes": {"DCF!C24": 0.05}}}),
                                 ("POST", self.base + "/ask", {"body": {"question": "revenue"}})):
            with self.assertRaises(ApiError, msg=path) as e:
                self.call(method, path, org="org_b", **kw)
            self.assertEqual(e.exception.status, 404, path)
        with self.assertRaises(ApiError) as e:
            self.call("GET", f"/api/v1/models/{self.deal}/missing.xlsx")
        self.assertEqual(e.exception.status, 404)
        self.assertTrue(e.exception.hint)


class Citations(Base):
    def test_preview_has_context_and_bbox(self):
        p = self.call("GET", "/api/v1/citations/cit_1/preview")
        self.assertEqual(p["page"], 7)
        self.assertEqual(p["bbox_norm"], [0.1, 0.2, 0.6, 0.25])
        self.assertEqual(p["doc_name"], "TestCo 10-K.pdf")
        self.assertEqual(p["deal_id"], self.deal)
        self.assertIn("Management discussion", p["context_before"])
        self.assertTrue(p["context_after"].startswith("primarily") or "primarily" in p["context_after"])
        self.assertEqual(p["quote"], QUOTE)

    def test_preview_xbrl_without_document(self):
        p = self.call("GET", "/api/v1/citations/cit_x/preview")
        self.assertIsNone(p["doc_id"])
        self.assertEqual(p["xbrl_concept"], "us-gaap:Revenues")

    def test_preview_tenant_isolation(self):
        with self.assertRaises(ApiError) as e:
            self.call("GET", "/api/v1/citations/cit_other/preview")
        self.assertEqual(e.exception.status, 404)
        self.assertEqual(self.call("GET", "/api/v1/citations/cit_other/preview", org="org_b")["quote"], "secret")

    def test_inspect_and_search(self):
        i = self.call("GET", "/api/v1/documents/doc_1/inspect", query={"cite": "cit_1"})
        self.assertEqual(i["doc"]["pages"], 12)
        self.assertEqual(i["citation"]["token"], "cit_1")
        self.assertEqual([c["token"] for c in i["citations"]], ["cit_1"])
        s = self.call("GET", "/api/v1/documents/doc_1/search", query={"q": "iphone"})
        self.assertEqual(s["hits"][0]["page"], 7)
        with self.assertRaises(ApiError) as e:
            self.call("GET", "/api/v1/documents/doc_1/inspect", org="org_b")
        self.assertEqual(e.exception.status, 404)

    def test_preview_is_fast(self):
        import time
        t0 = time.perf_counter()
        for _ in range(20):
            self.call("GET", "/api/v1/citations/cit_1/preview")
        self.assertLess((time.perf_counter() - t0) / 20, 0.05)


class RouteTable(unittest.TestCase):
    def test_routes_are_json_serialisable_shapes(self):
        self.assertTrue(all(r.pattern.startswith("/api/v1/") for r in V.ROUTES))
        json.dumps([r.pattern for r in V.ROUTES])


if __name__ == "__main__":
    unittest.main()
