"""Offline tests for the Matrix parity features of om/grid.py (S5.5a, docs/parity-spec.md Grid 1-14).

Parser pdfdoc, no network, no live model. Every class runs on SQLite and (when importable) DuckDB.
"""
import csv
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from om import docparse, grid  # noqa: E402
from om.grid import BudgetExceeded, ExtractiveEngine, GridStore, USED  # noqa: E402
from om.pdfwrite import PDFWriter  # noqa: E402
from test_grid import PDF_A, PDF_B, Scripted  # noqa: E402


def pdf_table() -> bytes:
    """A title line and a 3 row x 4 column table (header + 2 body rows)."""
    w = PDFWriter()
    w.page()
    w.text(72, 700, "Quarterly results overview for the segment", 12)
    rows = [("Item", "Q1", "Q2", "Q3"), ("Revenue", "100", "200", "300"), ("Cost of sales", "40", "50", "60")]
    for i, r in enumerate(rows):
        for x, t in zip((72, 230, 340, 450), r):
            w.text(x, 640 - 14 * i, t, 10)
    return w.to_bytes()


def pdf_c() -> bytes:
    w = PDFWriter()
    w.page()
    w.text(72, 700, "As of June 30, 2024, the Company had approximately 900 full-time equivalent employees.", 10)
    return w.to_bytes()


class Inst(ExtractiveEngine):
    """Extractive engine that records every estimate / answer call (and can be slow). ``id`` is per instance."""

    def __init__(self, id="inst", delay=0.0):
        self.id, self.delay = id, delay
        self.lock = threading.Lock()
        self.estimates = 0
        self.answers = []          # (qid, doc_id) at the moment the call STARTED
        self.finished = 0

    def estimate(self, doc, question):
        with self.lock:
            self.estimates += 1
        return super().estimate(doc, question)

    def answer(self, doc, question):
        with self.lock:
            self.answers.append((question["id"], doc.doc_id))
        if self.delay:
            time.sleep(self.delay)
        try:
            return super().answer(doc, question)
        finally:
            with self.lock:
                self.finished += 1

    def reset(self):
        self.answers = []


REV = {"id": "revenue", "text": "What were total net sales?", "type": "currency"}
STAFF = {"id": "staff", "text": "How many full-time equivalent employees did the company have?", "type": "number"}
AUD = {"id": "auditor", "text": "Who is the auditor and what opinion was issued?"}
QUANT = {"id": "quantum", "text": "Describe the quantum flux capacitor."}
BASE = [REV, STAFF, AUD]


class Base:
    backend = "sqlite"

    def setUp(self):
        self.s = GridStore(":memory:", backend=self.backend, parser_backend="pdfdoc")
        self.a = self.s.add_document(PDF_A, "a.pdf")
        self.b = self.s.add_document(PDF_B, "b.pdf")
        self.eng = Inst()

    def tearDown(self):
        self.s.close()

    def grid(self, qs=None, docs=None, name="g"):
        return self.s.create_grid(name, docs or [self.a, self.b], qs or BASE)

    def touched(self, res):
        return sorted(tuple(t) for t in res["touched"])

    def qtouched(self, res):
        return sorted({q for _d, q in res["touched"]})

    def assert_invariants(self, gid):
        """Every answered cell has an exact quote located on its cited page, with bbox and hash from the Locator."""
        for c in self.s.cells(gid):
            if c["status"] in USED:
                doc = self.s.document(c["doc_id"])
                loc = docparse.locate(doc, c["page"], c["exact_quote"])
                self.assertIsNotNone(loc, c)
                self.assertEqual(tuple(c["bbox_norm"]), tuple(min(1.0, max(0.0, v)) for v in loc.bbox_norm))
                self.assertEqual(c["sha256_span_hash"], loc.sha256_span_hash)
            elif c["status"] == "unverified":
                self.assertEqual(c["answer"], "")


