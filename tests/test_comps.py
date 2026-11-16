"""Trading comps builder and market-data helper. Hermetic: synthetic companyfacts variants, no network."""
import copy
import statistics
import unittest
from datetime import date

from om import bench, comps, market, modelcheck
from om.prices import Quote
from om.xlsx import read
from tests.test_model3 import synthetic_companyfacts

LAST_DAY = {3: "31", 6: "30", 9: "30", 12: "31"}


def _row(val, end, form="10-K", accn="0000000001-25-000001", filed="2025-02-15", start=None):
    d = {"val": val, "end": end, "form": form, "accn": accn, "filed": filed}
    if start:
        d["start"] = start
    return d


def make_co(ticker, name, *, scale=1.0, fye=12, options=None, rsu=None, shares=None, neg=False, ytd=False, float_=None, accn=None):
    """A variant of the synthetic company: USD values scaled, optional June/Sept year end, options, RSUs, cover facts."""
    cf = copy.deepcopy(synthetic_companyfacts())
    cf["entityName"] = name
    cf["cik"] = abs(hash(ticker)) % 1_000_000 + 1000
    g = cf["facts"]["us-gaap"]
    for concept, node in g.items():
        for unit, rows in node["units"].items():
            for r in rows:
                if unit in ("USD", "USD/shares"):
                    r["val"] *= scale
                if accn:
                    r["accn"] = accn
                if fye != 12:
                    y = int(r["end"][:4])
                    r["end"] = f"{y}-{fye:02d}-{LAST_DAY[fye]}"
                    if "start" in r:
                        r["start"] = f"{y - 1}-{fye + 1:02d}-01"
    if neg:
        for r in g["OperatingIncomeLoss"]["units"]["USD"]:
            r["val"] = -300e6
        for r in g["NetIncomeLoss"]["units"]["USD"]:
            r["val"] = -250e6
        for r in g["EarningsPerShareDiluted"]["units"]["USD/shares"]:
            r["val"] = -2.5
    end = f"2024-{fye:02d}-{LAST_DAY[fye]}"
    a = accn or "0000000001-25-000001"
    if options:
        n, k = options
        g["ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber"] = {"units": {"shares": [_row(n, end, accn=a)]}}
        g["ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice"] = {
            "units": {"USD/shares": [_row(k, end, accn=a)]}}
    if rsu:
        g["ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber"] = {
            "units": {"shares": [_row(rsu, end, accn=a)]}}
    if ytd:
        for concept, v1, v0 in (("Revenues", 800e6, 700e6), ("NetIncomeLoss", 150e6, 120e6)):
            g[concept]["units"]["USD"] += [_row(v1 * scale, "2025-09-30", "10-Q", "0000000001-25-000099", "2025-11-01", "2025-01-01"),
                                           _row(v0 * scale, "2024-09-30", "10-Q", "0000000001-24-000077", "2024-11-01", "2024-01-01")]
    if shares:
        cf["facts"]["dei"] = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [_row(shares, "2025-02-01", accn=a)]}}}
    if float_:
        cf["facts"].setdefault("dei", {})["EntityPublicFloat"] = {"units": {"USD": [_row(float_, "2024-06-28", accn=a)]}}
    return ticker, cf


def mk(price):
    return {"price": price, "as_of": "2025-03-03", "source": "test quote", "basis": "quote"}


def fixture():
    tgt = make_co("TGT", "Target Corp", options=(8e6, 25.0), rsu=2e6, shares=100e6, accn="0000000001-25-000010")
    peers = [make_co("PAA", "Peer A", scale=1.5, options=(10e6, 30.0), shares=150e6, accn="0000000001-25-000011"),
             make_co("PBB", "Peer B", scale=0.8, fye=6, options=(5e6, 35.0), shares=80e6, accn="0000000001-25-000012"),   # out of the money
             make_co("PCC", "Peer C", scale=2.0, fye=9, shares=200e6, accn="0000000001-25-000013"),
             make_co("PDD", "Peer D", scale=1.2, neg=True, shares=120e6, accn="0000000001-25-000014")]
    markets = {"TGT": mk(40.0), "PAA": mk(60.0), "PBB": mk(20.0), "PCC": mk(90.0), "PDD": mk(15.0)}
    return tgt, peers, markets


