"""Offline tests for om/api/grid.py (SF.2c): Matrix grid API. Synthetic PDFs, SQLite in a temp dir, zero sockets."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from om import docparse, xlsx  # noqa: E402
from om.api import db as apidb, grid  # noqa: E402
from om.api.http import SSE, ApiError, RequestContext, Response, Router  # noqa: E402
from om.deals import DealStore  # noqa: E402
from om.pdfwrite import PDFWriter  # noqa: E402
from om.storage import LocalBlobStore  # noqa: E402

DOC_TABLES = """
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, org_id TEXT NOT NULL, deal_id TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT, sha256 TEXT, size INTEGER, pages INTEGER, status TEXT, progress REAL, lang TEXT, created_at TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS document_pages(org_id TEXT NOT NULL, doc_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT,
  lines_json TEXT, tables_json TEXT, PRIMARY KEY(org_id, doc_id, page));
"""

COC = "Change of control: upon a change of control of the Borrower the Lender may accelerate all amounts outstanding."


def pdf(name: str, clause: bool, revenue: str, law: str = "New York") -> bytes:
    w = PDFWriter()
    w.page()
    w.text(72, 740, f"{name} Agreement", 12, "Helvetica-Bold")
    w.text(72, 700, f"Total revenue for the period was ${revenue} million.", 10)
    w.text(72, 684, f"This Agreement is governed by the laws of {law}.", 10)
    w.page()
    if clause:
        w.text(72, 700, COC, 10)
        w.text(72, 686, "The Lender must give written notice within thirty days.", 10)
    else:
        w.text(72, 700, "The parties shall cooperate in good faith on all operational matters.", 10)
    return w.to_bytes()


class Harness:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.conn = apidb.connect(base / "app.db")
        apidb.migrate(self.conn, ("om.api.grid", "om.api.decks"))
        self.conn.executescript(DOC_TABLES)
        self.blobs = LocalBlobStore(str(base / "blobs"))
        from om.api import decks
        self.router = Router(grid.ROUTES + decks.ROUTES)

    def deal(self, org="org_a", name="Project Nile") -> str:
        return DealStore(self.conn, self.blobs, org).create_deal(name).deal_id

    def add_docs(self, org, deal_id, specs):
        ids = []
        for i, (name, data) in enumerate(specs):
            doc_id = f"doc_{org}_{i}_{len(name)}_{abs(hash(name)) % 997}"
            parsed = docparse.parse(data)
            self.conn.execute("INSERT INTO documents(id, org_id, deal_id, name, kind, pages, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
                              (doc_id, org, deal_id, name, "pdf", len(parsed.pages), "indexed", apidb.now()))
            for p in parsed.pages:
                lines = [{"text": l.text, "bbox_norm": list(l.bbox_norm)} for l in p.lines]
                tables = [[["Item", "2024", "2023"], ["Revenue", "391", "383"]]] if (i == 0 and p.number == 1) else []
                self.conn.execute("INSERT INTO document_pages(org_id, doc_id, page, text, lines_json, tables_json) VALUES(?,?,?,?,?,?)",
                                  (org, doc_id, p.number, p.raw_text, json.dumps(lines), json.dumps(tables)))
            ids.append(doc_id)
        return ids

    def call(self, method, path, body=None, org="org_a", role="member", query=None, headers=None):
        route, params = self.router.resolve(method, "/api/v1" + path)
        ctx = RequestContext(method=method, path=path, params=params, query=query or {}, json=body, headers=headers or {},
                             conn=self.conn, blobs=self.blobs, data_dir=Path(self.tmp.name), org_id=org, role=role)
        try:
            res = route.handler(ctx)
        except ApiError as e:
            return e.status, e.body()
        if isinstance(res, tuple):
            return res
        return 200, res

    def wait(self, grid_id, timeout=10.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            st, g = self.call("GET", f"/grids/{grid_id}")
            if g["pending"] == 0:
                return g
            time.sleep(0.05)
        raise AssertionError("grid did not settle")


def specs():
    return [("Legal/loan-a.pdf", pdf("Loan A", True, "391")), ("Legal/loan-b.pdf", pdf("Loan B", False, "120")),
            ("Legal/loan-c.pdf", pdf("Loan C", True, "75", "England")), ("Finance/model.pdf", pdf("Model", False, "980")),
            ("Finance/notes.pdf", pdf("Notes", False, "44"))]


class GridApiTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.deal = self.h.deal()
        self.docs = self.h.add_docs("org_a", self.deal, specs())

    def tearDown(self):
        time.sleep(0.05)
        self.h.conn.close()
        self.h.tmp.cleanup()

    def default_grid(self):
        st, g = self.h.call("GET", f"/deals/{self.deal}/grid")
        self.assertEqual(st, 200)
        return g

    def add_col(self, gid, **kw):
        body = {"prompt": "What is the change of control clause?", **kw}
        st, r = self.h.call("POST", f"/grids/{gid}/columns", body)
        self.assertEqual(st, 201, r)
        return r["column"]

    def test_default_grid_has_all_indexed_documents(self):
        g = self.default_grid()
        self.assertEqual(len(g["rows"]), 5)
        self.assertEqual({r["folder"] for r in g["rows"]}, {"Legal", "Finance"})
        self.assertEqual(g["rows"][0]["name"], "model.pdf")
        self.assertEqual(self.default_grid()["grid"]["id"], g["grid"]["id"])          # idempotent
        st, docs = self.h.call("GET", f"/deals/{self.deal}/grid/documents")
        self.assertEqual({f["name"]: f["count"] for f in docs["folders"]}, {"Legal": 3, "Finance": 2})

    def test_add_column_streams_cited_answers_fast(self):
        gid = self.default_grid()["grid"]["id"]
        t0 = time.time()
        col = self.add_col(gid)
        first = None
        while time.time() - t0 < 10:
            _, g = self.h.call("GET", f"/grids/{gid}")
            if any(c["state"] == "done" for c in g["cells"]):
                first = time.time() - t0
                break
            time.sleep(0.02)
        self.assertIsNotNone(first)
        self.assertLess(first, 10.0)                                                     # parity item 1: first cells within 10 s
        g = self.h.wait(gid)
        by_row = {r["name"]: next(c for c in g["cells"] if c["row"] == r["id"] and c["col"] == col["id"]) for r in g["rows"]}
        for name in ("loan-a.pdf", "loan-c.pdf"):
            c = by_row[name]
            self.assertEqual(c["state"], "done")
            self.assertIn("change of control", c["value"].lower())
            cit = c["citations"][0]
            self.assertEqual(cit["page"], 2)
            self.assertEqual(len(cit["bbox_norm"]), 4)
            self.assertTrue(all(0 <= v <= 1 for v in cit["bbox_norm"]))
            self.assertTrue(cit["token"])
            self.assertIn(cit["quote"], COC + " The Lender must give written notice within thirty days.")
        for name in ("loan-b.pdf", "model.pdf", "notes.pdf"):
            self.assertEqual(by_row[name]["value"], "Not found in document")
            self.assertEqual(by_row[name]["citations"], [])                              # traceable or not shown

    def test_cells_are_verbatim_quotes_from_the_page(self):
        gid = self.default_grid()["grid"]["id"]
        self.add_col(gid, prompt="What was the total revenue?", type="number", name="Revenue")
        g = self.h.wait(gid)
        for c in g["cells"]:
            self.assertEqual(c["state"], "done")
            pg = self.h.conn.execute("SELECT text FROM document_pages WHERE doc_id=(SELECT doc_id FROM grid_rows WHERE id=?) AND page=?",
                                     (c["row"], c["citations"][0]["page"])).fetchone()[0]
            self.assertIn(" ".join(c["citations"][0]["quote"].split()), " ".join(pg.split()))
        vals = sorted(float(c["value"].replace(",", "")) for c in g["cells"])
        self.assertEqual(vals, [44.0, 75.0, 120.0, 391.0, 980.0])

    def test_run_condition_skips_rows_visibly(self):
        gid = self.default_grid()["grid"]["id"]
        a = self.add_col(gid, name="Change Of Control")
        st, r = self.h.call("POST", f"/grids/{gid}/columns", {"prompt": "What is the governing law?", "name": "Law",
                            "run_condition": {"col": a["id"], "op": "contains", "value": "lender"}})
        self.assertEqual(st, 201, r)
        law = r["column"]
        g = self.h.wait(gid)
        names = {r["id"]: r["name"] for r in g["rows"]}
        law_cells = {names[c["row"]]: c for c in g["cells"] if c["col"] == law["id"]}
        self.assertEqual(law_cells["loan-a.pdf"]["state"], "done")
        self.assertEqual(law_cells["loan-b.pdf"]["state"], "skipped")
        self.assertIn("Change Of Control contains lender was not met", law_cells["loan-b.pdf"]["reason"])
        _, wf = self.h.call("GET", f"/grids/{gid}/workflow")
        self.assertIn({"from": a["id"], "to": law["id"], "kind": "condition"}, wf["edges"])

    def test_input_edit_reruns_dependent_columns(self):
        gid = self.default_grid()["grid"]["id"]
        st, r = self.h.call("POST", f"/grids/{gid}/columns", {"prompt": "What does the document say about {{topic}}?", "name": "About"})
        self.assertEqual(st, 201)
        col = r["column"]
        self.assertEqual(col["depends_on"]["inputs"], ["topic"])
        self.h.call("PUT", f"/grids/{gid}/inputs/topic", {"value": "governing law"})
        g = self.h.wait(gid)
        self.assertTrue(any("laws of" in c["value"] for c in g["cells"]))
        before = {c["row"]: c["value"] for c in g["cells"]}
        st, r = self.h.call("PUT", f"/grids/{gid}/inputs/topic", {"value": "total revenue"})
        self.assertEqual(st, 200)
        self.assertEqual(r["rerun_columns"], [col["id"]])
        g = self.h.wait(gid)
        after = {c["row"]: c["value"] for c in g["cells"]}
        self.assertNotEqual(before, after)
        self.assertTrue(all("revenue" in v.lower() for v in after.values()))
        self.assertEqual(g["inputs"]["topic"], "total revenue")

    def test_workflow_edges_and_cycle_rejected(self):
        gid = self.default_grid()["grid"]["id"]
        a = self.add_col(gid, name="Clause")
        st, r = self.h.call("POST", f"/grids/{gid}/columns", {"prompt": "Who is the lender in: {{Clause}} given {{rate}}?", "name": "Lender"})
        b = r["column"]
        _, wf = self.h.call("GET", f"/grids/{gid}/workflow")
        self.assertIn({"from": a["id"], "to": b["id"], "kind": "reference"}, wf["edges"])
        self.assertIn({"from": "input:rate", "to": b["id"], "kind": "input"}, wf["edges"])
        lv = {n["id"]: n["level"] for n in wf["nodes"]}
        self.assertLess(lv[a["id"]], lv[b["id"]])
        st, err = self.h.call("PATCH", f"/grids/{gid}/columns/{a['id']}", {"prompt": "What is the clause given {{Lender}}?"})
        self.assertEqual(st, 400)
        self.assertEqual(err["error"]["code"], "dependency_cycle")
        self.assertTrue(err["error"]["hint"])

    def test_column_manager_rename_reorder_edit(self):
        gid = self.default_grid()["grid"]["id"]
        a = self.add_col(gid, name="Clause")
        _, r = self.h.call("POST", f"/grids/{gid}/columns", {"prompt": "Summarise {{Clause}} briefly", "name": "Summary"})
        b = r["column"]
        self.h.wait(gid)
        st, r = self.h.call("PATCH", f"/grids/{gid}/columns/{a['id']}", {"name": "CoC"})
        self.assertEqual(st, 200)
        _, g = self.h.call("GET", f"/grids/{gid}")
        self.assertIn("{{CoC}}", next(c for c in g["columns"] if c["id"] == b["id"])["prompt"])
        self.h.wait(gid)
        st, r = self.h.call("PATCH", f"/grids/{gid}/columns/{b['id']}", {"position": 0})
        _, g = self.h.call("GET", f"/grids/{gid}")
        self.assertEqual([c["name"] for c in g["columns"]], ["Summary", "CoC"])
        st, r = self.h.call("PATCH", f"/grids/{gid}/columns/{a['id']}", {"model": "claude-sonnet", "prompt": "What is the governing law?"})
        self.assertEqual(st, 200)
        self.assertGreater(r["queued"], 5)                                               # edited column + dependent
        g = self.h.wait(gid)
        self.assertTrue(any("laws of" in c["value"] for c in g["cells"] if c["col"] == a["id"]))
        st, r = self.h.call("POST", f"/grids/{gid}/run", {"col_ids": [a["id"]], "row_ids": [g["rows"][0]["id"]]})
        self.assertEqual(st, 202)
        self.h.wait(gid)
        st, r = self.h.call("DELETE", f"/grids/{gid}/columns/{a['id']}")
        self.assertEqual(r["dependents"], ["Summary"])

    def test_estimate(self):
        gid = self.default_grid()["grid"]["id"]
        st, e = self.h.call("GET", f"/grids/{gid}/estimate", query={"prompt": "What is x?"})
        self.assertEqual(e["cells"], 5)
        self.assertEqual(e["est_cost_usd"], 0.0)
        st, e2 = self.h.call("GET", f"/grids/{gid}/estimate", query={"prompt": "What is x?", "model": "claude-sonnet"})
        self.assertGreater(e2["est_cost_usd"], 0)

    def test_transfer_filtered_rows(self):
        gid = self.default_grid()["grid"]["id"]
        self.add_col(gid)
        g = self.h.wait(gid)
        keep = [r["id"] for r in g["rows"] if r["folder"] == "Legal"][:2]
        st, ng = self.h.call("POST", f"/grids/{gid}/transfer", {"row_ids": keep, "name": "Legal only"})
        self.assertEqual(st, 201)
        self.assertEqual(len(ng["rows"]), 2)
        self.assertEqual(ng["grid"]["name"], "Legal only")
        self.assertEqual(len(ng["columns"]), 1)
        ng = self.h.wait(ng["grid"]["id"])
        self.assertEqual(len([c for c in ng["cells"] if c["state"] == "done"]), 2)
        self.assertNotEqual(ng["columns"][0]["id"], g["columns"][0]["id"])
        st, err = self.h.call("POST", f"/grids/{gid}/transfer", {"row_ids": []})
        self.assertEqual(st, 400)

    def test_wizard_split_and_create(self):
        st, r = self.h.call("POST", f"/deals/{self.deal}/grids/split",
                            {"question": "What is the change of control clause? Is there a termination fee?\n- Total revenue\nWhen does it mature?"})
        names = [c["name"] for c in r["columns"]]
        self.assertEqual(len(names), 4)
        self.assertEqual(r["columns"][1]["type"], "yes-no")
        self.assertEqual(r["columns"][3]["type"], "date")
        st, g = self.h.call("POST", f"/deals/{self.deal}/grids", {"name": "Legal review", "folders": ["Legal"], "columns": r["columns"]})
        self.assertEqual(st, 201, g)
        self.assertEqual(len(g["rows"]), 3)
        self.assertEqual(len(g["columns"]), 4)
        g = self.h.wait(g["grid"]["id"])
        self.assertEqual(len(g["cells"]), 12)
        st, err = self.h.call("POST", f"/deals/{self.deal}/grids", {"columns": r["columns"], "doc_ids": ["nope"]})
        self.assertEqual(st, 400)

    def test_export_xlsx_has_values_and_citation_notes(self):
        gid = self.default_grid()["grid"]["id"]
        self.add_col(gid, name="Clause")
        self.h.wait(gid)
        res = grid.export_xlsx(self._ctx(gid, query={"logo": "1"}))
        self.assertIsInstance(res, Response)
        book = xlsx.read(res.body)
        self.assertEqual(book.order[:2], ["Matrix", "Sources"])
        self.assertEqual(book.value("Matrix", "A1"), "ACRETIA")
        self.assertEqual(book.value("Matrix", "A4"), "Document")
        self.assertEqual(book.value("Matrix", "C4"), "Clause")
        self.assertEqual(book.value("Matrix", "A7"), "loan-a.pdf")
        self.assertIn("change of control", book.value("Matrix", "C7").lower())
        note = book.comments["Matrix"][(7, 3)]
        self.assertIn("p.2", note)
        self.assertEqual(book.value("Sources", "C2"), 2)
        res = grid.export_xlsx(self._ctx(gid))
        self.assertEqual(xlsx.read(res.body).value("Matrix", "A1"), "Document")           # no logo banner

    def _ctx(self, gid, query=None, headers=None, body=None):
        return RequestContext(method="GET", params={"grid_id": gid}, query=query or {}, headers=headers or {}, json=body,
                              conn=self.h.conn, blobs=self.h.blobs, org_id="org_a", role="member")

    def test_chat_answers_with_row_citations(self):
        gid = self.default_grid()["grid"]["id"]
        t0 = time.time()
        st, r = self.h.call("POST", f"/grids/{gid}/chat", {"question": "Which agreements have a change of control clause?"})
        self.assertLess(time.time() - t0, 5)
        self.assertEqual(r["matched"], 2)
        self.assertEqual({x["name"] for x in r["rows"]}, {"loan-a.pdf", "loan-c.pdf"})
        for row in r["rows"]:
            self.assertEqual(row["citations"][0]["page"], 2)
            self.assertTrue(row["citations"][0]["token"])
            self.assertEqual(len(row["citations"][0]["bbox_norm"]), 4)
        self.assertIn("2 of 5", r["answer"])
        st, r = self.h.call("POST", f"/grids/{gid}/chat", {"question": "   "})
        self.assertEqual(st, 400)

    def test_conditional_formatting_and_or(self):
        tree_and = {"op": "and", "children": [{"op": "gt", "value": 50}, {"op": "lt", "value": 500}]}
        tree_or = {"op": "or", "children": [{"op": "lt", "value": 50}, {"op": "gt", "value": 900}]}
        look = lambda v: (lambda col: v)  # noqa: E731
        self.assertTrue(grid.eval_tree(tree_and, look("391"), "c"))
        self.assertFalse(grid.eval_tree(tree_and, look("980"), "c"))
        self.assertTrue(grid.eval_tree(tree_or, look("980"), "c"))
        self.assertTrue(grid.eval_tree(tree_or, look("44"), "c"))
        self.assertFalse(grid.eval_tree(tree_or, look("120"), "c"))
        nested = {"op": "and", "children": [tree_or, {"op": "not_empty"}]}
        self.assertTrue(grid.eval_tree(nested, look("44"), "c"))
        gid = self.default_grid()["grid"]["id"]
        rules = [{"id": "big", "tone": "positive", "when": {"op": "or", "children": [{"op": "gt", "value": 900}, {"op": "lt", "value": 50}]}},
                 {"id": "mid", "tone": "warning", "when": {"op": "and", "children": [{"op": "gt", "value": 100}, {"op": "lte", "value": 391}]}}]
        col = self.add_col(gid, prompt="What was the total revenue?", type="number", name="Revenue", format_rules=rules)
        g = self.h.wait(gid)
        names = {r["id"]: r["name"] for r in g["rows"]}
        tone = {names[c["row"]]: (c["fmt"] or {}).get("tone") for c in g["cells"] if c["col"] == col["id"]}
        self.assertEqual(tone, {"loan-a.pdf": "warning", "loan-b.pdf": "warning", "loan-c.pdf": None, "model.pdf": "positive", "notes.pdf": "positive"})
        st, err = self.h.call("PATCH", f"/grids/{gid}/columns/{col['id']}", {"format_rules": [{"tone": "purple", "when": {}}]})
        self.assertEqual(st, 400)
        st, ok = self.h.call("PATCH", f"/grids/{gid}/columns/{col['id']}", {"format_rules": [rules[0]]})
        self.assertEqual(ok["queued"], 0)                                                # formatting never re-runs the column

    def test_sse_replays_cell_events_then_idle(self):
        gid = self.default_grid()["grid"]["id"]
        col = self.add_col(gid)
        res = grid.events(self._ctx(gid))
        self.assertIsInstance(res, SSE)
        evs = list(res.iterator)
        kinds = [e for e, _d in evs]
        self.assertEqual(kinds[0], "hello")
        self.assertEqual(kinds[-1], "idle")
        done = [d for e, d in evs if e == "cell" and d["state"] == "done"]
        self.assertEqual(len(done), 5)
        self.assertTrue(all(d["col"] == col["id"] for d in done))
        last = max(d["seq"] for _e, d in evs if "seq" in d)
        res = grid.events(self._ctx(gid, headers={"Last-Event-ID": str(last)}))
        self.assertEqual([e for e, _d in res.iterator], ["hello", "idle"])

    def test_new_documents_become_rows_of_the_default_grid(self):
        gid = self.default_grid()["grid"]["id"]
        self.add_col(gid)
        self.h.wait(gid)
        self.h.add_docs("org_a", self.deal, [("Legal/loan-d.pdf", pdf("Loan D", True, "5"))])
        g = self.default_grid()
        self.assertEqual(len(g["rows"]), 6)
        g = self.h.wait(gid)
        self.assertEqual(len([c for c in g["cells"] if c["state"] == "done"]), 6)

    def test_risks_panel_has_page_and_bbox(self):
        st, r = self.h.call("GET", f"/deals/{self.deal}/risks")
        self.assertEqual(st, 200)
        kinds = {f["type"] for f in r["findings"]}
        self.assertIn("missing_document", kinds)
        coc = [f for f in r["findings"] if f["type"] == "change_of_control"]
        self.assertTrue(coc, kinds)
        f = coc[0]
        self.assertEqual(f["page"], 2)
        self.assertEqual(len(f["bbox_norm"]), 4)
        self.assertTrue(f["citation_token"])

    def test_document_tables_csv(self):
        st, r = self.h.call("GET", f"/documents/{self.docs[0]}/tables")
        self.assertEqual(r["tables"][0]["n_rows"], 2)
        res = grid.doc_table_csv(RequestContext(params={"doc_id": self.docs[0], "n": "1.csv"}, conn=self.h.conn, org_id="org_a", role="viewer"))
        self.assertIn(b"Revenue,391,383", res.body)
        self.assertEqual(self.h.call("GET", f"/documents/{self.docs[0]}/tables/9.csv")[0], 404)

    def test_viewer_cannot_write_and_tenant_isolation(self):
        gid = self.default_grid()["grid"]["id"]
        col = self.add_col(gid)
        self.h.wait(gid)
        for method, path, body in [
            ("GET", f"/deals/{self.deal}/grid", None), ("GET", f"/deals/{self.deal}/risks", None),
            ("POST", f"/deals/{self.deal}/grids", {"columns": [{"prompt": "x y z"}]}),
            ("GET", f"/grids/{gid}", None), ("PATCH", f"/grids/{gid}", {"name": "x"}),
            ("POST", f"/grids/{gid}/columns", {"prompt": "What is x?"}),
            ("PATCH", f"/grids/{gid}/columns/{col['id']}", {"name": "z"}), ("DELETE", f"/grids/{gid}/columns/{col['id']}", None),
            ("POST", f"/grids/{gid}/run", {}), ("GET", f"/grids/{gid}/estimate", None), ("PUT", f"/grids/{gid}/inputs/a", {"value": 1}),
            ("GET", f"/grids/{gid}/workflow", None), ("GET", f"/grids/{gid}/events", None),
            ("POST", f"/grids/{gid}/transfer", {"row_ids": ["x"]}), ("GET", f"/grids/{gid}/export.xlsx", None),
            ("POST", f"/grids/{gid}/chat", {"question": "what is x"}), ("GET", f"/documents/{self.docs[0]}/tables", None),
            ("GET", f"/documents/{self.docs[0]}/tables/1.csv", None)]:
            st, body_out = self.h.call(method, path, body, org="org_b")
            self.assertEqual(st, 404, (method, path, body_out))
        route, _ = self.h.router.resolve("POST", f"/api/v1/grids/{gid}/columns")
        self.assertEqual(route.role, "member")
        ctx = RequestContext(method="POST", params={"grid_id": gid}, json={"prompt": "What is x?"}, conn=self.h.conn,
                             org_id="org_a", role="viewer")
        with self.assertRaises(ApiError) as cm:
            grid.add_column(ctx)
        self.assertEqual(cm.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
