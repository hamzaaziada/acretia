"""S8.4: tie-out, confidence gate, release and the review queue. Synthetic, hand-built extracts; no network."""
import copy
import io
import json
import os
import tempfile
import unittest
from datetime import date

from om import model3
from om import statements as stm
from om.intl import review, tieout
from om.intl.types import ExtractedStatements, Figure, IntlItem, IntlStatements
from om.pdfdoc import span_hash
from om.xlsx import read
from tests.test_model3 import synthetic_companyfacts

DOC = "ab" * 32
P0, P1 = date(2023, 12, 31), date(2024, 12, 31)
UNIT = 1e3                      # printed in thousands: 1 unit = 0.001 m


def transpose(v):
    s = f"{v:.3f}"
    for i in range(len(s) - 1):
        if s[i].isdigit() and s[i + 1].isdigit() and s[i] != s[i + 1]:
            return float(s[:i] + s[i + 1] + s[i] + s[i + 2:])
    raise AssertionError(v)


def make(company="Testco", periods=(P0, P1), unit=UNIT) -> ExtractedStatements:
    """Two consistent periods (IS, BS, CF) from the synthetic filer, rounded to the printed unit."""
    s = stm.build(synthetic_companyfacts(), "T")
    yrs = {e.year: i for i, e in enumerate(s.years)}
    figs: list[Figure] = []
    row = [0]

    def put(key, p, value, stmt, label=None, total=False, comps=None, conf=0.97):
        i = len(figs)
        r = row[0] = row[0] + 1
        bbox = (0.70, 0.02 + 0.012 * r, 0.80, 0.03 + 0.012 * r)
        raw = f"{value:,.3f}"
        figs.append(Figure(key=key, label=label or key or "other", value=round(value, 3), raw=raw, scale=unit, period_end=p,
                           period_start=None, statement=stmt, page=1 + r // 40, bbox_norm=bbox, label_bbox=None,
                           confidence=conf, ocr_conf=None, source="native", doc_id=DOC,
                           sha256_span_hash=span_hash(1, raw, bbox), row=r, is_total=total, components=comps))
        return i

    for p in periods:
        i = yrs[p.year]
        g = lambda k: s.get(k, i)
        for k in ("revenue", "cogs", "gross_profit", "ebit", "pretax", "tax", "net_income"):
            put(k, p, g(k), "IS")
        # balance sheet: current assets is a printed total of cash + receivables + inventory + other
        c, a, v = (put("cash", p, g("cash"), "BS"), put("ar", p, g("ar"), "BS"), put("inventory", p, g("inventory"), "BS"))
        o = put(None, p, g("current_assets") - g("cash") - g("ar") - g("inventory"), "BS", label="Other current assets")
        put("current_assets", p, g("current_assets"), "BS", total=True, comps=[c, a, v, o])
        for k in ("assets", "current_liabilities", "liabilities", "liabilities_equity"):
            put(k, p, g(k), "BS")
        for k in ("cf_net_income", "cfo", "cfi", "cff", "net_change_cash"):
            put(k, p, g("net_income") if k == "cf_net_income" else g(k), "CF")
        put("x.cash_beginning", p, g("cash") - g("net_change_cash"), "CF")
        put("x.cash_end", p, g("cash"), "CF")
    return ExtractedStatements(doc_id=DOC, company=company, currency="EGP", unit_scale=unit, periods=list(periods), figures=figs,
                               standard="IFRS", language="en", fiscal_year_end_month=12, source_url="https://example.com/ar.pdf")


def fig(ex, key, p=P1):
    return next(f for f in ex.figures if f.key == key and f.period_end == p)