def _latest(cf, concept, kind="us-gaap", pos=-1):
    unit = next(iter(cf["facts"][kind][concept]["units"]))
    rows = sorted(cf["facts"][kind][concept]["units"][unit], key=lambda r: r["end"])
    return rows[pos]["val"]


def py_tsm(price, n, k):
    return max(0.0, n - n * k / price) if price > k else 0.0


def expected(cf, price, opt=(0.0, 0.0), rsu=0.0, shares=None, fye=12, cal=12):
    """Independent recomputation of equity value, EV and the multiples from the raw facts."""
    g = lambda c, p=-1: _latest(cf, c, pos=p)
    basic = (shares if shares is not None else _latest(cf, "EntityCommonStockSharesOutstanding", "dei")) / 1e6
    dil = basic + rsu / 1e6 + py_tsm(price, opt[0] / 1e6, opt[1])
    eqv = price * dil
    debt = (g("LongTermDebtCurrent") + g("LongTermDebtNoncurrent")) / 1e6
    cash = g("CashAndCashEquivalentsAtCarryingValue") / 1e6
    ev = eqv + debt - cash
    lag = (fye - cal) % 12
    wp = lag / 12
    out = {"dil": dil, "eqv": eqv, "ev": ev}
    for key, ebitdaless in (("rev", "Revenues"), ("ebit", "OperatingIncomeLoss"), ("ni", "NetIncomeLoss")):
        out[key + "_ltm"] = g(ebitdaless) / 1e6
        out[key + "_cy"] = ((1 - wp) * g(ebitdaless) + wp * g(ebitdaless, -2)) / 1e6
    da = lambda p: g("DepreciationDepletionAndAmortization", p) / 1e6
    out["ebitda_ltm"] = out["ebit_ltm"] + da(-1)
    out["ebitda_cy"] = (1 - wp) * (g("OperatingIncomeLoss") / 1e6 + da(-1)) + wp * (g("OperatingIncomeLoss", -2) / 1e6 + da(-2))
    out["eps_ltm"] = g("EarningsPerShareDiluted")
    out["eps_cy"] = (1 - wp) * g("EarningsPerShareDiluted") + wp * g("EarningsPerShareDiluted", -2)
    return out


def nm(num, den, cap):
    return "NM" if den <= 0 or num <= 0 or num / den > cap else num / den


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tgt, cls.peers, cls.markets = fixture()
        cls.data, cls.meta = comps.build(cls.tgt, cls.peers, markets=cls.markets, as_of="2025-03-03")
        cls.book = read(cls.data)

    def v(self, sheet, where):
        return self.book.value(sheet, where)

    def cell(self, sheet, key, ticker):
        return f"{self.meta['columns'][ticker]}{self.meta['rows'][sheet][key]}"