# ============================================================================================= item 1
class StreamCases(Base):
    def test_estimate_first_then_cells_then_done(self):
        gid = self.grid()
        seen_calls_at_estimate = []
        evs = []
        for ev in self.s.run_stream(gid, self.eng, workers=4):
            if ev["type"] == "estimate":
                seen_calls_at_estimate.append((len(self.eng.answers), self.eng.estimates))
            if ev["type"] == "cell":                      # written to the DB before it is yielded
                c = ev["cell"]
                got = {(x["doc_id"], x["question_id"]) for x in self.s.cells(gid)}
                self.assertIn((c["doc_id"], c["question_id"]), got)
                self.assertNotIn("raw_answer", c)
            evs.append(ev)
        self.assertEqual(evs[0]["type"], "estimate")
        self.assertEqual(seen_calls_at_estimate, [(0, seen_calls_at_estimate[0][1])])    # no engine answer before it
        self.assertEqual(evs[0]["pending_cells"], 6)
        self.assertEqual([e["type"] for e in evs].count("cell"), 6)
        done = evs[-1]
        self.assertEqual(done["type"], "done")
        for k in ("run_id", "touched", "stats", "elapsed_s", "first_cell_s", "actual_cost_usd", "tokens_in", "tokens_out"):
            self.assertIn(k, done)
        self.assertLessEqual(done["first_cell_s"], done["elapsed_s"])
        self.assertEqual(len(done["touched"]), 6)

    def test_first_cell_before_last_is_computed(self):
        gid = self.grid()
        slow = Inst("slow", delay=0.12)
        first_finished = None
        n_cells = 0
        for ev in self.s.run_stream(gid, slow, workers=2):
            if ev["type"] == "cell":
                n_cells += 1
                if first_finished is None:
                    first_finished = slow.finished
        self.assertEqual(n_cells, 6)
        self.assertLess(first_finished, 6)                 # a cell was delivered while others were still computing
        runs = self.s.runs(gid)
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual(r["cells"], 6)
        self.assertGreater(r["elapsed_s"], r["first_cell_s"])
        self.assertIsNotNone(r["tokens_in"])

    def test_run_wrapper_shape_and_incremental(self):
        gid = self.grid()
        r1 = self.s.run(gid, self.eng)
        for k in ("run_id", "engine", "touched", "skipped", "stats", "estimate", "actual_cost_usd"):
            self.assertIn(k, r1)
        self.assertEqual(len(r1["touched"]), 6)
        r2 = self.s.run(gid, self.eng)
        self.assertEqual((r2["touched"], r2["skipped"]), ([], 6))
        evs = list(self.s.run_stream(gid, self.eng))
        self.assertEqual([e["type"] for e in evs], ["estimate", "skipped", "done"])
        self.assertEqual(evs[1]["count"], 6)

    def test_bulk_subsets(self):
        gid = self.grid()
        r = self.s.run(gid, self.eng, questions=["revenue"], docs=[self.b])
        self.assertEqual(self.touched(r), [(self.b, "revenue")])
        self.assertEqual(len(self.s.cells(gid)), 1)
        r = self.s.run(gid, self.eng, questions=["revenue", "staff"])
        self.assertEqual(self.touched(r), sorted([(self.a, "revenue"), (self.a, "staff"), (self.b, "staff")]))
        with self.assertRaises(KeyError):
            self.s.run(gid, self.eng, questions=["nope"])

    def test_budget_refuses_after_estimate_before_engine(self):
        gid = self.grid()

        class Pricey(Inst):
            def estimate(self, doc, question):
                return {"input_tokens": 400000, "output_tokens": 400000}
        pe = Pricey("pricey")
        pe.model = "gpt-4.1-mini"
        gen = self.s.run_stream(gid, pe, max_cost_usd=0.0001)
        self.assertEqual(next(gen)["type"], "estimate")
        with self.assertRaises(BudgetExceeded):
            next(gen)
        self.assertEqual(pe.answers, [])
        self.assertEqual(self.s.cells(gid), [])

    def test_db_writes_on_calling_thread_only(self):
        main = threading.get_ident()
        seen = set()
        real = self.s._save_cell
        self.s._save_cell = lambda *a, **k: (seen.add(threading.get_ident()), real(*a, **k))[1]
        self.s.run(self.grid(), self.eng, workers=4)
        self.assertEqual(seen, {main})


