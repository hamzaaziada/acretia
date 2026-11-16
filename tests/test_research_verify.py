"""S6.2 figure verifier tests: offline, synthetic, deterministic."""
import socket
import unittest
from unittest import mock

from src.harness.research.api import ExcelInputPayload, ResearchResult, SourcedFigure
from src.harness.research.verify import (SourceResolver, Verdict, extract_numbers, verify_figure, verify_result)

H = "a" * 64
PAGE = ("Consolidated Statements of Operations (in millions)\nTotal net sales  391,035\n"
        "Gross margin percentage  46.2 %\nOperating loss (1,234)\n")
THOUSANDS = "Statement (in thousands)\nRevenue 1,234 ; Cost 900\n"


def fig(label="Revenue", value=391035.0, units="USD m", period="FY2024", as_of="2024-11-01", **cit):
    c = {"doc_id": "AAPL", "sha256_span_hash": H, "as_of": as_of}
    c.update(cit)
    if not (c.get("url") or c.get("source_url")) and c.get("page") is None and "page" not in cit:
        c["url"] = "https://example.com/x"
    return SourcedFigure.from_dict({"label": label, "value": value, "units": units, "period": period, "citation": c})


def resolver():
    r = SourceResolver()
    r.add_page("AAPL", 3, PAGE).add_page("AAPL", 4, "nothing relevant here")
    r.add_page("TH", 1, THOUSANDS)
    r.add_xbrl("AAPL", "us-gaap:Revenues", "FY2024", 391035e6)
    r.add_cell("model.xlsx", "IS!B5", 391035.0)
    r.add_url("https://example.com/x", "Revenue was $391.0 billion in fiscal 2024.")
    return r


def qfig(quote, value=391035.0, units="USD m", page=3, doc="AAPL", **kw):
    return fig(value=value, units=units, doc_id=doc, page=page, quote=quote, **kw)


class Numbers(unittest.TestCase):
    def test_formats(self):
        e = extract_numbers
        self.assertEqual(e("1,234.5"), [(1234.5, "")])
        self.assertEqual(e("(1,234)"), [(-1234.0, "")])
        self.assertEqual(e("$12.3bn"), [(12.3e9, "USD")])
        self.assertEqual(e("12.3 billion"), [(12.3e9, "")])
        self.assertEqual(e("45%"), [(45.0, "%")])
        self.assertEqual(e("€3.2m"), [(3.2e6, "EUR")])
        self.assertEqual(e("3.2x"), [(3.2, "x")])
        self.assertEqual(e("25 bps"), [(25.0, "bps")])

    def test_arabic_minus_thin_space(self):
        self.assertEqual(extract_numbers("٣٤٥٫٥")[0][0], 345.5)
        self.assertEqual(extract_numbers("١٬٢٣٤")[0][0], 1234.0)
        self.assertEqual(extract_numbers("−5.5")[0][0], -5.5)
        self.assertEqual(extract_numbers("1 234 567")[0][0], 1234.0)
        self.assertEqual(extract_numbers("1 234 567")[0][0], 1234567.0)

    def test_glued_and_dates(self):
        vals = [v for v, _ in extract_numbers("FY24 Q3 3 months")]
        self.assertEqual(vals, [3.0])
        self.assertEqual(extract_numbers("-$1,234")[0], (-1234.0, "USD"))
        self.assertEqual(extract_numbers(None), [])