class AcceptanceTests(Base):
    def test_modelcheck_production_ready(self):
        g = modelcheck.grade(self.data)
        self.assertTrue(g["production_ready"], modelcheck.report_md("comps", g))
        self.assertGreaterEqual(g["score"], 95, modelcheck.report_md("comps", g))
        self.assertTrue(all(r["passed"] is not False for r in g["graders"] if r["critical"]))
        print(f"\ncomps modelcheck score: {g['score']}")

    def test_no_typed_literals_in_formulas(self):
        g = modelcheck.grade(self.data)
        c = next(r for r in g["graders"] if r["id"] == "constants")
        self.assertTrue(c["passed"], c["detail"])

    def test_libreoffice_agrees(self):
        r = bench.agree(self.data)
        if r is None:
            self.skipTest("soffice not available")
        self.assertEqual(r["mismatches"], 0, r["examples"])

    def test_master_check_ok(self):
        self.assertEqual(self.v("Checks", f"C{self.meta['rows']['Checks']['master']}"), "OK")
        self.assertTrue(self.meta["converged"])

    def test_outputs_and_plants_resolve(self):
        ids = {o["id"] for o in self.meta["outputs"]}
        self.assertEqual(ids, {"comps.median_ev_ebitda_ltm", "comps.median_pe_ltm", "comps.implied_price_low", "comps.implied_price_high",
                               "comps.target_ev", "comps.target_diluted_shares"})
        for o in self.meta["outputs"]:
            self.assertIsNotNone(self.v(o["sheet"], o["ref"]), o["id"])
        for k, p in self.meta["plants"].items():
            sheet, where = p.rsplit("!", 1)
            self.assertIsNotNone(self.v(sheet, where), k)
        ff = self.meta["football_field"]
        self.assertEqual(ff["sheet"], "Valuation")
        self.assertEqual(self.v("Valuation", f"D{ff['first_row']}") is not None, True)

    def test_sourced_inputs(self):
        r = self.meta["rows"]["Inputs"]["rev_fy"]
        c = self.meta["columns"]["PAA"]
        self.assertIn("Revenues", self.book.comments["Inputs"][(r, 4)])
        self.assertIn("sec.gov", self.book.links["Inputs"][(r, 4)])
        self.assertEqual(c, "D")


class TsmTests(Base):
    def test_diluted_shares_match_independent_tsm(self):
        spec = {"TGT": ((8e6, 25.0), 2e6, 100e6, 12), "PAA": ((10e6, 30.0), 0, 150e6, 12), "PBB": ((5e6, 35.0), 0, 80e6, 6),
                "PCC": ((0, 0), 0, 200e6, 9), "PDD": ((0, 0), 0, 120e6, 12)}
        cfs = dict([self.tgt] + self.peers)
        for t, (opt, rsu, sh, fye) in spec.items():
            e = expected(cfs[t], self.markets[t]["price"], opt, rsu, sh, fye)
            self.assertAlmostEqual(self.v("Equity value", self.cell("Equity value", "dil", t)), e["dil"], places=6, msg=t)
            self.assertAlmostEqual(self.v("Equity value", self.cell("Equity value", "eqv", t)), e["eqv"], places=4, msg=t)
            self.assertAlmostEqual(self.v("Equity value", self.cell("Equity value", "ev", t)), e["ev"], places=4, msg=t)

    def test_in_the_money_adds_shares_out_of_the_money_adds_none(self):
        itm = self.v("Equity value", self.cell("Equity value", "itm", "PAA"))
        self.assertAlmostEqual(itm, 10 - 10 * 30.0 / 60.0, places=9)
        self.assertEqual(self.v("Equity value", self.cell("Equity value", "itm", "PBB")), 0.0)   # strike 35 > price 20
        d = self.v("Equity value", self.cell("Equity value", "dil", "PBB"))
        self.assertAlmostEqual(d, 80.0, places=9)
        self.assertGreaterEqual(self.v("Equity value", self.cell("Equity value", "dil", "PAA")), 150.0)

    def test_plant_cells_point_at_tsm_and_bridge(self):
        sheet, where = self.meta["plants"]["tsm"].rsplit("!", 1)
        f = self.book.cell(sheet, where).formula
        self.assertTrue(f.startswith("=IF("), f)
        sheet, where = self.meta["plants"]["bridge"].rsplit("!", 1)
        self.assertIn("+", self.book.cell(sheet, where).formula)