# ============================================================================================= item 2
class ConditionCases(Base):
    COND = {"id": "opinion", "text": "What opinion did the auditor issue?",
            "condition": {"column": "revenue", "op": "gt", "value": 300000}}

    def test_skip_is_visible_and_counts_as_filled(self):
        gid = self.grid(BASE[:1] + [self.COND])
        res = self.s.run(gid, self.eng)
        by = {(c["doc_id"], c["question_id"]): c for c in self.s.cells(gid)}
        skipped = by[(self.b, "opinion")]                    # 210,000 is not > 300,000
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["answer"], "")
        self.assertEqual(skipped["flags"], ["condition_not_met:revenue gt 300000"])
        self.assertEqual(by[(self.a, "opinion")]["status"], "extracted")
        self.assertEqual(res["stats"]["skipped"], 1)
        self.assertEqual(self.s.view(gid)["pending_cells"], 0)
        # the skipped cell is in the view, never silent
        row = next(r for r in self.s.view(gid)["rows"] if r["doc_id"] == self.b)
        self.assertEqual(row["cells"]["opinion"]["status"], "skipped")
        self.assertEqual(self.s.run(gid, self.eng)["touched"], [])

    def test_condition_and_upstream_change_invalidate(self):
        gid = self.grid(BASE[:1] + [self.COND])
        self.s.run(gid, self.eng)
        self.s.update_question(gid, "opinion", condition={"column": "revenue", "op": "gt", "value": 100000})
        r = self.s.run(gid, self.eng)
        self.assertEqual(self.touched(r), [(self.a, "opinion"), (self.b, "opinion")])   # new condition: both rehashed
        by = {(c["doc_id"], c["question_id"]): c for c in self.s.cells(gid)}
        self.assertEqual(by[(self.b, "opinion")]["status"], "extracted")                  # now met
        # upstream content change (a different answer) flips A's condition result
        self.s.update_question(gid, "revenue", text="How many full-time equivalent employees did the company have?")
        r = self.s.run(gid, self.eng)                                            # A 164,000 / B 12,500
        self.assertEqual(self.qtouched(r), ["opinion", "revenue"])
        by = {(c["doc_id"], c["question_id"]): c for c in self.s.cells(gid)}
        self.assertEqual(by[(self.a, "opinion")]["status"], "extracted")
        self.assertEqual(by[(self.b, "opinion")]["status"], "skipped")          # 12,500 is not > 100,000

    def test_all_ops(self):
        cells = {
            "n": {"status": "extracted", "answer": "Total 5,000", "value": 5000.0},
            "t": {"status": "extracted", "answer": "The auditor is KPMG", "value": None},
            "b": {"status": "extracted", "answer": "Yes, it is", "value": None},
            "nf": {"status": "not_found", "answer": "Not found in document", "value": None},
        }
        E = grid._eval_cell_op
        self.assertTrue(E("eq", cells["n"], 5000) and E("eq", cells["n"], "5,000") and E("ne", cells["n"], 4))
        self.assertTrue(E("gte", cells["n"], 5000) and E("lte", cells["n"], 5000) and not E("lt", cells["n"], 5000))
        self.assertTrue(E("lt", cells["n"], 5001) and E("gt", cells["n"], 4999))
        self.assertTrue(E("contains", cells["t"], "kpmg") and E("not_contains", cells["t"], "ernst"))
        self.assertTrue(E("is_true", cells["b"], None) and not E("is_false", cells["b"], None))
        self.assertTrue(E("exists", cells["n"], None) and not E("exists", cells["nf"], None) and not E("exists", None, None))
        self.assertTrue(E("not_found", cells["nf"], None) and not E("not_found", cells["n"], None))
        self.assertFalse(E("gt", cells["t"], 1))                 # non-numeric: not met, never an exception
        self.assertFalse(E("eq", cells["nf"], "Not found in document"))   # a not-found cell has no answer to compare

    def test_bad_condition_rejected(self):
        for cond in ({"column": "revenue", "op": "approx", "value": 1}, {"column": "revenue", "op": "gt"},
                     {"column": "ghost", "op": "exists"}, {"op": "exists"}):
            with self.assertRaises(ValueError, msg=cond):
                self.grid(BASE[:1] + [{"id": "x", "text": "What is the auditor opinion?", "condition": cond}], name=str(cond))


# ============================================================================================= item 3
class VariableCases(Base):
    QS = [{"id": "sales", "text": "What were total net sales in {{var:year}}?", "type": "currency"}, STAFF]

    def test_variable_edit_reruns_only_dependents(self):
        gid = self.grid(self.QS)
        with self.assertRaises(ValueError):
            self.s.run(gid, self.eng)                         # undefined variable: refused before any call
        self.assertEqual(self.eng.answers, [])
        self.s.set_variable(gid, "year", 2024)
        self.assertEqual(self.s.variables(gid), {"year": "2024"})
        self.s.run(gid, self.eng)
        self.assertEqual(self.s.run(gid, self.eng)["touched"], [])
        self.s.set_variable(gid, "year", 2023)
        r = self.s.run(gid, self.eng)
        self.assertEqual(self.touched(r), sorted([(self.a, "sales"), (self.b, "sales")]))
        self.s.set_variable(gid, "year", 2023)                # same value: nothing to do
        self.assertEqual(self.s.run(gid, self.eng)["touched"], [])

    def test_resolved_text_reaches_engine_and_graph_has_variable_node(self):
        gid = self.grid(self.QS)
        self.s.set_variable(gid, "year", "FY2031")
        seen = []

        class Spy(Inst):
            def answer(self, doc, question):
                seen.append(question["text"])
                return super().answer(doc, question)
        self.s.run(gid, Spy("spy"), questions=["sales"])
        self.assertTrue(seen and all("FY2031" in t and "{{" not in t for t in seen))
        g = self.s.workflow_graph(gid)
        self.assertIn({"id": "var:year", "label": "year", "type": "variable"}, g["nodes"])
        self.assertIn({"from": "var:year", "to": "sales", "kind": "variable"}, g["edges"])

    def test_bad_variable_name(self):
        with self.assertRaises(ValueError):
            self.s.set_variable(self.grid(), "bad name", 1)


