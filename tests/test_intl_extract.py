"""S8.3b: extraction on the synthetic fixtures (manifest ground truth). OCR results are cached per fixture."""
import json
import os
import re
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
os.environ.setdefault("ACRETIA_TELEMETRY_PATH", "off")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from om.intl import extract as ex_mod, numparse, tables  # noqa: E402
from om.intl.tieout import check  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "intl"
MANIFEST = json.load(open(FX / "manifest.json", encoding="utf-8"))["fixtures"]
_CACHE = {}
TIMES = {}


def entry(name):
    return next(e for e in MANIFEST if e["file"] == name)


def extracted(name):
    """(ExtractedStatements, seconds). A scanned report whose period headers the OCR cannot read gets the period hint."""
    if name not in _CACHE:
        e = entry(name)
        t = time.time()
        try:
            ex, _ = ex_mod._extract(str(FX / name))
        except ex_mod.ExtractError:
            ex, _ = ex_mod._extract(str(FX / name), hints={"period_end": e["periods"][-1]})
        TIMES[name] = time.time() - t
        _CACHE[name] = ex
    return _CACHE[name]


def classify(name):
    e, ex = entry(name), extracted(name)
    tol = 0.5 * e["unit_scale"] / 1e6 + 1e-9
    out = []
    for g in e["ground_truth"]:
        cands = [f for f in ex.figures if f.key == g["key"] and f.period_end.isoformat() == g["period_end"]]
        c = next((f for f in cands if f.page == g["page"]), cands[0] if cands else None)
        if c is None:
            out.append(("missing", g, None))
        elif abs(c.value - g["value"]) <= tol:
            out.append(("ok" if c.status == "ok" else "review", g, c))
        else:
            out.append(("review" if c.status == "review" else "wrong", g, c))
    return out


class Fixtures(unittest.TestCase):
    def _check(self, name, need):
        cl = classify(name)
        wrong = [(g["key"], g["period_end"], g["value"], f.value) for s, g, f in cl if s == "wrong"]
        missing = [(g["key"], g["period_end"]) for s, g, f in cl if s == "missing"]
        self.assertEqual(wrong, [], "released wrong figures")
        self.assertEqual(missing, [], "ground truth neither extracted nor in review")
        cov = sum(1 for s, *_ in cl if s == "ok") / len(cl)
        print(f"\n  {name}: coverage {cov:.3f} ({len(cl)} gt), wrong 0, {TIMES.get(name, 0):.1f}s", file=sys.stderr)
        self.assertGreaterEqual(cov, need)

    def test_native_fixtures(self):
        for e in MANIFEST:
            if e["kind"] == "native":
                with self.subTest(e["file"]):
                    self._check(e["file"], 0.95)

    def test_scanned_fixtures(self):
        for e in MANIFEST:
            if e["kind"] == "scanned":
                with self.subTest(e["file"]):
                    self._check(e["file"], 0.85)

    def test_metadata_and_native_bbox_text(self):
        for e in MANIFEST:
            ex = extracted(e["file"])
            self.assertEqual(ex.currency, e["currency"], e["file"])
            self.assertEqual(ex.unit_scale, e["unit_scale"], e["file"])
            self.assertEqual(ex.fiscal_year_end_month, e["fiscal_year_end_month"], e["file"])
            self.assertEqual([p.isoformat() for p in ex.periods], e["periods"], e["file"])
            for f in ex.figures:
                x0, y0, x1, y1 = f.bbox_norm
                self.assertTrue(0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1, (e["file"], f.raw, f.bbox_norm))
                self.assertTrue(0 <= f.confidence <= 1)
                self.assertTrue(1 <= f.page <= e["pages"])
                self.assertEqual(len(f.sha256_span_hash), 64)
                self.assertEqual(f.doc_id, ex.doc_id)

    def test_native_raw_matches_pdf_words(self):
        from om import pdfdoc
        for e in [x for x in MANIFEST if x["kind"] == "native"]:
            doc = pdfdoc.load(str(FX / e["file"]), ocr=False)
            ex = extracted(e["file"])
            for f in ex.figures:
                if f.source != "native":
                    continue
                pg = doc.pages[f.page - 1]
                inside = [w.text for w in pg.words if f.bbox_norm[0] - 1e-3 <= (w.bbox_norm[0] + w.bbox_norm[2]) / 2 <= f.bbox_norm[2] + 1e-3
                          and f.bbox_norm[1] - 1e-3 <= (w.bbox_norm[1] + w.bbox_norm[3]) / 2 <= f.bbox_norm[3] + 1e-3]
                norm = lambda s: re.sub(r"\s", "", numparse.normalise_digits(s))
                self.assertIn(norm(f.raw), [norm(t) for t in inside] + [norm("".join(inside))], (e["file"], f.raw, inside))

    def test_signs_and_by_nature_ebit(self):
        ex = extracted("red_sea_cement_en_native_fy2024.pdf")
        get = lambda k, p="2024-12-31": next(f for f in ex.figures if f.key == k and f.period_end.isoformat() == p)
        self.assertAlmostEqual(get("x.raw_materials").value, 2509.7)
        self.assertIn("sign:deduction", get("x.raw_materials").reasons)
        self.assertAlmostEqual(get("x.zakat").value, 42.8)
        self.assertAlmostEqual(get("cfi").value, -379.8)
        self.assertAlmostEqual(get("capex").value, 379.8)
        eb = get("ebit")
        self.assertEqual(eb.source, "derived")
        self.assertIn("basis:computed_by_nature", eb.reasons)
        self.assertAlmostEqual(eb.value, 5886.9 + 64.1 - 2509.7 - 602.9 - 200.9 - 467.5, places=6)
        self.assertTrue(eb.components)
        self.assertEqual(eb.confidence, min(ex.figures[i].confidence for i in eb.components))

    def test_clean_fixtures_tie(self):
        for e in MANIFEST:
            rep = check(extracted(e["file"]))
            self.assertTrue(rep.passed, (e["file"], [t.name for t in rep.failed]))


class Units(unittest.TestCase):
    def test_fix_word_text_arabic_visual_order(self):
        self.assertEqual(tables.fix_word_text("ﺔﻳﺬﻏﻸﻟ", True), "للأغذية")
        self.assertEqual(tables.fix_word_text("يداو", True), "وادي")
        self.assertEqual(tables.fix_word_text("4,207,558", True), "4,207,558")

    def test_label_resolution(self):
        k = ex_mod.resolve_label("Depreciation and amortisation", "", "IS")
        self.assertEqual(k[0], "x.depreciation")
        k = ex_mod.resolve_label("", "العملاء والمدينون الآخرون", "BS")
        self.assertEqual(k[0], "ar")

    def test_no_statements_raises(self):
        with self.assertRaises(Exception):
            ex_mod.extract(b"%PDF-1.4 not really")


if __name__ == "__main__":
    unittest.main()