class MultiplesTests(Base):
    def comps_cell(self, ticker, col_key):
        mcol = {"ev_rev_ltm": "F", "ev_rev_cy": "G", "ev_ebitda_ltm": "H", "ev_ebitda_cy": "I", "ev_ebit_ltm": "J", "ev_ebit_cy": "K",
                "pe_ltm": "L", "pe_cy": "M"}[col_key]
        rows = {"TGT": 7, "PAA": 10, "PBB": 11, "PCC": 12, "PDD": 13}
        return self.v("Comps", f"{mcol}{rows[ticker]}")

    def test_multiples_match_python(self):
        spec = {"TGT": ((8e6, 25.0), 2e6, 100e6, 12), "PAA": ((10e6, 30.0), 0, 150e6, 12), "PBB": ((5e6, 35.0), 0, 80e6, 6),
                "PCC": ((0, 0), 0, 200e6, 9), "PDD": ((0, 0), 0, 120e6, 12)}
        cfs = dict([self.tgt] + self.peers)
        for t, (opt, rsu, sh, fye) in spec.items():
            price = self.markets[t]["price"]
            e = expected(cfs[t], price, opt, rsu, sh, fye)
            for per in ("ltm", "cy"):
                for key, num, den, cap in (("ev_rev", e["ev"], e["rev_" + per], 25), ("ev_ebitda", e["ev"], e["ebitda_" + per], 100),
                                           ("ev_ebit", e["ev"], e["ebit_" + per], 100), ("pe", price, e["eps_" + per], 100)):
                    want = nm(num, den, cap)
                    got = self.comps_cell(t, f"{key}_{per}")
                    if want == "NM":
                        self.assertEqual(got, "NM", f"{t} {key} {per}")
                    else:
                        self.assertAlmostEqual(got, want, places=6, msg=f"{t} {key} {per}")

    def test_negative_ebitda_peer_is_nm_and_excluded(self):
        for k in ("ev_ebitda_ltm", "ev_ebit_ltm", "pe_ltm", "ev_ebitda_cy"):
            self.assertEqual(self.comps_cell("PDD", k), "NM", k)
        nums = [self.comps_cell(t, "ev_ebitda_ltm") for t in ("PAA", "PBB", "PCC")]
        self.assertTrue(all(isinstance(x, float) for x in nums))
        q = statistics.quantiles(nums, n=4, method="inclusive")
        st = self.meta["rows"]["Comps"]
        self.assertAlmostEqual(self.v("Comps", f"H{st['q1']}"), q[0], places=9)
        self.assertAlmostEqual(self.v("Comps", f"H{st['median']}"), q[1], places=9)
        self.assertAlmostEqual(self.v("Comps", f"H{st['q3']}"), q[2], places=9)
        self.assertAlmostEqual(self.v("Comps", f"H{st['mean']}"), statistics.mean(nums), places=9)
        self.assertAlmostEqual(self.v("Comps", f"H{st['max']}"), max(nums), places=9)
        self.assertAlmostEqual(self.v("Comps", f"H{st['min']}"), min(nums), places=9)
        self.assertEqual(self.v("Comps", f"H{st['n']}"), 3.0)

    def test_target_excluded_from_statistics(self):
        st = self.meta["rows"]["Comps"]
        nums = [self.comps_cell(t, "ev_rev_ltm") for t in ("PAA", "PBB", "PCC", "PDD")]
        self.assertAlmostEqual(self.v("Comps", f"F{st['median']}"), statistics.median(nums), places=9)
        self.assertNotAlmostEqual(self.v("Comps", f"F{st['median']}"), statistics.median(nums + [self.comps_cell("TGT", "ev_rev_ltm")]), places=6)

    def test_cap_makes_nm(self):
        tgt, peers, markets = fixture()
        markets = dict(markets, PAA=mk(5000.0))       # absurd price: EV/Revenue far above the 25x cap, P/E above 100x
        data, meta = comps.build(tgt, peers, markets=markets)
        bk = read(data)
        self.assertEqual(bk.value("Comps", "F10"), "NM")
        self.assertEqual(bk.value("Comps", "L10"), "NM")
        self.assertIsInstance(bk.value("Comps", "F11"), float)