# ============================================================================================= item 4
class FollowUpCases(Base):
    FU = {"id": "memo", "text": "Summarise the auditor opinion given {{col:revenue}}"}

    def qs(self):
        return [REV, STAFF, self.FU]

    def test_waves_and_cascade_only_downstream(self):
        gid = self.grid(self.qs())
        order = []

        class Rec(Inst):
            def answer(self, doc, question):
                order.append(question["id"])
                return super().answer(doc, question)
        r = self.s.run(gid, Rec("rec"), workers=4)
        self.assertEqual(len(r["touched"]), 6)
        self.assertLess(max(i for i, q in enumerate(order) if q == "revenue"), min(i for i, q in enumerate(order) if q == "memo"))
        self.assertEqual(self.s.run(gid, Rec("rec"))["touched"], [])
        # upstream prompt edit with a different answer: revenue + memo rerun, staff untouched
        self.s.update_question(gid, "revenue", text="What was cost of sales?")
        r = self.s.run(gid, Rec("rec"))
        self.assertEqual(self.qtouched(r), ["memo", "revenue"])
        self.assert_invariants(gid)

    def test_upstream_rerun_with_same_content_does_not_cascade(self):
        gid = self.grid(self.qs())
        e = Inst()
        self.s.run(gid, e)
        self.s.update_question(gid, "revenue", instructions="Answer from the income statement.")   # hash changes, answer same
        e.reset()
        r = self.s.run(gid, e)
        self.assertEqual(self.qtouched(r), ["revenue"])
        self.assertEqual({q for q, _d in e.answers}, {"revenue"})

    def test_context_contains_upstream_answer_and_quote(self):
        gid = self.grid(self.qs(), docs=[self.a])
        seen = []

        class Spy(Inst):
            def answer(self, doc, question):
                seen.append(question["text"])
                return super().answer(doc, question)
        self.s.run(gid, Spy("spy"))
        memo = next(t for t in seen if t.startswith("Summarise"))
        self.assertIn("Total net sales 391,035", memo)
        self.assertNotIn("{{", memo)

    def test_graph_edges_and_order(self):
        gid = self.grid([self.FU, REV, {"id": "tail", "text": "What is the auditor?", "condition":
                                       {"column": "memo", "op": "exists"}}])
        g = self.s.workflow_graph(gid)
        self.assertEqual([n["id"] for n in g["nodes"] if n["type"] == "column"], ["memo", "revenue", "tail"])
        self.assertIn({"from": "revenue", "to": "memo", "kind": "column"}, g["edges"])
        self.assertIn({"from": "memo", "to": "tail", "kind": "condition"}, g["edges"])
        o = g["order"]
        self.assertLess(o.index("revenue"), o.index("memo"))
        self.assertLess(o.index("memo"), o.index("tail"))

    def test_cycles_and_unknown_refs_rejected(self):
        with self.assertRaises(ValueError):
            self.grid([{"id": "a", "text": "x {{col:b}} one"}, {"id": "b", "text": "y {{col:a}} two"}])
        with self.assertRaises(ValueError):
            self.grid([{"id": "a", "text": "what about {{col:a}} itself"}], name="self")
        with self.assertRaises(ValueError):
            self.grid([{"id": "a", "text": "what about {{col:zzz}} there"}], name="unknown")
        gid = self.grid(self.qs(), name="ok")
        with self.assertRaises(ValueError):                              # update_question closing a loop
            self.s.update_question(gid, "revenue", text="What were sales given {{col:memo}}?")
        self.assertEqual(self.s.questions(gid)[0]["text"], REV["text"])    # nothing changed
        self.s.add_questions(gid, [{"id": "z", "text": "z {{col:memo}} here"}])
        with self.assertRaises(ValueError):                              # a condition closing a loop memo -> z -> memo
            self.s.update_question(gid, "memo", condition={"column": "z", "op": "exists"})


# ============================================================================================= item 5
class ColumnManagerCases(Base):
    def test_rename_is_label_only(self):
        gid = self.grid()
        self.s.run(gid, self.eng)
        self.s.rename_question(gid, "revenue", "Net sales (FY)")
        q = self.s.questions(gid)[0]
        self.assertEqual((q["id"], q["label"], q["text"]), ("revenue", "Net sales (FY)", REV["text"]))
        self.assertEqual(self.s.run(gid, self.eng)["touched"], [])
        self.assertEqual(self.s.workflow_graph(gid)["nodes"][0]["label"], "Net sales (FY)")

    def test_reorder(self):
        gid = self.grid()
        self.s.run(gid, self.eng)
        self.s.reorder_questions(gid, ["auditor", "revenue", "staff"])
        self.assertEqual([q["id"] for q in self.s.questions(gid)], ["auditor", "revenue", "staff"])
        self.assertEqual([q["id"] for q in self.s.view(gid)["questions"]], ["auditor", "revenue", "staff"])
        self.assertEqual(self.s.run(gid, self.eng)["touched"], [])
        for bad in (["auditor", "revenue"], ["auditor", "revenue", "revenue"], ["a", "b", "c"]):
            with self.assertRaises(ValueError):
                self.s.reorder_questions(gid, bad)

    def test_delete_refuses_with_dependents_unless_cascade(self):
        gid = self.grid([REV, STAFF, {"id": "memo", "text": "Summarise {{col:revenue}} for the auditor"},
                         {"id": "deep", "text": "Explain", "condition": {"column": "memo", "op": "exists"}}])
        self.s.run(gid, self.eng)
        with self.assertRaises(ValueError):
            self.s.delete_question(gid, "revenue")
        self.assertEqual(self.s.dependents(gid, "revenue"), ["memo", "deep"])
        self.assertEqual(self.s.delete_question(gid, "staff"), ["staff"])
        gone = self.s.delete_question(gid, "revenue", cascade=True)
        self.assertEqual(gone, ["revenue", "memo", "deep"])
        self.assertEqual(self.s.questions(gid), [])
        self.assertEqual(self.s.cells(gid), [])

    def test_engine_swap_reruns_only_that_column(self):
        gid = self.grid()
        fast = Inst("fast")
        self.s.register_engine("fast", fast)
        self.s.run(gid, self.eng)
        self.s.set_question_engine(gid, "staff", "fast")
        self.assertEqual(self.s.questions(gid)[1]["engine"], "fast")
        self.eng.reset()
        r = self.s.run(gid, self.eng)
        self.assertEqual(self.qtouched(r), ["staff"])
        self.assertEqual({q for q, _d in fast.answers}, {"staff"})
        self.assertEqual(self.eng.answers, [])
        self.assertEqual({c["engine"] for c in self.s.cells(gid) if c["question_id"] == "staff"}, {"fast"})
        self.s.set_question_engine(gid, "staff", "")          # back to the run engine: reruns once
        self.assertEqual(self.qtouched(self.s.run(gid, self.eng)), ["staff"])
        for bad in ("gpt-5", "llm:"):
            with self.assertRaises(ValueError):
                self.s.set_question_engine(gid, "staff", bad)
        self.s.set_question_engine(gid, "revenue", "llm:some-model")      # a valid spec is stored, not resolved yet
        self.assertEqual(self.s.questions(gid)[0]["engine"], "llm:some-model")

    def test_prompt_edit_reruns_that_column(self):
        gid = self.grid()
        self.s.run(gid, self.eng)
        self.s.update_question(gid, "staff", text="How many full-time equivalent employees were there?")
        self.assertEqual(self.qtouched(self.s.run(gid, self.eng)), ["staff"])