class CleanTests(unittest.TestCase):
    def test_clean_extract_passes_and_releases(self):
        ex = make()
        rep = tieout.check(ex)
        self.assertTrue(rep.passed, [(t.name, t.period, t.diff) for t in rep.failed])
        self.assertGreaterEqual(len(rep.ties), 14)
        self.assertEqual(rep.review, {})
        s = tieout.release(ex, rep)
        self.assertIsInstance(s, IntlStatements)
        self.assertIsInstance(s.data["revenue"][0], IntlItem)
        self.assertEqual(s.years, [P0, P1])
        self.assertAlmostEqual(s.get("revenue", 1), fig(ex, "revenue").value)
        self.assertIsNone(s.get("rd", 1))
        self.assertEqual(set(s.data), set(stm.LINES))
        self.assertEqual(s.filings[0], {"end": "2023-12-31", "filed": "", "form": "IFRS annual report", "accn": DOC[:12], "url": "https://example.com/ar.pdf"})
        self.assertTrue(s.release_report.passed)
        it = s.data["revenue"][1]
        self.assertEqual(it.citation.doc_id, DOC)
        self.assertEqual(it.citation.page, fig(ex, "revenue").page)
        self.assertEqual(it.citation.quote, fig(ex, "revenue").raw)
        self.assertTrue(it.source().startswith("p.1 bbox ") and DOC[:12] in it.source() and "conf 0.97" in it.source())
        self.assertEqual(s.data["rd"][0].source(), "")

    def test_model3_builds_from_released_statements_and_balances(self):
        s = tieout.release(make())
        wb, meta = model3.build_workbook(s)
        b = read(wb.to_bytes())
        r = meta["rows"]["BS"]["bal"]
        for p in range(len(s.years) + model3.F):
            self.assertAlmostEqual(b.sheets["BS"][(r, model3.C0 + p)].value, 0.0, places=3)
        self.assertIsInstance(model3.build(s)[0], bytes)

    def test_tolerance_scales_with_printed_unit(self):
        ex = make()
        fig(ex, "net_change_cash").value += 0.001            # 1 unit of rounding
        self.assertTrue(tieout.check(ex).passed)
        ex = make()
        fig(ex, "net_change_cash").value += 0.003            # beyond
        self.assertFalse(tieout.check(ex).passed)
        ex = make(unit=1e6)                                    # printed in millions: 0.5 per term
        fig(ex, "net_change_cash").value += 1.0
        self.assertTrue(tieout.check(ex).passed)

    def test_cf_from_pretax_ties_pretax(self):
        ex = make()
        for p in (P0, P1):
            fig(ex, "cf_net_income", p).value = fig(ex, "pretax", p).value
        rep = tieout.check(ex)
        self.assertTrue(rep.passed, [(t.name, t.diff) for t in rep.failed])
        self.assertIn("cf_start(pretax)=pretax", {t.name for t in rep.ties})

    def test_zakat_and_nci_enter_the_profit_ties(self):
        ex = make()
        z = copy.copy(fig(ex, "tax"))
        z.key, z.value, z.label = "x.zakat", 2.0, "Zakat"
        ex.figures.append(z)
        fig(ex, "net_income").value -= 2.0
        fig(ex, "cf_net_income").value -= 2.0
        self.assertTrue(tieout.check(ex).passed)