class Methods(unittest.TestCase):
    def test_xbrl_pass_and_fail(self):
        f = fig(xbrl_concept="us-gaap:Revenues")
        self.assertEqual(verify_figure(f, resolver()), Verdict(True, mock.ANY, "xbrl"))
        bad = fig(value=400000.0, xbrl_concept="us-gaap:Revenues")
        v = verify_figure(bad, resolver())
        self.assertFalse(v.ok)
        self.assertEqual(v.method, "xbrl")

    def test_xbrl_scale_trap(self):
        v = verify_figure(fig(units="USD bn", xbrl_concept="us-gaap:Revenues"), resolver())  # 391035 bn
        self.assertFalse(v.ok)
        v2 = verify_figure(fig(value=391.035, units="USD bn", xbrl_concept="us-gaap:Revenues"), resolver())
        self.assertTrue(v2.ok)

    def test_xbrl_missing(self):
        v = verify_figure(fig(xbrl_concept="us-gaap:Assets"), resolver())
        self.assertFalse(v.ok)
        self.assertIn("unavailable", v.reason)

    def test_page_text_pass(self):
        v = verify_figure(qfig("Total net sales 391,035"), resolver())
        self.assertTrue(v.ok, v.reason)
        self.assertEqual(v.method, "page_text")

    def test_quote_whitespace_normalised(self):
        v = verify_figure(qfig("Total  net\nsales   391,035"), resolver())
        self.assertTrue(v.ok, v.reason)

    def test_quote_on_other_page(self):
        v = verify_figure(qfig("Total net sales 391,035", page=4), resolver())
        self.assertFalse(v.ok)
        self.assertIn("not found", v.reason)

    def test_quote_tampered(self):
        v = verify_figure(qfig("Total net sales 391,036"), resolver())
        self.assertFalse(v.ok)

    def test_quote_present_number_differs(self):
        v = verify_figure(qfig("Total net sales 391,035", value=500000.0), resolver())
        self.assertFalse(v.ok)

    def test_negative_parentheses(self):
        self.assertTrue(verify_figure(qfig("Operating loss (1,234)", value=-1234.0), resolver()).ok)
        self.assertFalse(verify_figure(qfig("Operating loss (1,234)", value=1234.0), resolver()).ok)

    def test_percentage_vs_bps(self):
        q = qfig("Gross margin percentage 46.2 %", value=46.2, units="%")
        self.assertTrue(verify_figure(q, resolver()).ok)
        trap = qfig("Gross margin percentage 46.2 %", value=46.2, units="bps")
        v = verify_figure(trap, resolver())
        self.assertFalse(v.ok)
        self.assertIn("unit", v.reason)

    def test_thousands_vs_millions_trap(self):
        ok = fig(doc_id="TH", page=1, quote="Revenue 1,234", value=1234.0, units="USD k")
        self.assertTrue(verify_figure(ok, resolver()).ok)
        bad = fig(doc_id="TH", page=1, quote="Revenue 1,234", value=1234.0, units="USD m")
        v = verify_figure(bad, resolver())
        self.assertFalse(v.ok)
        self.assertIn("scale", v.reason)

    def test_bn_vs_m(self):
        r = resolver()
        r.add_page("AAPL", 9, "Revenue of $12.3bn")
        self.assertTrue(verify_figure(qfig("Revenue of $12.3bn", value=12300.0, page=9), r).ok)
        self.assertFalse(verify_figure(qfig("Revenue of $12.3bn", value=12.3, page=9), r).ok)

    def test_conflicting_units(self):
        v = verify_figure(fig(units="USD m bn", xbrl_concept="us-gaap:Revenues"), resolver())
        self.assertFalse(v.ok)
        self.assertIn("ambiguity", v.reason)

    def test_url_snapshot(self):
        f = fig(value=391.0, units="USD bn", url="https://example.com/x", quote="Revenue was $391.0 billion")
        v = verify_figure(f, resolver())
        self.assertTrue(v.ok, v.reason)
        self.assertEqual(v.method, "quote")
        missing = fig(value=391.0, units="USD bn", url="https://example.com/none", quote="Revenue was $391.0 billion")
        self.assertIn("unavailable", verify_figure(missing, resolver()).reason)

    def test_cell(self):
        f = fig(doc_id="model.xlsx", cell_locator="IS!B5")
        self.assertEqual(verify_figure(f, resolver()).method, "cell")
        self.assertTrue(verify_figure(f, resolver()).ok)
        self.assertFalse(verify_figure(fig(value=1.0, doc_id="model.xlsx", cell_locator="IS!B5"), resolver()).ok)
        self.assertFalse(verify_figure(fig(doc_id="model.xlsx", cell_locator="IS!Z9"), resolver()).ok)

    def test_no_method(self):
        v = verify_figure(fig(url="https://example.com/x"), resolver())
        self.assertEqual((v.ok, v.method), (False, "none"))


class Gates(unittest.TestCase):
    def test_future_as_of(self):
        f = fig(xbrl_concept="us-gaap:Revenues", as_of="2999-01-01", period="FY2999")
        v = verify_figure(f, resolver())
        self.assertFalse(v.ok)
        self.assertIn("future", v.reason)

    def test_period_mismatch(self):
        v = verify_figure(fig(xbrl_concept="us-gaap:Revenues", period="FY2019"), resolver())
        self.assertFalse(v.ok)
        self.assertIn("period mismatch", v.reason)

    def test_unparseable_period(self):
        v = verify_figure(fig(xbrl_concept="us-gaap:Revenues", period="LTM"), resolver())
        self.assertFalse(v.ok)

    def test_bad_as_of_date(self):
        f = fig(xbrl_concept="us-gaap:Revenues")
        f.citation.as_of = "2024-13-45"
        self.assertIn("real date", verify_figure(f, resolver()).reason)