# ============================================================================================= item 6
class FormatCases(Base):
    def setUp(self):
        super().setUp()
        self.a_ = self.s.add_document(PDF_A, "a.pdf", source_path="room/2024/q1/a.pdf")
        self.s.add_document(PDF_B, "b.pdf", source_path="room/2023/q4/b.pdf")
        self.g = self.grid()
        self.s.run(self.g, self.eng)

    def rules(self):
        return [
            {"id": "big", "apply_to": "revenue", "style": {"fill": "#FFEEAA", "bold": True},
             "when": {"all": [{"column": "revenue", "op": "gt", "value": 300000},
                              {"any": [{"column": "auditor", "op": "contains", "value": "KPMG"},
                                       {"column": "staff", "op": "lt", "value": 10}]}]}},
            {"id": "old", "apply_to": "row", "style": {"font": "#888888"},
             "when": {"field": "source_folder", "op": "eq", "value": "room/2023/q4"}},
            {"id": "lowconf", "apply_to": "staff", "style": {"fill": "#FF0000"},
             "when": {"field": "confidence", "op": "lt", "value": 0.0}},
        ]

    def test_and_or_nested(self):
        self.s.set_format_rules(self.g, self.rules())
        v = self.s.formatted_view(self.g)
        by = {r["doc_id"]: r for r in v["rows"]}
        # A: revenue 391,035 > 300,000 AND (auditor has KPMG: no, Ernst) OR staff<10: no -> NOT applied.
        self.assertEqual(by[self.a]["cells"]["revenue"]["styles"], [])
        # B: revenue 210,000: not > 300,000.
        self.assertEqual(by[self.b]["cells"]["revenue"]["styles"], ["old"])      # row rule reaches every cell
        self.assertEqual(by[self.b]["styles"], ["old"])
        self.assertEqual(by[self.a]["styles"], [])
        self.assertEqual(by[self.b]["cell_styles"]["staff"], ["old"])
        self.assertEqual(v["format_rules"][0]["id"], "big")
        # flip the OR branch so A matches: staff 164000 > 10
        r = self.rules()
        r[0]["when"]["all"][1]["any"][1] = {"column": "staff", "op": "gt", "value": 10}
        self.s.set_format_rules(self.g, r)
        by = {x["doc_id"]: x for x in self.s.formatted_view(self.g)["rows"]}
        self.assertEqual(by[self.a]["cells"]["revenue"]["styles"], ["big"])
        self.assertEqual(by[self.b]["cells"]["revenue"]["styles"], ["old"])

    def test_field_conditions(self):
        r = [{"id": "ext", "apply_to": "staff", "style": {"fill": "#00FF00"}, "when": {"field": "status", "op": "eq", "value": "extracted"}}]
        self.s.set_format_rules(self.g, r)
        by = {x["doc_id"]: x for x in self.s.formatted_view(self.g)["rows"]}
        self.assertEqual(by[self.a]["cells"]["staff"]["styles"], ["ext"])
        self.assertEqual(by[self.a]["cells"]["revenue"]["styles"], [])
        self.assertEqual(self.s.format_rules(self.g), r)

    def test_validation(self):
        ok = self.rules()[0]

        def bad(**ch):
            r = json.loads(json.dumps(ok))
            r.update(ch)
            with self.assertRaises(ValueError, msg=ch):
                self.s.set_format_rules(self.g, [r])
        bad(style={"fill": "red"})
        bad(style={"fill": "#12345"})
        bad(style={"font": "#GGGGGG"})
        bad(style={"bold": "yes"})
        bad(style={"shadow": True})
        bad(style={})
        bad(apply_to="ghost")
        bad(when={"all": [{"column": "revenue", "op": "roughly", "value": 1}]})
        bad(when={"all": []})
        bad(when={"all": [{"column": "ghost", "op": "exists"}]})
        bad(when={"all": [], "any": []})
        bad(when={"field": "colour", "op": "eq", "value": 1})
        bad(id="")
        with self.assertRaises(ValueError):                               # duplicate ids
            self.s.set_format_rules(self.g, [ok, ok])
        with self.assertRaises(ValueError):                               # status on a row rule needs a column
            self.s.set_format_rules(self.g, [{"id": "r", "apply_to": "row", "style": {"bold": True},
                                              "when": {"field": "status", "op": "eq", "value": "ok"}}])
        self.assertEqual(self.s.format_rules(self.g), [])                 # nothing stored by failures