class MutationTests(unittest.TestCase):
    MUTATIONS = [
        ("transpose revenue", "revenue", lambda v: transpose(v)),
        ("flip cogs sign", "cogs", lambda v: -v),
        ("gross profit +3 units", "gross_profit", lambda v: v + 0.003),
        ("assets -3 units", "assets", lambda v: v - 0.003),
        ("transpose total L&E", "liabilities_equity", lambda v: transpose(v)),
        ("flip cfo sign", "cfo", lambda v: -v),
        ("net change in cash +3 units", "net_change_cash", lambda v: v + 0.003),
        ("closing cash +0.01", "x.cash_end", lambda v: v + 0.01),
        ("transpose net income", "net_income", lambda v: transpose(v)),
        ("flip tax sign", "tax", lambda v: -v),
        ("pretax -3 units", "pretax", lambda v: v - 0.003),
        ("drop receivables from current assets", "ar", lambda v: 0.0),
        ("flip cf net income", "cf_net_income", lambda v: -v),
        ("current assets +3 units", "current_assets", lambda v: v + 0.003),
        ("cfi transposed", "cfi", lambda v: transpose(v)),
    ]

    def test_every_mutation_fails_routes_to_review_and_blocks_release(self):
        self.assertGreaterEqual(len(self.MUTATIONS), 10)
        for name, key, fn in self.MUTATIONS:
            with self.subTest(name):
                ex = make()
                f = fig(ex, key)
                f.value = fn(f.value)
                rep = tieout.check(ex)
                self.assertFalse(rep.passed)
                self.assertEqual(f.status, "review")
                self.assertTrue(any(r.startswith("tie-failed:") for r in f.reasons))
                self.assertIn(f, [it.figure for it in review.queue(ex, rep)])
                with self.assertRaises(tieout.ReleaseBlocked) as cm:
                    tieout.release(ex, rep)
                self.assertIs(cm.exception.report, rep)
                self.assertIn(f, cm.exception.review_items)

    def test_dropped_component_figure_fails_the_sum(self):
        ex = make()
        fig(ex, "current_assets").components = fig(ex, "current_assets").components[:-1]
        rep = tieout.check(ex)
        self.assertFalse(rep.passed)
        self.assertTrue(any(t.name == "sum:current_assets" and not t.passed for t in rep.ties))

    def test_non_strict_release_blanks_review_figures(self):
        ex = make()
        f = fig(ex, "revenue")
        f.value = transpose(f.value)
        s = tieout.release(ex, strict=False)
        self.assertIsNone(s.get("revenue", 1))
        self.assertIsNotNone(s.get("revenue", 0))
        self.assertFalse(s.release_report.passed)
        self.assertIn(f, s.review)
        self.assertTrue(any(w.startswith("review: revenue") for w in s.warnings))
        self.assertTrue(s.data["revenue"][1].source().startswith("p."))     # review figure stays traceable


class ConfidenceTests(unittest.TestCase):
    def test_low_confidence_without_corroboration_goes_to_review(self):
        ex = make()
        for f in ex.figures:
            if f.key == "gross_profit":
                f.value = None                                             # revenue no longer in any tie
        f = fig(ex, "revenue")
        f.confidence = 0.55
        rep = tieout.check(ex)
        self.assertTrue(rep.passed)
        self.assertEqual(f.status, "review")
        self.assertTrue(any(r.startswith("low-confidence") for r in f.reasons))
        with self.assertRaises(tieout.ReleaseBlocked):
            tieout.release(ex, rep)
        s = tieout.release(ex, rep, strict=False)
        self.assertIsNone(s.get("revenue", 1))

    def test_low_confidence_corroborated_by_a_passing_tie_is_released(self):
        ex = make()
        f = fig(ex, "assets")
        f.confidence = 0.40
        rep = tieout.check(ex)
        self.assertEqual(f.status, "ok")
        self.assertGreaterEqual(f.confidence, 0.95)
        self.assertIn("tie-corroborated", f.reasons)
        s = tieout.release(ex, rep)
        self.assertGreaterEqual(s.data["assets"][1].confidence, 0.95)

    def test_low_confidence_in_a_failing_tie_stays_in_review(self):
        ex = make()
        f = fig(ex, "assets")
        f.confidence, f.value = 0.40, f.value + 1.0
        tieout.check(ex)
        self.assertEqual(f.status, "review")
        self.assertNotIn("tie-corroborated", f.reasons)

    def test_unrequired_low_confidence_figure_does_not_block(self):
        ex = make()
        f = copy.copy(fig(ex, "revenue"))
        f.key, f.confidence = "x.employee_costs", 0.3
        ex.figures.append(f)
        rep = tieout.check(ex)
        self.assertEqual(f.status, "review")
        tieout.release(ex, rep)


class PriorTests(unittest.TestCase):
    def test_matching_prior_passes(self):
        rep = tieout.check(make(), prior=make(periods=(P0,)))
        self.assertTrue(rep.passed)
        self.assertTrue(any(t.name == "prior:revenue" for t in rep.ties))

    def test_prior_mismatch_goes_to_review(self):
        prior = make(periods=(P0,))
        fig(prior, "revenue", P0).value += 5.0
        ex = make()
        rep = tieout.check(ex, prior=prior)
        self.assertFalse(rep.passed)
        self.assertEqual(fig(ex, "revenue", P0).status, "review")
        self.assertEqual(fig(ex, "revenue", P1).status, "ok")
        with self.assertRaises(tieout.ReleaseBlocked):
            tieout.release(ex, rep)

    def test_restated_column_is_flagged_not_failed(self):
        prior = make(periods=(P0,))
        fig(prior, "revenue", P0).value += 5.0
        ex = make()
        ex.warnings.append("restated:2023-12-31")
        rep = tieout.check(ex, prior=prior)
        self.assertTrue(rep.passed)
        self.assertEqual(fig(ex, "revenue", P0).status, "ok")
        self.assertTrue(any("restated" in w for w in rep.warnings))
        self.assertTrue(any(t.restated for t in rep.ties))
        self.assertTrue(any("restated" in w for w in tieout.release(ex, rep).warnings))


