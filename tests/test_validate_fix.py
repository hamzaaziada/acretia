"""FP-S4-F: consistency.rowset. One broken formula in a short (3-column or 2-column) period row must be caught and located,
on hand-made rows and on random neighbour-row mutations of the model3, LBO and merger builders. Hermetic, fixed seed."""
import copy
import random
import re
import unittest

from om import bench, model3, templatefit as tf, validate_xlsx as vx
from om import statements as stm
from om.formula import calculate_workbook
from om.xlsx import Workbook, col_index, read, ref
from tests.test_model3 import synthetic_companyfacts
from tests.test_templatefit import _statements, firm_template

ID = "consistency.rowset"
HEADS = ("FY2023A", "FY2024A", "FY2025E", "FY2026E", "FY2027E")


def rowset_cells(data: bytes) -> list[tuple]:
    res = vx.validate(data)
    return [(f["sheet"], f["cell"]) for f in res["findings"] if f["id"] == ID]


def caught_cells(data: bytes) -> list[tuple]:
    """Located by any consistency rule (columns / rows / rowset): the older rules already catch some broken cells."""
    res = vx.validate(data)
    return [(f["sheet"], f["cell"]) for f in res["findings"] if f["id"].startswith("consistency.") and f["severity"] == "critical"]


def periods(rows, heads=HEADS) -> bytes:
    """A one-sheet model: row 5 period labels in C.., source numbers in rows 10-12, then the given (label, [C..G]) rows from row 20."""
    wb = Workbook()
    sh = wb.sheet("Model")
    sh.set("A2", "Model", kind="title")
    sh.set("A5", "USD in millions", kind="header")
    sh.set("B5", "", kind="header")
    for i, h in enumerate(heads):
        if h:
            sh.set((5, 3 + i), h, kind="header", align="right")
    for r in (10, 11, 12):
        sh.set((r, 1), f"Driver {r}")
        for i in range(len(heads)):
            sh.set((r, 3 + i), 10.0 * r + i, kind="input", fmt="num1")
    for n, (label, fs) in enumerate(rows):
        r = 20 + n
        sh.set((r, 1), label)
        for i, f in enumerate(fs):
            if f is not None:
                sh.set((r, 3 + i), f, fmt="num1")
    calculate_workbook(wb)
    return wb.to_bytes()


class TestHandMade(unittest.TestCase):
    def test_three_column_row_one_broken(self):
        data = periods([("Net revenue", [None, None, "=E10*E11", "=F10", "=G10*G11"])])
        self.assertEqual(caught_cells(data), [("Model", "F20")])

    def test_first_of_three_broken(self):
        data = periods([("Net revenue", [None, None, "=E10", "=F10*F11", "=G10*G11"])])
        self.assertEqual(rowset_cells(data), [("Model", "E20")])

    def test_clean_row_passes(self):
        data = periods([("Net revenue", [None, None, "=E10*E11", "=F10*F11", "=G10*G11"])])
        self.assertEqual(rowset_cells(data), [])

    def test_two_column_row_different_rowset(self):
        heads = ("FY2024A", "FY2025E", "FY2026E")
        data = periods([("Net revenue", [None, "=D10*D11", "=E10*E12"])], heads=heads)
        self.assertEqual(rowset_cells(data), [("Model", "E20")])

    def test_two_column_row_same_rowset_passes(self):
        heads = ("FY2024A", "FY2025E", "FY2026E")
        data = periods([("Net revenue", [None, "=D10*D11", "=E10*E11"])], heads=heads)
        self.assertEqual(rowset_cells(data), [])

    def test_opening_balance_exempt(self):
        # the first projection column opens from the last historical column; later columns roll off other rows
        data = periods([("Opening cash", [None, None, "=D20", "=F10+F11", "=G10+G11"])])
        self.assertEqual(rowset_cells(data), [])

    def test_opening_balance_control_same_column_flagged(self):
        data = periods([("Opening cash", [None, None, "=E12", "=F10+F11", "=G10+G11"])])
        self.assertEqual(rowset_cells(data), [("Model", "E20")])

    def test_total_row_exempt(self):
        data = periods([("Total revenue", [None, None, "=E10*E11", "=F10", "=G10*G11"])])
        self.assertEqual(rowset_cells(data), [])

    def test_boundary_not_compared(self):
        # a historical formula beside projection formulas is a different regime, not an inconsistency
        data = periods([("Net revenue", [None, "=D12", "=E10*E11", "=F10*F11", "=G10*G11"])])
        self.assertEqual(rowset_cells(data), [])