class CalendarisationTests(Base):
    def test_weights(self):
        K = self.meta["rows"]["Calendarisation"]
        for t, wp in (("TGT", 0.0), ("PAA", 0.0), ("PBB", 0.5), ("PCC", 0.75)):
            c = self.meta["columns"][t]
            self.assertAlmostEqual(self.v("Calendarisation", f"{c}{K['wp']}"), wp, places=9, msg=t)
            self.assertAlmostEqual(self.v("Calendarisation", f"{c}{K['wl']}"), 1 - wp, places=9, msg=t)

    def test_cy_blends_fiscal_years(self):
        K = self.meta["rows"]["Calendarisation"]
        c = self.meta["columns"]["PBB"]
        fy, py = self.v("Calendarisation", f"{c}{K['rev_fy']}"), self.v("Calendarisation", f"{c}{K['rev_py']}")
        self.assertAlmostEqual(self.v("Calendarisation", f"{c}{K['rev_cy']}"), 0.5 * fy + 0.5 * py, places=9)
        c = self.meta["columns"]["PCC"]
        fy, py = self.v("Calendarisation", f"{c}{K['rev_fy']}"), self.v("Calendarisation", f"{c}{K['rev_py']}")
        self.assertAlmostEqual(self.v("Calendarisation", f"{c}{K['rev_cy']}"), 0.25 * fy + 0.75 * py, places=9)

    def test_other_calendar_month(self):
        tgt, peers, markets = fixture()
        data, meta = comps.build(tgt, peers, markets=markets, calendar_month=6)
        bk = read(data)
        K = meta["rows"]["Calendarisation"]
        self.assertAlmostEqual(bk.value("Calendarisation", f"C{K['wp']}"), 0.5)       # Dec FYE vs June CY
        self.assertAlmostEqual(bk.value("Calendarisation", f"E{K['wp']}"), 0.0)       # June FYE vs June CY
        self.assertEqual(bk.value("Checks", f"C{meta['rows']['Checks']['master']}"), "OK")


