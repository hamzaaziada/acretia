"""S4.6b SpreadsheetBench eval: tiny synthetic workbooks only (no dataset needed), fake adapter, no network."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from om import formula as fx, sbench, xlsx
from src.harness.adapter import AdapterResult


def make_book(rows, *, cached=None) -> bytes:
    """rows: {"A1": value-or-=formula}; cached overrides saved values after calculation ({"B2": 999})."""
    wb = xlsx.Workbook()
    sh = wb.sheet("Sheet1")
    for a1, v in rows.items():
        sh.set(a1, v)
    fx.calculate_workbook(wb)
    for a1, v in (cached or {}).items():
        sh.cells[xlsx.split_ref(a1)].cached = v
    return wb.to_bytes()


def task(tid="t1", pos="B1:B3", sheet="Sheet1", **kw):
    return {"id": tid, "instruction": "Fill B with doubles of A.", "instruction_type": "Cell-Level Manipulation",
            "spreadsheet_path": f"spreadsheet/{tid}", "answer_position": pos, "answer_sheet": sheet, **kw}


def write_dataset(root: Path, tasks_books):
    (root / "spreadsheet").mkdir(parents=True)
    (root / "dataset.json").write_text(json.dumps([t for t, _, _ in tasks_books]))
    for t, init, gold in tasks_books:
        d = root / t["spreadsheet_path"]
        d.mkdir(parents=True)
        (d / f"1_{t['id']}_init.xlsx").write_bytes(init)
        (d / f"1_{t['id']}_golden.xlsx").write_bytes(gold)


class FakeAdapter:
    """Deterministic stand-in for src.harness.adapter.Adapter: no network, answers from a table."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def chat(self, messages, *, json_schema=None, job_id=None, **kw):
        self.calls.append((messages, json_schema, job_id))
        w = self.answers[job_id.removeprefix("sbench-")]
        return AdapterResult(text=json.dumps({"writes": w}), data={"writes": w})


class Compare(unittest.TestCase):
    def test_numbers_text_blanks(self):
        eq = sbench.cells_equal
        self.assertTrue(eq(1, 1.004))                 # rounded to 2 decimals
        self.assertFalse(eq(1, 1.01))
        self.assertTrue(eq("3.50", 3.5))              # numeric text equals number
        self.assertTrue(eq("abc", "abc"))
        self.assertFalse(eq("abc", "ABC"))
        self.assertTrue(eq(None, ""))                 # blank == empty string
        self.assertTrue(eq(None, None))
        self.assertFalse(eq(None, 0))                 # blank is not zero
        self.assertFalse(eq("x", 1))

    def test_dates(self):
        self.assertTrue(sbench.cells_equal(dt.datetime(2020, 1, 2, 9, 0), dt.datetime(2020, 1, 2, 10, 0)))
        self.assertFalse(sbench.cells_equal(dt.datetime(2020, 1, 2), dt.datetime(2020, 1, 3)))

    def test_score_workbooks(self):
        gold = make_book({"A1": 1, "B1": "=A1*2", "C1": "x"})
        same = make_book({"A1": 1, "B1": 2, "C1": "different outside scope"})
        bad = make_book({"A1": 1, "B1": 3, "C1": "x"})
        self.assertTrue(sbench.score_workbooks(gold, same, "Sheet1!B1")[0])
        ok, msg, _ = sbench.score_workbooks(gold, bad, "B1", "Sheet1")
        self.assertFalse(ok)
        self.assertIn("B1", msg)
        self.assertFalse(sbench.score_workbooks(gold, same, "Nope!B1")[0])