# ============================================================================================= item 7
class TransferCases(Base):
    def setUp(self):
        super().setUp()
        self.g = self.grid()
        self.s.run(self.g, self.eng)
        self.when = {"all": [{"column": "revenue", "op": "gt", "value": 300000}]}

    def test_filter_docs(self):
        self.assertEqual(self.s.filter_docs(self.g, self.when), [self.a])
        self.assertEqual(self.s.filter_docs(self.g, {"any": [self.when, {"column": "staff", "op": "lt", "value": 20000}]}),
                         [self.a, self.b])
        self.assertEqual(self.s.filter_docs(self.g, {"column": "revenue", "op": "lt", "value": 1}), [])
        with self.assertRaises(ValueError):
            self.s.filter_docs(self.g, {"field": "status", "op": "eq", "value": "ok"})      # needs a column
        with self.assertRaises(ValueError):
            self.s.filter_docs(self.g, {"column": "revenue", "op": "nope", "value": 1})

    def test_transfer_recomputes_incrementally(self):
        self.s.set_variable(self.g, "x", "y")
        g2 = self.s.transfer(self.g, self.when, "subset")
        self.assertEqual(self.s.doc_ids(g2), [self.a])
        self.assertEqual([q["id"] for q in self.s.questions(g2)], ["revenue", "staff", "auditor"])
        self.assertEqual(self.s.cells(g2), [])
        self.assertEqual(self.s.variables(g2), {"x": "y"})
        self.assertEqual(len(self.s.run(g2, self.eng)["touched"]), 3)
        self.assertEqual(len(self.s.cells(self.g)), 6)                 # source grid untouched

    def test_transfer_copy_cells_and_no_questions(self):
        g2 = self.s.transfer(self.g, self.when, "copied", copy_cells=True)
        self.assertEqual(len(self.s.cells(g2)), 3)
        self.assertEqual(self.s.run(g2, self.eng)["touched"], [])      # hashes carried: nothing to recompute
        g3 = self.s.transfer(self.g, self.when, "bare", copy_questions=False)
        self.assertEqual((self.s.doc_ids(g3), self.s.questions(g3)), ([self.a], []))
        with self.assertRaises(ValueError):
            self.s.transfer(self.g, self.when, "bare")                  # name taken


# ============================================================================================= items 8, 9
class SourceCases(Base):
    def test_source_folder_and_grouping(self):
        sa = self.s.add_document(PDF_A, "a.pdf", source_path="Data Room/Financials/2024/a.pdf")
        sb = self.s.add_document(PDF_B, "b.pdf", source_path="Data Room/Financials/2023/b.pdf")
        sc = self.s.add_document(pdf_c(), "c.pdf", source_path="Data Room/Legal/c.pdf")
        sd = self.s.add_document(pdf_table(), "loose.pdf")
        g = self.s.create_grid("src", [sa, sb, sc, sd], BASE[:1])
        rows = {r["doc_id"]: r for r in self.s.view(g)["rows"]}
        self.assertEqual(rows[sa]["source_folder"], "Data Room/Financials/2024")
        self.assertEqual(rows[sa]["source_path"], "Data Room/Financials/2024/a.pdf")
        self.assertEqual((rows[sd]["source_folder"], rows[sd]["source_path"]), ("", ""))
        self.assertEqual(self.s.group_by_source(g), {"Data Room/Financials/2024": [sa], "Data Room/Financials/2023": [sb],
                                                      "Data Room/Legal": [sc], "": [sd]})

    def test_folder_rule_in_filter(self):
        sa = self.s.add_document(PDF_A, "a.pdf", source_path="room/fin/a.pdf")
        sb = self.s.add_document(PDF_B, "b.pdf", source_path="room/legal/b.pdf")
        g = self.s.create_grid("src", [sa, sb], BASE[:1])
        self.assertEqual(self.s.filter_docs(g, {"field": "source_folder", "op": "contains", "value": "legal"}), [sb])