def candidates(wb) -> list[tuple]:
    """(sheet, row, projection columns) of mutable period rows: >= 2 adjacent formula cells in projection columns, no total/check label."""
    book = read(wb.to_bytes())
    sens = vx._sens_blocks(book)
    out = []
    for s in book.order:
        g = book.sheets[s]
        kinds = vx._period_kinds(g)
        sens_rows = {r for b in sens if b["sheet"] == s for r in range(min(b["hr"], *b["rows"]), max(b["rows"]) + 1)}
        for r in sorted({rr for (rr, _), c in g.items() if c.formula}):
            label = " ".join(str(g[(r, k)].value) for k in (1, 2) if (r, k) in g and isinstance(g[(r, k)].value, str))
            if r in sens_rows or vx.TOTAL_LABEL.search(label):
                continue
            cols = [c for c in sorted(kinds) if kinds[c] == "E" and (r, c) in g and g[(r, c)].formula]
            if len(cols) >= 2 and all(cols[i + 1] == cols[i] + 1 for i in range(len(cols) - 1)):
                out.append((s, r, cols))
    return out


def mutate(wb, g, s, r, c):
    """Copy of wb with one formula replaced by a reference to a neighbouring row in the same column, or None."""
    own = vx._rowset(vx.relative(g[(r, c)].formula, r, c))
    for dr in (1, -1, 2, -2):
        cell = g.get((r + dr, c))
        if cell is None or not (cell.formula or isinstance(cell.value, float)):
            continue
        new = f"={ref(r + dr, c)}"
        if vx._rowset(vx.relative(new, r, c)) == own:
            continue
        w = copy.deepcopy(wb)
        w[s].cells[(r, c)].value = new
        w[s].cells[(r, c)].cached = None
        return w, new
    return None


class TestMutationSweep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builds = bench.synthetic_builds()

    def test_neighbour_row_mutations_caught(self):
        rng = random.Random(20260101)
        for name in ("model3", "lbo", "merger"):
            wb, _ = self.builds[name]
            book = read(wb.to_bytes())
            cands = candidates(wb)
            self.assertGreaterEqual(len(cands), 5, name)
            done = 0
            for s, r, cols in rng.sample(cands, len(cands)):
                c = rng.choice(cols)
                m = mutate(wb, book.sheets[s], s, r, c)
                if m is None:
                    continue
                w, new = m
                got = caught_cells(w.to_bytes())
                self.assertIn((s, ref(r, c)), got, f"{name}: {s}!{ref(r, c)} -> {new} not caught/located (got {got})")
                done += 1
                if done == 5:
                    break
            self.assertEqual(done, 5, name)

    def test_merger_synergy_plant(self):
        """The independent gate's plant: after-tax synergies replaced by the pre-tax row in the first projection year."""
        wb, meta = self.builds["merger"]
        m = re.match(r"^'?(.+?)'?!\$?([A-Z]+)\$?(\d+)$", meta["plants"]["synergy_tax"])
        s, col, row = m.group(1), col_index(m.group(2)), int(m.group(3))
        w = copy.deepcopy(wb)
        w[s].cells[(row, col)].value = f"={ref(meta['rows']['Pro forma']['syn'], col)}"
        w[s].cells[(row, col)].cached = None
        calculate_workbook(w, iterate=True)
        self.assertIn((s, ref(row, col)), caught_cells(w.to_bytes()))
        self.assertIn((s, ref(row, col)), rowset_cells(w.to_bytes()))


class TestNoFalsePositives(unittest.TestCase):
    def test_builders_clean(self):
        for name, (wb, _) in bench.synthetic_builds().items():
            self.assertEqual(rowset_cells(wb.to_bytes()), [], name)

    def test_model3_circ_variants(self):
        s = stm.build(synthetic_companyfacts(), "TEST")
        for circ in (0, 1):
            data, _ = model3.build(s, circ=circ)
            self.assertEqual(rowset_cells(data), [], f"circ={circ}")

    def test_templatefit_clean(self):
        out, _ = tf.generate(firm_template(), _statements())
        self.assertEqual(rowset_cells(out), [])


if __name__ == "__main__":
    unittest.main()