class Scoping(unittest.TestCase):
    def test_parse_answer_position(self):
        sheets = ["Sheet1", "Other"]
        self.assertEqual(sbench.parse_answer_position("B1:B3", "Sheet1", sheets), [("Sheet1", 1, 2, 3, 2)])
        self.assertEqual(sbench.parse_answer_position("'Other'!A1,Sheet1!C2:D3", "Sheet1", sheets),
                         [("Other", 1, 1, 1, 1), ("Sheet1", 2, 3, 3, 4)])
        # dataset quirks: stray quote, comma list of sheets, whole-column range
        self.assertEqual(sbench.parse_answer_position("Other'!A:B", "'Sheet1','Other'", sheets)[0][0], "Other")
        r = sbench.parse_answer_position("A:B", "Other", sheets)[0]
        self.assertEqual((r[0], r[1], r[3]), ("Other", 1, sbench.MAXROW))
        self.assertEqual(sbench.parse_answer_position("A1", "", sheets)[0][0], "Sheet1")

    def test_in_scope(self):
        rg = sbench.parse_answer_position("B1:B3", "Sheet1", ["Sheet1"])
        self.assertTrue(sbench.in_scope(("Sheet1", 2, 2), rg))
        self.assertFalse(sbench.in_scope(("Sheet1", 4, 2), rg))
        self.assertFalse(sbench.in_scope(("Sheet1", 2, 3), rg))
        self.assertFalse(sbench.in_scope(("Other", 2, 2), rg))


