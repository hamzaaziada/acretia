"""Three-engine recalculation: LibreOffice daemon + formulon + om.formula, with per-cell divergence.
Hermetic (synthetic company); engines that are not installed are reported unavailable and their checks skip."""
import os
import signal
import time
import unittest

from om import model3, recalc
from om import statements as stm
from om.xlsx import col_letter
from tests.test_model3 import synthetic_companyfacts


def _statements():
    return stm.build(synthetic_companyfacts(), "TEST")


def _need_lo(test):
    d = recalc.daemon()
    if not d.available():
        test.skipTest(f"LibreOffice/uno unavailable: {d.reason}")


class CompareModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = _statements()

    def test_circ_off_all_engines_agree(self):
        data, meta = model3.build(self.s, circ=0)
        r = recalc.compare(data)
        self.assertTrue(r["engines"]["om"]["available"])
        self.assertTrue(r["engines"]["cached"]["available"])
        self.assertTrue(r["agree"], r["divergences"][:3])
        self.assertEqual(r["divergences"], [])
        self.assertGreater(r["compared_cells"], 500)
        self.assertEqual(r["excluded"]["cycles"], [])                    # circ=0 reads no cell in a loop
        if r["engines"]["libreoffice"]["available"]:
            self.assertEqual(r["engines"]["libreoffice"]["cells"], r["engines"]["om"]["cells"])
        if r["engines"]["formulon"]["available"]:
            self.assertEqual(r["engines"]["formulon"]["cells"], r["engines"]["om"]["cells"])
            self.assertEqual(r["engines"]["formulon"]["cannot_evaluate"], {})
        else:
            self.assertIn("formulon", r["engines"]["formulon"]["reason"])

    def test_planted_cached_value_is_reported_with_exact_cell(self):
        wb, meta = model3.build_workbook(self.s, circ=0)
        sheet = wb["IS"]
        target = next((rc, cell) for rc, cell in sorted(sheet.cells.items())
                      if isinstance(cell.value, str) and cell.value.startswith("=") and isinstance(cell.cached, float) and abs(cell.cached) > 1)
        (r, c), cell = target
        cell.cached = cell.cached + 12345.0
        data = wb.to_bytes()
        rep = recalc.compare(data, engines=["cached", "om"])
        where = f"IS!{col_letter(c)}{r}"
        self.assertFalse(rep["agree"])
        self.assertIn(where, [d["cell"] for d in rep["divergences"]])
        hit = next(d for d in rep["divergences"] if d["cell"] == where)
        self.assertAlmostEqual(hit["values"]["cached"] - hit["values"]["om"], 12345.0, places=6)
        # every other engine still agrees with om on that cell: only the stored value is wrong
        full = recalc.compare(data)
        got = next(d for d in full["divergences"] if d["cell"] == where)
        others = {k: v for k, v in got["values"].items() if k != "cached"}
        for a in others.values():
            self.assertAlmostEqual(a, hit["values"]["om"], places=6)

    def test_circularity_cells_excluded_from_libreoffice(self):
        data, meta = model3.build(self.s, circ=1)
        r = recalc.compare(data)
        self.assertTrue(r["excluded"]["cycles"], "circ=1 must have cells in a live cycle")
        self.assertTrue(r["excluded"]["cycle_dependents"])
        if r["engines"]["libreoffice"]["available"]:
            self.assertIn("D-006", r["excluded"]["reason"])
            self.assertEqual(r["excluded"]["engines"], ["libreoffice"])
        self.assertTrue(r["agree"], r["divergences"][:3])               # om, formulon and the cached values still agree everywhere

    def test_missing_engine_is_reported_not_fatal(self):
        data, _ = model3.build(self.s, circ=0)
        r = recalc.compare(data, engines=["om", "cached", "nope"])
        self.assertFalse(r["engines"]["nope"]["available"])
        self.assertIn("unknown engine", r["engines"]["nope"]["reason"])
        self.assertTrue(r["agree"])

    def test_om_values_and_formulon_values_shapes(self):
        data, _ = model3.build(self.s, circ=0)
        ov = recalc.om_values(data)
        self.assertTrue(all(isinstance(k, tuple) and len(k) == 3 for k in ov))
        fv = recalc.formulon_values(data)
        if fv is None:
            self.assertIn("formulon", recalc.formulon_reason())
        else:
            self.assertEqual(set(fv), set(ov))


class Daemon(unittest.TestCase):
    def test_reuse_is_faster_than_one_shot_and_restarts_after_kill(self):
        _need_lo(self)
        data, _ = model3.build(_statements(), circ=0)
        d = recalc.LibreOfficeDaemon()
        try:
            t0 = time.time()
            first = d.values(data)
            t_first = time.time() - t0
            times = []
            for _ in range(3):
                t0 = time.time()
                again = d.values(data)
                times.append(time.time() - t0)
            self.assertEqual(d.starts, 1, "the same soffice process must serve every call")
            self.assertEqual(first, again)
            self.assertGreater(len(first), 500)
            from om.consistency import recalc as one_shot
            t0 = time.time()
            one_shot(data)
            t_one = time.time() - t0
            print(f"\n[recalc timing] daemon first={t_first:.2f}s warm={[round(x, 2) for x in times]} one-shot={t_one:.2f}s")
            self.assertLess(min(times), t_one, "a warm daemon call must beat a one-shot conversion")
            os.killpg(os.getpgid(d.pid), signal.SIGKILL)                 # simulate a crash
            time.sleep(0.5)
            self.assertEqual(d.values(data), first)
            self.assertEqual(d.starts, 2)
        finally:
            d.close()

    def test_values_errors_come_back_as_excel_codes(self):
        _need_lo(self)
        from om.xlsx import Workbook
        wb = Workbook()
        sh = wb.sheet("S")
        sh.set("A1", 1), sh.set("A2", 0)
        sh.set("B1", "=A1/A2"), sh.set("B2", '=VLOOKUP("x",A1:A2,1,FALSE)'), sh.set("B3", '="t"&A1'), sh.set("B4", "=A1+1")
        vals = recalc.daemon().values(wb.to_bytes())
        self.assertEqual(vals[("S", 1, 2)], "#DIV/0!")
        self.assertEqual(vals[("S", 2, 2)], "#N/A")
        self.assertEqual(vals[("S", 3, 2)], "t1")
        self.assertEqual(vals[("S", 4, 2)], 2.0)

    def test_singleton_is_shared(self):
        self.assertIs(recalc.daemon(), recalc.daemon())


if __name__ == "__main__":
    unittest.main()
