"""Merger (accretion / dilution) model: conventions acceptance, independent recomputation, structural identities."""
import copy
import re
import unittest

from om import bench, merger, modelcheck
from om import statements as stm
from om.xlsx import read, split_ref
from tests.test_model3 import synthetic_companyfacts

ACQ_MKT = {"price": 30.0, "as_of": "2025-03-31", "source": "unit-test quote"}
TGT_MKT = {"price": 12.0, "as_of": "2025-03-31", "source": "unit-test quote"}


def scaled(cf: dict, k: float) -> dict:
    """A copy of the companyfacts with every USD and share value multiplied by k (per-share figures untouched)."""
    cf = copy.deepcopy(cf)
    for tax in cf["facts"].values():
        for concept in tax.values():
            for unit, rows in concept["units"].items():
                if unit in ("USD", "shares"):
                    for r in rows:
                        r["val"] *= k
    return cf


def statements() -> tuple:
    cf = synthetic_companyfacts()
    return stm.build(cf, "ACQ"), stm.build(scaled(cf, 0.3), "TGT")


def build(assumptions=None, acq_mkt=ACQ_MKT, tgt_mkt=TGT_MKT):
    a, t = statements()
    x, meta = merger.build(a, t, acq_market=acq_mkt, tgt_market=tgt_mkt, assumptions=assumptions)
    return a, t, x, meta, read(x)


def val(book, meta, sheet, key, col=3):
    return book.value(sheet, f"{_col(col)}{meta['rows'][sheet][key]}")


def _col(c):
    return "ABCDEFGHIJ"[c - 1]


def out(book, meta, oid):
    o = next(o for o in meta["outputs"] if o["id"] == oid)
    return book.value(o["sheet"], o["ref"])


class MergerAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a, cls.t, cls.x, cls.meta, cls.book = build()

    def test_modelcheck_production_ready(self):
        g = modelcheck.grade(self.x)
        failed = [(r["id"], r["detail"], (r.get("cells") or [])[:3]) for r in g["graders"] if r["critical"] and r["passed"] is False]
        self.assertTrue(g["production_ready"], failed)
        self.assertGreaterEqual(g["score"], 95, [(r["id"], r["score"]) for r in g["graders"]])

    def test_no_literals_and_cross_sheet_green(self):
        g = modelcheck.grade(self.x)
        by = {r["id"]: r for r in g["graders"]}
        self.assertTrue(by["constants"]["passed"], by["constants"]["detail"])
        self.assertTrue(by["colours"]["passed"], by["colours"]["cells"][:3])

    def test_master_check_ok_and_all_checks_ok(self):
        self.assertEqual(self.book.value("Checks", f"C{self.meta['rows']['Checks']['master']}"), "OK")
        self.assertEqual(self.book.value("Cover", f"C{self.meta['rows']['Cover']['master']}"), "OK")
        first, last = self.meta["rows"]["Checks"]["first"], self.meta["rows"]["Checks"]["last"]
        for r in range(first, last + 1):
            self.assertEqual(self.book.value("Checks", f"C{r}"), "OK", r)

    def test_libreoffice_agrees(self):
        res = bench.agree(self.x)
        if res is None:
            self.skipTest("LibreOffice (soffice) is not installed")
        self.assertEqual(res["mismatches"], 0, res["examples"])

    def test_meta_contract(self):
        self.assertTrue(self.meta["converged"])
        self.assertEqual(self.meta["model"], "merger")
        ids = {o["id"] for o in self.meta["outputs"]}
        self.assertEqual(ids, {"merger.accretion_y1_pct", "merger.accretion_y2_pct", "merger.pf_eps_y1", "merger.goodwill",
                               "merger.breakeven_synergies_y1", "merger.offer_price", "merger.ev_paid", "merger.new_shares"})
        for o in self.meta["outputs"]:
            self.assertIsInstance(out(self.book, self.meta, o["id"]), float, o["id"])
        for k in ("shares", "goodwill", "synergy_tax"):
            sheet, cell = self.meta["plants"][k].split("!")
            c = self.book.cell(sheet, cell)
            self.assertIsNotNone(c, k)
            self.assertTrue(c.formula, k)

    def test_sheets_and_sources(self):
        self.assertEqual(self.book.order, ["Cover", "Assumptions", "Purchase price", "Sources & Uses", "PPA", "Pro forma", "Breakeven",
                                           "Sensitivity", "Checks", "Filings"])
        self.assertIn("unit-test quote", self.book.comments["Assumptions"][split_ref(f"C{self.meta['rows']['Assumptions']['acq_price']}")])
        self.assertTrue(self.book.links["Filings"])
        self.assertTrue(self.book.comments["Filings"])

    def test_independent_year1_recomputation(self):
        a, t, book, meta = self.a, self.t, self.book, self.meta
        d = meta["defaults"]
        la, lt = len(a.years) - 1, len(t.years) - 1
        na, nt = a.get("diluted_shares", la), t.get("diluted_shares", lt)
        ni_a = a.get("revenue", la) * (1 + d["acq_growth"][0]) * d["acq_margin"][0]
        ni_t = t.get("revenue", lt) * (1 + d["tgt_growth"][0]) * d["tgt_margin"][0]
        eq = TGT_MKT["price"] * (1 + d["premium"]) * nt
        fees = d["fee_pct"] * eq
        debt = d["pct_cash"] * eq + fees - d["cash_used"]
        new_sh = d["pct_stock"] * eq / ACQ_MKT["price"]
        tb = t.get("equity_parent", lt) - (t.get("goodwill", lt) or 0)
        wu = d["wu_pct"] * max(0.0, eq - tb)
        adj = (d["syn_runrate"] * d["syn_phase"][0] - d["integ"][0] - debt * d["rate_debt"] - d["cash_used"] * d["rate_cash"] - wu / d["life"]) * (1 - d["tax"])
        pf_eps = (ni_a + ni_t + adj) / (na + new_sh)
        sa_eps = ni_a / na
        self.assertAlmostEqual(out(book, meta, "merger.pf_eps_y1"), pf_eps, places=9)
        self.assertAlmostEqual(out(book, meta, "merger.accretion_y1_pct"), pf_eps / sa_eps - 1, places=9)
        self.assertAlmostEqual(out(book, meta, "merger.new_shares"), new_sh, places=9)
        self.assertAlmostEqual(out(book, meta, "merger.offer_price"), TGT_MKT["price"] * (1 + d["premium"]), places=9)

    def test_ev_and_goodwill_identity(self):
        a, t, book, meta = self.a, self.t, self.book, self.meta
        lt = len(t.years) - 1
        eq = val(book, meta, "Purchase price", "equity")
        net_debt = (t.get("debt_current", lt) or 0) + (t.get("debt_noncurrent", lt) or 0) - (t.get("cash", lt) or 0) - (t.get("sti", lt) or 0)
        self.assertAlmostEqual(out(book, meta, "merger.ev_paid"), eq + net_debt, places=6)
        tax = meta["defaults"]["tax"]
        tb = t.get("equity_parent", lt) - (t.get("goodwill", lt) or 0)
        wu = meta["defaults"]["wu_pct"] * max(0.0, eq - tb)
        gw = out(book, meta, "merger.goodwill")
        self.assertAlmostEqual(gw, eq - (tb + wu - wu * tax), places=6)
        self.assertGreaterEqual(gw, 0)
        # book equity + write-up - DTL + goodwill - old goodwill = price
        self.assertAlmostEqual(t.get("equity_parent", lt) - t.get("goodwill", lt) + wu - wu * tax + gw, eq, places=6)

    def test_sources_equal_uses(self):
        b, m = self.book, self.meta
        self.assertAlmostEqual(val(b, m, "Sources & Uses", "s_total"), val(b, m, "Sources & Uses", "u_total"), places=9)

    def test_sensitivity_centres_equal_base(self):
        b, m = self.book, self.meta
        S = m["rows"]["Sensitivity"]
        base = out(b, m, "merger.accretion_y1_pct")
        self.assertAlmostEqual(b.value("Sensitivity", f"F{S['g1_centre']}"), base, places=9)
        self.assertAlmostEqual(b.value("Sensitivity", f"F{S['g2_centre']}"), base, places=9)
        # monotone: a higher premium is more dilutive down grid 1; more synergies more accretive down grid 2
        g1 = [b.value("Sensitivity", f"F{S['g1_centre'] + i}") for i in (-2, -1, 0, 1, 2)]
        g2 = [b.value("Sensitivity", f"F{S['g2_centre'] + i}") for i in (-2, -1, 0, 1, 2)]
        self.assertEqual(g1, sorted(g1, reverse=True))
        self.assertEqual(g2, sorted(g2))


