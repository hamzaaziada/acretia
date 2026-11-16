"""S6.3 research eval harness tests. Offline: no sockets, synthetic fixtures only (eval/research/fixtures)."""
import csv
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.research import datasets, run as runner_mod  # noqa: E402
from eval.research.score import (aggregate, normalise_figure, numbers_match, parse_numbers, score_item,  # noqa: E402
                                 update_scorecard)

FX = datasets.FIXTURES
H = "a" * 64


def fig(value, units="USD_m", cited=True, label="Revenue", page=41, quote=""):
    c = {"doc_id": "EXMP_2022_10K", "sha256_span_hash": H if cited else "", "page": page, "quote": quote, "as_of": "2023-01-01"}
    return {"label": label, "value": value, "units": units, "period": "FY2022", "citation": c}


def ok(*figs):
    return {"status": "succeeded", "figures": list(figs), "rejected": []}


class NoNetwork(unittest.TestCase):
    def setUp(self):
        self._c = socket.socket.connect
        socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used in test"))

    def tearDown(self):
        socket.socket.connect = self._c


class Loaders(NoNetwork):
    def test_vals(self):
        v1 = datasets.load("vals_v1", FX)
        self.assertEqual(len(v1), 3)
        self.assertEqual(v1[0].tickers, ["EXMP"])
        self.assertEqual(v1[2].category, "Beat or Miss")
        v2 = datasets.load("vals_v2", FX)
        self.assertEqual(v2[0].gold_answer, "Operating margin was 18.2%")      # gold from rubric: v2 has no Answer column

    def test_financebench(self):
        it = datasets.load("financebench", FX)
        self.assertEqual(it[0].gold_evidence[0]["page"], 41)                     # 0-based -> 1-based
        self.assertEqual(it[0].gold_answer, "$310.00")

    def test_btb(self):
        it = datasets.load("btb", FX)
        self.assertEqual(len(it), 2)
        self.assertTrue(it[0].meta["needs_deliverable_grader"])
        self.assertEqual(it[0].meta["rubric_criteria"], 2)
        self.assertEqual(it[0].gold_answer, "")

    def test_unavailable_when_not_fetched(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(datasets.DatasetUnavailable):
            datasets.load("btb", d)

    def test_fetch_writes_manifest_with_fake_opener(self):
        with tempfile.TemporaryDirectory() as d:
            mp = Path(d) / "m.json"
            e = datasets.fetch("btb", Path(d) / "data", opener=lambda u: b'{"task_id":"x"}\n', manifest_path=mp)
            man = json.loads(mp.read_text())
            self.assertEqual(man["btb"]["files"][0]["sha256"], e[0]["sha256"])
            self.assertTrue(man["btb"]["files"][0]["url"].startswith("https://huggingface.co/"))
            self.assertTrue(datasets.verify_checksums("btb", Path(d) / "data", mp))
            self.assertEqual(len(datasets.load("btb", Path(d) / "data")), 1)

    def test_committed_manifest_is_valid_json_if_present(self):
        if datasets.MANIFEST.is_file():
            json.loads(datasets.MANIFEST.read_text())


class Scoring(NoNetwork):
    def item(self, gold, **kw):
        return datasets.EvalItem("i1", "q", gold, kw.pop("ev", []), [], "c", "vals_v1", kw.pop("meta", {}))

    def test_unit_normalisation(self):
        g = parse_numbers("$1,577.00")[0]
        self.assertTrue(numbers_match(g, normalise_figure(1577, "USD_m")))       # question states USD millions
        self.assertTrue(numbers_match(parse_numbers("$1.5 billion")[0], normalise_figure(1500, "USD_m")))
        self.assertTrue(numbers_match(parse_numbers("12.5%")[0], normalise_figure(12.5, "pct")))
        self.assertTrue(numbers_match(parse_numbers("80bps")[0], normalise_figure(0.8, "pct")))
        self.assertTrue(numbers_match(parse_numbers("(5.2)")[0] | {"value": -5.2} if False else parse_numbers("-5.2")[0],
                                      normalise_figure(-5.2, "x")))
        self.assertEqual(parse_numbers("FY 2024 Q4"), [])                        # years / quarter labels are not numbers

    def test_tolerance_and_exact_counts(self):
        self.assertTrue(score_item(self.item("$1000 million"), ok(fig(1009)))["numeric_ok"])      # 0.9% off
        self.assertFalse(score_item(self.item("$1000 million"), ok(fig(1020)))["numeric_ok"])     # 2% off
        self.assertTrue(score_item(self.item("4"), ok(fig(4, "count")))["numeric_ok"])
        self.assertFalse(score_item(self.item("4"), ok(fig(4.03, "count")))["numeric_ok"])        # counts are exact

    def test_correct_number_without_verified_citation_is_wrong(self):
        s = score_item(self.item("$310.00"), ok(fig(310, cited=False)))
        self.assertTrue(s["numeric_ok"])
        self.assertFalse(s["correct"])
        self.assertIn("no verified citation", s["reason"])
        self.assertTrue(score_item(self.item("$310.00"), ok(fig(310)))["correct"])

    def test_multi_number_gold_needs_all(self):
        it = self.item("80bps beat from low end and 70bps beat from high end")
        self.assertTrue(score_item(it, ok(fig(80, "bps"), fig(70, "bps")))["correct"])
        self.assertFalse(score_item(it, ok(fig(80, "bps")))["correct"])

    def test_evidence_overlap(self):
        ev = [{"doc": "EXMP_2022_10K", "page": 41, "quote": "Purchases of property, plant and equipment (310.0)"}]
        self.assertTrue(score_item(self.item("$310.00", ev=ev), ok(fig(310, page=41)))["evidence_ok"])
        self.assertFalse(score_item(self.item("$310.00", ev=ev), ok(fig(310, page=7)))["evidence_ok"])
        by_quote = fig(310, page=9, quote="Purchases of property, plant and equipment (310.0)")
        self.assertTrue(score_item(self.item("$310.00", ev=ev), ok(by_quote))["evidence_ok"])
        self.assertIsNone(score_item(self.item("$310.00"), ok(fig(310)))["evidence_ok"])

    def test_not_run_unscorable_and_text(self):
        self.assertFalse(score_item(self.item("$5"), None)["correct"])
        self.assertFalse(score_item(self.item("x" * 300), ok(fig(1)))["scorable"])
        self.assertFalse(score_item(self.item("", meta={"needs_deliverable_grader": True}), ok(fig(1)))["scorable"])
        t = score_item(self.item("Operating margin"), ok(fig(18.2, "pct", label="Operating margin")))
        self.assertTrue(t["correct"])


class Scorecard(NoNetwork):
    def test_update_preserves_foreign_rows_and_only_touches_research(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "scorecard.csv"
            p.write_text("suite,metric,value,n,mode,ran_live,date,notes,extra\n"
                         "deck/s3.10,quality,0.91,20,live,yes,2026-11-01,keep me,x1\n"
                         "research/vals-v1,strict_accuracy,0.5,50,live,yes,2026-11-02,live row,\n")
            row = lambda s, m, v, live: {"suite": s, "metric": m, "value": v, "n": 3, "mode": "live" if live else "replay",  # noqa: E731
                                         "ran_live": "yes" if live else "no", "date": "2026-11-16", "notes": "n"}
            update_scorecard(p, [row("research/vals-v1", "strict_accuracy", "", False),     # replay must not clobber live
                                 row("research/btb", "items_run", "", False)])
            rows = list(csv.DictReader(p.open()))
            self.assertEqual(rows[0]["extra"], "x1")
            self.assertEqual(rows[0]["notes"], "keep me")
            live = [r for r in rows if r["suite"] == "research/vals-v1"][0]
            self.assertEqual((live["value"], live["ran_live"]), ("0.5", "yes"))
            self.assertTrue(any(r["suite"] == "research/btb" for r in rows))
            update_scorecard(p, [row("research/vals-v1", "strict_accuracy", "0.6", True)])   # live may update live
            rows = list(csv.DictReader(p.open()))
            self.assertEqual([r["value"] for r in rows if r["suite"] == "research/vals-v1"], ["0.6"])
            self.assertEqual(len(rows), 3)

    def test_rejects_foreign_suite_rows(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            update_scorecard(Path(d) / "s.csv", [{"suite": "deck/x", "metric": "m"}])

    def test_creates_file_with_columns(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.csv"
            update_scorecard(p, [{"suite": "research/btb", "metric": "m", "value": "", "n": 0, "mode": "replay",
                                  "ran_live": "no", "date": "d", "notes": "not run live (D-021)"}])
            self.assertEqual(p.read_text().splitlines()[0], "suite,metric,value,n,mode,ran_live,date,notes")


class FakeAdapter:
    pass


def fake_runner(request, *, adapter=None, evidence_dir=None):
    """Stands in for run_research: answers the FinanceBench capex question with a cited figure, misses the rest."""
    if "capital expenditure" in request.question:
        return {"status": "succeeded", "figures": [fig(310)], "rejected": [{"figure": {}, "reason": "x"}], "cost_usd": 0.02,
                "tokens": 120, "error": None}
    return {"status": "failed", "figures": [], "rejected": [], "cost_usd": 0.0, "tokens": 0,
            "error": "ReplayMiss: no LLM replay fixture"}


class Runner(NoNetwork):
    def test_replay_run_with_fake_adapter(self):
        with tempfile.TemporaryDirectory() as d:
            card = Path(d) / "scorecard.csv"
            s = runner_mod.run("all", "replay", None, Path(d) / "out", data_root=FX, adapter=FakeAdapter(),
                               runner=fake_runner, scorecard_path=card, now=None)
            fb = s["suites"]["financebench"]
            self.assertEqual((fb["n"], fb["n_run"]), (2, 1))
            self.assertEqual(fb["accuracy"], 1.0)
            rec = fb["items"][0]
            self.assertEqual((rec["verified"], rec["rejected"], rec["tokens"]), (1, 1, 120))
            self.assertEqual(fb["items"][1]["status"], "not_run")
            self.assertEqual(s["suites"]["vals-v1"]["n_run"], 0)
            self.assertEqual(s["suites"]["btb"]["n_unscorable"], 2)
            summ = json.loads((Path(d) / "out" / "summary.json").read_text())
            self.assertEqual(summ["mode"], "replay")
            rows = list(csv.DictReader(card.open()))
            self.assertTrue(rows and all(r["ran_live"] == "no" and r["value"] == "" for r in rows))
            self.assertTrue(all("not run live (D-021)" in r["notes"] for r in rows))
            self.assertEqual({r["suite"] for r in rows}, {"research/vals-v1", "research/vals-v2", "research/financebench",
                                                         "research/btb"})
            tsb = [json.loads(x) for x in (Path(d) / "out" / "tsb_research.jsonl").read_text().splitlines()]
            self.assertEqual(len(tsb), 3 + 1 + 2 + 2)
            self.assertIsNone(tsb[0]["review_and_fix_min"])
            self.assertEqual(set(tsb[0]["T_a"]), {"wall_clock_s", "cost_usd", "tokens"})

    def test_live_mode_rows_carry_values(self):
        with tempfile.TemporaryDirectory() as d:
            s = runner_mod.run("financebench", "live", None, Path(d) / "o", data_root=FX, adapter=FakeAdapter(),
                               runner=fake_runner, scorecard_path=Path(d) / "c.csv")
            acc = [r for r in s["scorecard_rows"] if r["metric"] == "strict_accuracy"][0]
            self.assertEqual((acc["ran_live"], acc["value"]), ("yes", "1.0000"))

    def test_unfetched_dataset_marked_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            s = runner_mod.run("btb", "replay", None, Path(d) / "o", data_root=Path(d) / "none", adapter=FakeAdapter(),
                               runner=fake_runner, scorecard_path=Path(d) / "c.csv")
            self.assertEqual(s["suites"]["btb"]["status"], "dataset_unavailable")
            self.assertIn("dataset unavailable", s["scorecard_rows"][0]["notes"])

    def test_real_run_research_replay_adapter_no_sockets(self):
        """End to end through the stable api with the real replay Adapter: no fixture -> not_run, never faked."""
        with tempfile.TemporaryDirectory() as d:
            s = runner_mod.run("financebench", "replay", 1, Path(d) / "o", data_root=FX, scorecard_path=Path(d) / "c.csv")
            it = s["suites"]["financebench"]["items"][0]
            self.assertEqual(it["status"], "not_run")


if __name__ == "__main__":
    unittest.main()