class IngestCases(Base):
    def test_batch_with_corrupt_and_duplicate(self):
        calls = []
        tids = set()
        real = self.s._store_parsed
        self.s._store_parsed = lambda *a, **k: (tids.add(threading.get_ident()), real(*a, **k))[1]
        items = [("room/fin/new_a.pdf", pdf_c()), ("room/fin/b.pdf", PDF_B), ("room/bad/corrupt.pdf", b"this is not a pdf"),
                 ("room/fin/a.pdf", PDF_A), ("room/dup/c_again.pdf", pdf_c()), "/no/such/file.pdf", ("room/e/empty.pdf", b"")]
        res = self.s.add_documents(items, workers=4, progress=lambda d, t, st: calls.append((d, t, st["status"])))
        by = {f["source_path"]: f for f in res["files"]}
        self.assertEqual([f["name"] for f in res["files"]][:2], ["new_a.pdf", "b.pdf"])      # input order
        self.assertEqual(by["room/fin/new_a.pdf"]["status"], "ok")
        self.assertEqual(by["room/fin/new_a.pdf"]["pages"], 1)
        self.assertGreaterEqual(by["room/fin/new_a.pdf"]["completeness_min"], 0.97)
        self.assertEqual(by["room/bad/corrupt.pdf"]["status"], "failed")
        self.assertIn("PdfError", by["room/bad/corrupt.pdf"]["error"])
        self.assertEqual(by["room/fin/b.pdf"]["status"], "duplicate")        # already in the store from setUp
        self.assertEqual(by["room/fin/a.pdf"]["status"], "duplicate")
        self.assertEqual(by["room/dup/c_again.pdf"]["status"], "duplicate")  # same bytes twice in one batch
        self.assertEqual(by["room/dup/c_again.pdf"]["doc_id"], by["room/fin/new_a.pdf"]["doc_id"])
        self.assertEqual(by["no/such/file.pdf"]["status"], "failed")
        self.assertEqual(by["room/e/empty.pdf"]["status"], "failed")
        self.assertEqual((res["ok"], res["failed"], res["duplicates"]), (1, 3, 3))
        self.assertEqual(len(res["alerts"]), 3)
        self.assertTrue(any("corrupt.pdf" in a and "failed" in a for a in res["alerts"]))
        self.assertEqual(len(calls), 7)
        self.assertEqual(sorted(c[0] for c in calls), list(range(1, 8)))
        self.assertTrue(all(c[1] == 7 for c in calls))
        self.assertEqual(tids, {threading.get_ident()})                       # DB writes on the calling thread
        grp = self.s.add_document(pdf_c())                                    # stored with its source folder
        self.assertEqual(self.s._folder(self.s._sources([grp])[grp]), "room/fin")
        log = self.s.ingest_log()
        self.assertEqual(len(log), 7)
        self.assertEqual({r["status"] for r in log}, {"ok", "failed", "duplicate"})
        self.assertEqual(len(self.s.ingest_log()), 7)
        # an ingested document is usable in a grid
        g = self.s.create_grid("g", [by["room/fin/new_a.pdf"]["doc_id"]], [STAFF])
        self.s.run(g, self.eng)
        self.assert_invariants(g)

    def test_a_failure_never_aborts_and_dedupe_is_stable(self):
        res = self.s.add_documents([("x/bad.pdf", b"%PDF-broken"), ("x/good.pdf", pdf_c())], workers=1)
        self.assertEqual((res["ok"], res["failed"]), (1, 1))
        res = self.s.add_documents([("y/good2.pdf", pdf_c())])
        self.assertEqual((res["ok"], res["duplicates"]), (0, 1))
        self.assertEqual(len(self.s.ingest_log()), 3)

    def test_path_items(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.pdf"
            p.write_bytes(pdf_c())
            res = self.s.add_documents([p])
        self.assertEqual((res["ok"], res["files"][0]["name"]), (1, "c.pdf"))


# ============================================================================================= item 10
class TableCases(Base):
    def test_rows_reconstructed_from_words(self):
        d = self.s.add_document(pdf_table(), "t.pdf")
        ts = self.s.tables(d)
        self.assertEqual(len(ts), 1)
        t = ts[0]
        self.assertEqual(t["rows"], [["Item", "Q1", "Q2", "Q3"], ["Revenue", "100", "200", "300"],
                                     ["Cost of sales", "40", "50", "60"]])
        self.assertEqual((t["page"], t["source"]), (1, "pdfdoc"))
        self.assertEqual(len(t["bbox_norm"]), 4)
        self.assertRegex(t["sha256_span_hash"], r"^[0-9a-f]{64}$")
        self.assertTrue(all(0 <= v <= 1 for v in t["bbox_norm"]))

    def test_no_tables_in_prose_documents(self):
        self.assertEqual(self.s.tables(self.s.add_document(pdf_c())), [])

    def test_backend_rows_are_used_when_present(self):
        d = self.s.add_document(pdf_table(), "t.pdf")
        doc = self.s.document(d)
        blk = next(b for b in doc.pages[0].blocks if b.kind == "table")
        blk.source, blk.text = "docling", "Item | Q1\nRevenue | 100"
        t = self.s.tables(d)[0]
        self.assertEqual((t["source"], t["rows"]), ("docling", [["Item", "Q1"], ["Revenue", "100"]]))

    def test_statement_table_in_a_filing_page(self):
        ts = self.s.tables(self.a)
        self.assertTrue(ts)
        self.assertTrue(any(any("Total net sales" in r[0] for r in t["rows"]) for t in ts))


# ============================================================================================= item 11
class ExportCases(Base):
    def test_export_rows_typed_with_citations(self):
        gid = self.grid(BASE + [QUANT, {"id": "flag", "text": "Does the auditor issue an unqualified opinion?", "type": "boolean"}])
        self.s.run(gid, self.eng)
        rows = self.s.export_rows(gid)
        ra = next(r for r in rows if r["doc_id"] == self.a)
        self.assertEqual(ra["document"], "a.pdf")
        self.assertEqual(ra["revenue"], 391035.0)
        self.assertEqual((ra["revenue__page"], ra["revenue__status"]), (1, "extracted"))
        self.assertIn("391,035", ra["revenue__quote"])
        self.assertEqual(ra["staff"], 164000.0)
        self.assertIsInstance(ra["auditor"], str)
        self.assertIsNone(ra["quantum"])                                   # not_found: no value
        self.assertEqual((ra["quantum__status"], ra["quantum__page"]), ("not_found", None))
        for k in ("source_path", "source_folder", "revenue__confidence"):
            self.assertIn(k, ra)

    def test_unverified_is_hidden_in_export(self):
        gid = self.grid([REV], docs=[self.a])
        bad = Scripted({"revenue": {"answer": "999", "exact_quote": "never written in the document", "page": 1,
                                    "confidence": "high", "not_found": False}})
        self.s.run(gid, bad)
        row = self.s.export_rows(gid)[0]
        self.assertEqual((row["revenue"], row["revenue__quote"], row["revenue__status"]), (None, None, "unverified"))

    def test_csv_still_works_with_skipped_cells(self):
        gid = self.grid(BASE[:1] + [{"id": "op", "text": "What opinion did the auditor issue?",
                                     "condition": {"column": "revenue", "op": "gt", "value": 300000}}])
        self.s.run(gid, self.eng)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "o.csv"
            self.s.export_csv(gid, p)
            with open(p, encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
        self.assertEqual(len(rows), 3)
        self.assertIn("skipped", rows[2])


# ============================================================================================= invariants
class InvariantCases(Base):
    def test_everything_together_keeps_traceability(self):
        gid = self.grid([REV, STAFF, AUD, QUANT,
                         {"id": "memo", "text": "Explain the auditor opinion given {{col:auditor}} in {{var:y}}"},
                         {"id": "gated", "text": "How many employees?", "type": "number",
                          "condition": {"column": "revenue", "op": "gt", "value": 300000}}])
        self.s.set_variable(gid, "y", "FY24")
        self.s.run(gid, self.eng, workers=6)
        self.assert_invariants(gid)
        self.s.set_variable(gid, "y", "FY25")
        r = self.s.run(gid, self.eng)
        self.assertEqual(self.qtouched(r), ["memo"])
        self.assert_invariants(gid)
        statuses = {c["status"] for c in self.s.cells(gid)}
        self.assertTrue(statuses <= {"extracted", "not_found", "skipped"})

    def test_untraceable_stays_hidden_in_follow_up_chain(self):
        gid = self.grid([REV, {"id": "memo", "text": "Explain {{col:revenue}} more"}], docs=[self.a])
        bad = Scripted({"revenue": {"answer": "1", "exact_quote": "invented words here", "page": 1, "confidence": "high",
                                    "not_found": False},
                        "memo": {"answer": "x", "exact_quote": "also invented", "page": 1, "confidence": "high", "not_found": False}})
        self.s.run(gid, bad)
        for c in self.s.view(gid)["rows"][0]["cells"].values():
            self.assertEqual((c["status"], c["answer"]), ("unverified", ""))
            self.assertNotIn("raw_answer", c)


def _both(*classes):
    for cls in classes:
        for backend in ("sqlite", "duckdb"):
            name = f"{cls.__name__}_{backend}"
            t = type(name, (cls, unittest.TestCase), {"backend": backend})
            if backend == "duckdb":
                t = unittest.skipUnless(grid.duckdb_available(), "duckdb not installed")(t)
            globals()[name] = t


_both(StreamCases, ConditionCases, VariableCases, FollowUpCases, ColumnManagerCases, FormatCases, TransferCases,
      SourceCases, IngestCases, TableCases, ExportCases, InvariantCases)
del Base, StreamCases, ConditionCases, VariableCases, FollowUpCases, ColumnManagerCases, FormatCases, TransferCases, \
    SourceCases, IngestCases, TableCases, ExportCases, InvariantCases

if __name__ == "__main__":
    unittest.main()