class Derived(unittest.TestCase):
    def pool(self, rev_value=391035.0):
        r_ = fig(label="Net sales", value=rev_value, doc_id="AAPL", page=3, quote="Total net sales 391,035")
        g_ = fig(label="Gross profit", value=180683.0, doc_id="AAPL", page=5, quote="Gross margin 180,683")
        return r_, g_

    def res(self):
        r = resolver()
        r.add_page("AAPL", 5, "(in millions) Gross margin 180,683")
        return r

    def ratio(self):
        return fig(label="Gross margin = {Gross profit} / {Net sales}", value=46.2, units="%",
                   doc_id="AAPL", page=3, quote="x")

    def test_derived_pass(self):
        r_, g_ = self.pool()
        d = self.ratio()
        v = verify_figure(d, self.res(), figures=[r_, g_, d])
        self.assertTrue(v.ok, v.reason)
        self.assertEqual(v.method, "derived")

    def test_derived_wrong_value(self):
        r_, g_ = self.pool()
        d = self.ratio()
        d.value = 60.0
        self.assertFalse(verify_figure(d, self.res(), figures=[r_, g_, d]).ok)

    def test_derived_with_unverified_input(self):
        r_, g_ = self.pool()
        g_.citation.quote = "Gross margin 180,684"
        d = self.ratio()
        v = verify_figure(d, self.res(), figures=[r_, g_, d])
        self.assertFalse(v.ok)
        self.assertIn("unverified", v.reason)

    def test_derived_missing_input(self):
        r_, _ = self.pool()
        d = self.ratio()
        self.assertIn("not found", verify_figure(d, self.res(), figures=[r_, d]).reason)

    def test_derived_div_zero(self):
        z = fig(label="Zero", value=0.0, doc_id="AAPL", page=3, quote="Total net sales 391,035")
        d = fig(label="Ratio = {Net sales} / {Zero}", value=1.0, units="x", doc_id="AAPL", page=3, quote="x")
        r_, _ = self.pool()
        v = verify_figure(d, self.res(), figures=[r_, z, d])
        self.assertFalse(v.ok)


def _result(figures=(), slides=(), excel=(), rejected=()):
    return ResearchResult(job_id="j1", status="succeeded", evidence_head="0" * 64, figures=list(figures),
                          slide_specs=list(slides), excel_inputs=list(excel), rejected=list(rejected))


def _slide(**kw):
    d = {"id": "s1", "layout": "bullets", "title": "Apple results", "bullets": [], "blocks": []}
    d.update(kw)
    return d


class ResultLevel(unittest.TestCase):
    def good(self):
        return fig(value=391035.0, doc_id="AAPL", page=3, quote="Total net sales 391,035")

    def test_conservation_and_reason(self):
        bad = qfig("Total net sales 391,036")
        res = _result([self.good(), bad], rejected=[{"figure": {"x": 1}, "reason": "pre"}])
        out = verify_result(res, resolver())
        self.assertEqual(len(out.figures) + len(out.rejected), 3)
        self.assertEqual(len(out.figures), 1)
        last = out.rejected[-1]
        last = last if isinstance(last, dict) else last.to_dict()
        self.assertTrue(last["reason"].startswith("[page_text]"), last)
        self.assertEqual(len(res.figures), 2)    # input untouched

    def test_deterministic(self):
        res = _result([self.good(), qfig("zzz")])
        a, b = verify_result(res, resolver()), verify_result(res, resolver())
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_slide_with_verified_number_kept(self):
        g = self.good()
        s = _slide(bullets=["Revenue of $391.0bn in 2024"], blocks=[{"type": "kpi", "label": "Revenue", "value": "391,035"}])
        g.label = "Revenue"
        out = verify_result(_result([g], [s]), resolver())
        self.assertEqual(len(out.slide_specs), 1, out.rejected)

    def test_slide_with_unverified_number_rejected(self):
        g = self.good()
        g.label = "Revenue"
        s = _slide(bullets=["Revenue of $391.0bn", "Margin expanded to 52.5%"])
        out = verify_result(_result([g], [s]), resolver())
        self.assertEqual(out.slide_specs, [])
        r = out.rejected[-1]
        r = r if isinstance(r, dict) else r.to_dict()
        self.assertEqual(r["figure"]["id"], "s1")
        self.assertIn("52.5", r["reason"])

    def test_slide_number_matching_rejected_figure_rejected(self):
        bad = qfig("Total net sales 999")
        bad.label = "Revenue"
        out = verify_result(_result([bad], [_slide(bullets=["Revenue of $391bn"])]), resolver())
        self.assertEqual(out.slide_specs, [])

    def test_slide_wrong_label_rejected(self):
        g = self.good()
        g.label = "Revenue"
        out = verify_result(_result([g], [_slide(bullets=["Debt of $391bn"])]), resolver())
        self.assertEqual(out.slide_specs, [])

    def test_slide_years_and_small_enums_exempt(self):
        out = verify_result(_result([], [_slide(bullets=["3 key drivers in 2024 (FY24, Q3)"])]), resolver())
        self.assertEqual(len(out.slide_specs), 1)

    def test_excel_payload(self):
        ok = ExcelInputPayload("dcf", "AAPL", {"revenue": self.good()})
        bad = ExcelInputPayload("dcf", "AAPL", {"revenue": qfig("nope")})
        out = verify_result(_result([], excel=[ok, bad]), resolver())
        self.assertEqual(len(out.excel_inputs), 1)
        self.assertEqual(len(out.rejected), 1)


class NoNetwork(unittest.TestCase):
    def test_no_socket(self):
        def boom(*a, **k):
            raise AssertionError("network access attempted")
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom):
            self.assertTrue(verify_figure(qfig("Total net sales 391,035"), resolver()).ok)
            verify_result(_result([qfig("Total net sales 391,035")], [_slide(bullets=["x 5%"])]), resolver())
            # default resolver, nothing registered: unavailable, still no network
            self.assertFalse(verify_figure(qfig("Total net sales 391,035"), SourceResolver()).ok)


if __name__ == "__main__":
    unittest.main()