class MergerBehaviour(unittest.TestCase):
    def test_all_stock_zero_premium_equal_pe_is_neutral(self):
        a, t = statements()
        d = merger.defaults(a, t, ACQ_MKT, TGT_MKT)
        la, lt = len(a.years) - 1, len(t.years) - 1
        ni_a = a.get("revenue", la) * (1 + d["acq_growth"][0]) * d["acq_margin"][0]
        ni_t = t.get("revenue", lt) * (1 + d["tgt_growth"][0]) * d["tgt_margin"][0]
        na, nt = a.get("diluted_shares", la), t.get("diluted_shares", lt)
        # target priced so its equity value / year-1 net income equals the acquirer's: P/E parity
        px = ACQ_MKT["price"] * na * ni_t / (ni_a * nt)
        ass = {"premium": 0.0, "pct_stock": 1.0, "pct_cash": 0.0, "fee_pct": 0.0, "syn_runrate": 0.0, "integ": [0.0, 0.0, 0.0],
               "wu_pct": 0.0, "cash_used": 0.0}
        _, _, x, meta, book = build(ass, tgt_mkt={**TGT_MKT, "price": px})
        self.assertAlmostEqual(out(book, meta, "merger.accretion_y1_pct"), 0.0, places=9)
        self.assertEqual(book.value("Checks", f"C{meta['rows']['Checks']['master']}"), "OK")

    def test_breakeven_synergies_give_zero_accretion(self):
        ass = {"premium": 3.0, "pct_stock": 1.0, "pct_cash": 0.0, "cash_used": 0.0}
        _, _, x, meta, book = build(ass)
        base = out(book, meta, "merger.accretion_y1_pct")
        be = out(book, meta, "merger.breakeven_synergies_y1")
        self.assertLess(base, 0.0)
        self.assertGreater(be, meta["defaults"]["syn_runrate"] * meta["defaults"]["syn_phase"][0])
        ass["syn_runrate"] = be / meta["defaults"]["syn_phase"][0]
        _, _, _, meta2, book2 = build(ass)
        self.assertAlmostEqual(out(book2, meta2, "merger.accretion_y1_pct"), 0.0, places=9)
        self.assertEqual(book2.value("Checks", f"C{meta2['rows']['Checks']['master']}"), "OK")

    def test_max_premium_is_eps_neutral(self):
        _, _, x, meta, book = build()
        prem = val(book, meta, "Breakeven", "prem_star")
        self.assertGreater(prem, meta["defaults"]["premium"])
        _, _, _, meta2, book2 = build({"premium": prem})
        self.assertAlmostEqual(out(book2, meta2, "merger.accretion_y1_pct"), 0.0, places=9)

    def test_overrides_flow_through(self):
        _, _, _, meta, book = build({"premium": 0.5})
        self.assertAlmostEqual(out(book, meta, "merger.offer_price"), 18.0, places=9)

    def test_market_price_required(self):
        a, t = statements()
        with self.assertRaises(ValueError):
            merger.build(a, t, acq_market={"price": 0, "as_of": "x", "source": "x"}, tgt_market=TGT_MKT)

    def test_assumption_inputs_are_blue_with_fill(self):
        _, _, x, meta, book = build()
        r = meta["rows"]["Assumptions"]["premium"]
        c = book.cell("Assumptions", f"C{r}")
        self.assertEqual(c.color, "0000FF")
        self.assertFalse(re.search(r"^=", str(c.value or "")))


if __name__ == "__main__":
    unittest.main()