class LtmAndValuationTests(unittest.TestCase):
    def test_ltm_formula_from_ytd(self):
        tgt = make_co("TGT", "Target Corp", shares=100e6, ytd=True, accn="0000000001-25-000010")
        peers = [make_co("PAA", "Peer A", scale=1.5, shares=150e6, accn="0000000001-25-000011"),
                 make_co("PBB", "Peer B", scale=0.8, shares=80e6, accn="0000000001-25-000012")]
        data, meta = comps.build(tgt, peers, markets={"TGT": mk(40.0), "PAA": mk(60.0), "PBB": mk(20.0)})
        bk = read(data)
        I = meta["rows"]["Inputs"]
        fy = bk.value("Inputs", f"C{I['rev_fy']}")
        ytd, pytd = bk.value("Inputs", f"C{I['rev_ytd']}"), bk.value("Inputs", f"C{I['rev_pytd']}")
        self.assertAlmostEqual(ytd, 800.0)
        self.assertAlmostEqual(pytd, 700.0)
        self.assertAlmostEqual(bk.value("Inputs", f"C{I['rev_ltm']}"), fy + 800.0 - 700.0)
        self.assertTrue(bk.cell("Inputs", f"C{I['rev_ltm']}").formula.startswith("="))
        self.assertEqual(bk.value("Checks", f"C{meta['rows']['Checks']['master']}"), "OK")
        self.assertTrue(modelcheck.grade(data)["production_ready"])

    def test_implied_price_uses_tsm_closed_form(self):
        tgt, peers, markets = fixture()
        data, meta = comps.build(tgt, peers, markets=markets)
        bk = read(data)
        R = meta["rows"]["Valuation"]
        E = meta["rows"]["Equity value"]
        bridge = bk.value("Equity value", f"C{E['bridge']}")
        ex = bk.value("Equity value", f"C{E['exopt']}")
        n, k = 8.0, 25.0
        row = next(r for r in range(R["method_first"], R["method_last"] + 1) if bk.value("Valuation", f"A{r}") == "EV / EBITDA LTM")
        q1, q3 = bk.value("Valuation", f"C{row}"), bk.value("Valuation", f"D{row}")
        ebitda = bk.value("Valuation", f"E{row}")
        for mult, col in ((q1, "J"), (q3, "K")):
            equity = mult * ebitda - bridge
            lo, hi = 0.01, 10000.0
            for _ in range(200):                     # bisection on the fixed point P * (ex + TSM(P)) = equity
                mid = (lo + hi) / 2
                if mid * (ex + py_tsm(mid, n, k)) < equity:
                    lo = mid
                else:
                    hi = mid
            self.assertAlmostEqual(bk.value("Valuation", f"{col}{row}"), (lo + hi) / 2, places=5)

    def test_football_field_shape(self):
        tgt, peers, markets = fixture()
        data, meta = comps.build(tgt, peers, markets=markets)
        bk = read(data)
        ff = meta["football_field"]
        self.assertEqual(ff["last_row"] - ff["first_row"] + 1, 8)
        for r in range(ff["first_row"], ff["last_row"] + 1):
            lo, hi, sp = (bk.value("Valuation", f"{c}{r}") for c in "BCD")
            if isinstance(lo, float) and isinstance(hi, float):
                self.assertAlmostEqual(sp, hi - lo, places=9)
                self.assertGreaterEqual(sp, 0)
            self.assertAlmostEqual(bk.value("Valuation", f"E{r}"), 40.0)

    def test_missing_price_is_never_invented(self):
        tgt, peers, markets = fixture()
        with self.assertRaises(ValueError):
            comps.build(tgt, peers, markets={k: v for k, v in markets.items() if k != "TGT"})
        data, meta = comps.build(tgt, peers, markets={k: v for k, v in markets.items() if k != "PCC"})
        self.assertNotIn("PCC", meta["peers"])
        self.assertTrue(any("PCC" in w for w in meta["warnings"]))


class MarketTests(unittest.TestCase):
    def cf(self):
        return make_co("X", "X Co", shares=100e6, float_=3_000e6)[1]

    def test_public_float_proxy(self):
        m = market.from_companyfacts(self.cf())
        self.assertAlmostEqual(m["price"], 30.0)
        self.assertEqual(m["as_of"], "2024-06-28")
        self.assertEqual(m["basis"], "public_float")
        for s in ("EntityPublicFloat", "EntityCommonStockSharesOutstanding", "0000000001-25-000001", "affiliates"):
            self.assertIn(s, m["source"])

    def test_none_without_dei_facts(self):
        self.assertIsNone(market.from_companyfacts(synthetic_companyfacts()))
        only_shares = make_co("X", "X Co", shares=100e6)[1]
        self.assertIsNone(market.from_companyfacts(only_shares))
        only_float = make_co("X", "X Co", float_=3e9)[1]
        self.assertIsNone(market.from_companyfacts(only_float))
        self.assertIsNone(market.resolve("X", synthetic_companyfacts()))

    def test_resolve_prefers_quote(self):
        q = Quote("X", 45.5, "USD", date(2025, 3, 3), "csv:test.csv")
        m = market.resolve("X", self.cf(), {"X": q})
        self.assertEqual(m["basis"], "quote")
        self.assertAlmostEqual(m["price"], 45.5)
        self.assertEqual(m["as_of"], "2025-03-03")
        self.assertAlmostEqual(market.resolve("X", self.cf(), quotes=q)["price"], 45.5)
        self.assertEqual(market.resolve("X", self.cf(), {})["basis"], "public_float")
        adr = Quote("X", 90.0, "USD", date(2025, 3, 3), "csv", ordinary_per_unit=2.0)
        self.assertAlmostEqual(market.from_quote(adr)["price"], 45.0)


if __name__ == "__main__":
    unittest.main()