class SoftTieTests(unittest.TestCase):
    def test_cf_cash_vs_bs_cash_is_a_warning_only(self):
        ex = make()
        for k in ("x.cash_beginning", "x.cash_end"):          # e.g. an overdraft: CF cash differs from BS cash
            fig(ex, k).value += 5.0
        rep = tieout.check(ex)
        self.assertTrue(rep.passed)
        soft = [t for t in rep.ties if t.name == "cf_cash_end=bs_cash"]
        self.assertTrue(any(not t.passed and not t.hard for t in soft))
        self.assertTrue(rep.warnings)
        self.assertEqual(rep.review, {})
        s = tieout.release(ex, rep)
        self.assertTrue(any("closing cash" in w for w in s.warnings))


class ReviewTests(unittest.TestCase):
    @staticmethod
    def tiny_pdf():
        from om.pdfwrite import PDFWriter
        w = PDFWriter(page_size=(300, 400))
        w.page()
        w.text(20, 300, "Revenue                 1,100.000")
        return w.to_bytes()

    def mutated(self):
        ex = make()
        f = fig(ex, "revenue")
        f.page, f.bbox_norm = 1, (0.55, 0.20, 0.95, 0.26)
        f.value = transpose(f.value)
        return ex, tieout.check(ex)

    def test_queue_without_pdf_has_no_crop(self):
        ex, rep = self.mutated()
        items = review.queue(ex, rep)
        self.assertTrue(items)
        self.assertTrue(all(it.crop_png is None and it.reasons and it.page >= 1 for it in items))

    def test_crop_is_a_valid_png_from_path_and_bytes(self):
        from PIL import Image
        ex, rep = self.mutated()
        pdf = self.tiny_pdf()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.pdf")
            with open(path, "wb") as fh:
                fh.write(pdf)
            for src in (path, pdf):
                items = review.queue(ex, rep, pdf=src)
                it = next(i for i in items if i.figure.key == "revenue")
                self.assertTrue(it.crop_png.startswith(b"\x89PNG\r\n\x1a\n"))
                im = Image.open(io.BytesIO(it.crop_png))
                self.assertGreater(im.size[0], 100)
                self.assertTrue(any(px[0] > 180 and px[1] < 90 for px in (lambda i: getattr(i, "get_flattened_data", i.getdata)())(im.convert("RGB"))), "highlight rectangle drawn")
            lines = review.to_jsonl(items, crop_dir=os.path.join(d, "crops"))
            rec = [json.loads(x) for x in lines.splitlines()]
            r = next(x for x in rec if x["key"] == "revenue")
            self.assertTrue(os.path.exists(r["crop_path"]))
            self.assertIn("tie-failed:revenue-cogs=gross_profit", r["reasons"])
        b64 = json.loads(review.to_jsonl(items).splitlines()[0])
        self.assertTrue("crop_png_b64" in b64 or "crop_path" in b64)

    def test_unrenderable_pdf_gives_no_crop_not_a_crash(self):
        ex, rep = self.mutated()
        self.assertTrue(all(it.crop_png is None for it in review.queue(ex, rep, pdf=b"not a pdf")))


class OnlyReleaseConstructsStatements(unittest.TestCase):
    def test_intl_statements_constructed_only_in_tieout(self):
        import ast
        import pathlib
        for p in pathlib.Path("om/intl").rglob("*.py"):
            for n in ast.walk(ast.parse(p.read_text())):
                if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "IntlStatements":
                    self.assertEqual(p.name, "tieout.py", p)


if __name__ == "__main__":
    unittest.main()