class Fidelity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ds"
        ok = make_book({"A1": 1, "A2": 2, "B1": "=A1*2", "B2": "=A2*2", "D1": "=SUM(A1:A2)"})
        wrong = make_book({"A1": 1, "A2": 2, "B1": "=A1*2", "B2": "=A2*2"}, cached={"B2": 999})
        unsup = make_book({"A1": "abcdef", "B1": '=SEARCH("c",A1)', "B2": "=ROW(A1)"}, cached={"B1": 3, "B2": 1})
        whole = make_book({"A1": 1, "B1": "=SUM(A:A)"}, cached={"B1": 1})
        noform = make_book({"A1": 1, "B1": 2})
        self.tasks = [(task("ok", "B1:B2"), ok, ok), (task("wrong", "B1:B2"), wrong, wrong),
                      (task("unsup", "B1:B2"), unsup, unsup), (task("whole", "B1"), whole, whole),
                      (task("plain", "B1"), noform, noform)]
        write_dataset(self.root, self.tasks)
        (self.root / "spreadsheet" / "bad").mkdir()
        (self.root / "dataset.json").write_text(json.dumps([t for t, _, _ in self.tasks] + [task("bad")]))
        (self.root / "spreadsheet" / "bad" / "1_bad_golden.xlsx").write_bytes(b"not a zip")
        self.res = sbench.fidelity(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts(self):
        w, c = self.res["workbooks"], self.res["cells"]
        self.assertEqual(w["tasks"], 6)
        self.assertEqual(w["parsed"], 5)
        self.assertEqual([s["id"] for s in w["skipped"]], ["bad"])          # unparseable: skipped with a reason
        self.assertTrue(w["skipped"][0]["reason"])
        self.assertEqual(w["with_formulas"], 4)                             # "plain" has no formulas
        self.assertEqual(w["fully_supported"], 3)                           # unsup uses SEARCH/ROW
        self.assertEqual(c["formula_cells_compared"], 8)
        self.assertEqual(c["reproduced"], 4)
        self.assertEqual(c["reproduced_pct"], 50.0)
        # supported workbooks: ok 3/3 + wrong 1/2 + whole 0/1
        self.assertEqual((c["supported_workbooks_cells"], c["supported_workbooks_reproduced"]), (6, 4))
        self.assertFalse(self.res["gate"]["met"])

    def test_answer_scope(self):
        c = self.res["cells"]
        # ok: D1 outside B1:B2 -> 2 scoped; wrong 2; unsup 2; whole 1
        self.assertEqual(c["answer_scope_cells"], 7)
        self.assertEqual(c["answer_scope_reproduced"], 3)

    def test_unsupported_ranking_and_causes(self):
        fns = {u["function"]: u for u in self.res["unsupported_functions"]}
        self.assertEqual(set(fns), {"SEARCH", "ROW"})
        self.assertEqual(fns["SEARCH"]["cells"], 1)
        causes = {m["cause"]: m["cells"] for m in self.res["mismatch_causes"]}
        self.assertEqual(causes["unsupported function"], 2)
        self.assertEqual(causes["whole-column ref"], 1)
        self.assertEqual(causes["other"], 1)                  # the tampered saved value
        self.assertEqual(sum(causes.values()), 4)

    def test_limit_and_notes(self):
        r = sbench.fidelity(self.root, limit=2)
        self.assertEqual(r["workbooks"]["tasks"], 2)
        self.assertIn("not run live (no keys; D-021)", sbench.report_md(self.res))

    def test_scorecard_rows(self):
        rows = sbench.scorecard_rows(self.res, date="2026-01-01")
        self.assertTrue(all(set(r) == {"task", "metric", "value", "n", "mode", "date"} for r in rows))
        self.assertTrue(all(r["task"] == "S4.6" for r in rows))
        m = {r["metric"]: r for r in rows}
        self.assertEqual(m["sbench_formula_cells_reproduced_pct"]["value"], 50.0)
        self.assertEqual(m["sbench_formula_cells_reproduced_pct"]["n"], 8)
        self.assertEqual(m["sbench_llm_solving"]["value"], "not run live")

    def test_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            rp, jp = sbench.write_outputs(self.res, d)
            self.assertIn("Headline", rp.read_text())
            self.assertEqual(json.loads(jp.read_text())["workbooks"]["parsed"], 5)

    def test_function_extraction(self):
        self.assertEqual(sbench.functions_in('=IF(A1,"SEARCH(x)",_xlfn.IFNA(B1,0))+Sheet1!A1'), ["IF", "IFNA"])
        self.assertTrue(sbench.supported("sum"))
        self.assertFalse(sbench.supported("SEARCH"))


class Solver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ds"
        init = make_book({"A1": 1, "A2": 2, "A3": 3})
        gold = make_book({"A1": 1, "A2": 2, "A3": 3, "B1": "=A1*2", "B2": "=A2*2", "B3": "=A3*2"})
        self.t1, self.t2 = task("s1"), task("s2")
        write_dataset(self.root, [(self.t1, init, gold), (self.t2, init, gold)])
        self.replay = Path(self.tmp.name) / "replay"

    def tearDown(self):
        self.tmp.cleanup()

    def test_prompt_has_instruction_and_cells(self):
        init = (self.root / "spreadsheet/s1/1_s1_init.xlsx").read_bytes()
        msgs = sbench.build_prompt(self.t1, init)
        self.assertIn("Fill B with doubles", msgs[1]["content"])
        self.assertIn("A3=3", msgs[1]["content"])

    def test_fake_adapter_records_then_replays(self):
        good = {"Sheet1!B1": "=A1*2", "Sheet1!B2": 4, "B3": 6}                 # bare "B3" lands on the answer sheet
        bad = {"Sheet1!B1": 2, "Sheet1!B2": 4, "Sheet1!B3": 7}
        ad = FakeAdapter({"s1": good, "s2": bad})
        r1 = sbench.solve(self.t1, adapter=ad, replay_dir=self.replay, root=self.root)
        r2 = sbench.solve(self.t2, adapter=ad, replay_dir=self.replay, root=self.root)
        self.assertTrue(r1["passed"], r1)
        self.assertFalse(r2["passed"])
        self.assertIn("B3", r2["reason"])
        self.assertEqual(len(ad.calls), 2)
        self.assertIsNotNone(ad.calls[0][1])                                    # JSON schema was requested
        self.assertEqual(ad.calls[0][2], "sbench-s1")
        out = sbench.replay_eval(self.root, self.replay)                        # no adapter at all
        self.assertEqual((out["tasks_replayed"], out["passed"], out["pass_pct"]), (2, 1, 50.0))
        self.assertIn("not run live (no keys; D-021)", out["llm"])

    def test_replay_miss_and_bad_answer(self):
        r = sbench.solve(self.t1, replay_dir=self.replay, root=self.root)
        self.assertFalse(r["passed"])
        self.assertIn("replay miss", r["reason"])
        ad = FakeAdapter({"s1": {"Nowhere!B1": 1}})
        r = sbench.solve(self.t1, adapter=ad, replay_dir=self.replay, root=self.root)
        self.assertFalse(r["passed"])
        self.assertIn("edit refused", r["reason"])

    def test_no_live_client_in_module(self):
        src = Path(sbench.__file__).read_text()
        for bad in ("urllib", "requests", "openai", "anthropic"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
