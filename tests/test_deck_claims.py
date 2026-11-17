"""R2-d: deterministic claim check between a slide's title and its own evidence. Offline, no model calls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om.deck import claims  # noqa: E402
from om.deck.model import Element, Para, Run, SolvedSlide, TextSpec  # noqa: E402


def _t(id_, role, *paras):
    return Element(f"s1.{role}.{id_}", "text", role, 0, 0, 1, 1, text=TextSpec([Para([Run(p)]) for p in paras], 12))


def _tbl(cols, rows):
    return Element("s1.table", "table", "table", 0, 0, 1, 1, table={"columns": cols, "rows": rows})


def _chart(kind, vals, name="Revenue"):
    return Element("s1.chart", "chart", "chart", 0, 0, 1, 1,
                   chart={"type": kind, "categories": [f"c{i}" for i in range(len(vals))],
                          "series": [{"name": name, "values": vals}]})


def slide(title, *els, idx=1):
    return SolvedSlide(idx, "x", [Element("s1.title", "text", "title", 0, 0, 1, 1, text=TextSpec([Para([Run(title)])], 12)), *els])


def rules(*slides):
    return [f["rule"] for f in claims.check({}, list(slides))]


class Basis(unittest.TestCase):
    def test_reviewer_case_revenue_title_ebitda_cards(self):
        s = slide("EV / forward revenue of 6.8x to 9.1x frames the range",
                  _t("c1", "kpi", "11.2x EBITDA"), _t("c2", "kpi", "9.4x EBITDA"), _t("c3", "kpi", "12.0x EBITDA"))
        out = claims.check({}, [s])
        self.assertEqual([f["rule"] for f in out], ["claim_basis", "claim_basis"])
        self.assertTrue(all(f["severity"] == "major" and f["slide"] == 1 for f in out))

    def test_matching_basis_passes(self):
        s = slide("EV / forward revenue of 6.8x to 9.1x frames the range",
                  _t("c1", "kpi", "6.8x revenue"), _t("c2", "kpi", "9.1x revenue"))
        self.assertEqual(rules(s), [])

    def test_basis_from_table_header(self):
        ok = slide("Peers trade at 7.3x ARR", _tbl(["Company", "EV/ARR"], [["A", "7.3x"], ["B", "6.1x"]]))
        bad = slide("Peers trade at 7.3x ARR", _tbl(["Company", "EV/EBITDA"], [["A", "7.3x"], ["B", "6.1x"]]))
        self.assertEqual(rules(ok), [])
        self.assertEqual(rules(bad), ["claim_basis"])

    def test_percent_basis_irr_vs_margin(self):
        bad = slide("The deal returns a 25% IRR", _t("b", "body", "Operating margin 25%"), _t("b2", "body", "EBITDA margin 22%"))
        self.assertEqual(rules(bad), ["claim_basis"])
        self.assertEqual(rules(slide("The deal returns a 25% IRR", _t("b", "body", "Base case IRR 25%"))), [])

    def test_arabic_basis_and_digits(self):
        bad = slide("مضاعف 6.8x من الإيرادات", _t("c", "kpi", "11.2x EBITDA"))
        self.assertEqual(rules(bad), ["claim_basis"])
        ok = slide("مضاعف ٦٫٨x من الإيرادات", _t("c", "kpi", "6.8x الإيرادات"))
        self.assertEqual(rules(ok), [])


class Unsupported(unittest.TestCase):
    def test_reviewer_case_21x_vs_arr_7_3x(self):
        s = slide("The offer implies 21.0x", _t("b", "body", "EV/ARR 7.3x"), _t("b2", "body", "Premium 31%"))
        out = claims.check({}, [s])
        self.assertEqual([f["rule"] for f in out], ["claim_unsupported"])
        self.assertEqual(out[0]["severity"], "major")
        self.assertIn("21.0x", out[0]["message"])

    def test_value_present_in_chart_or_table_or_formats_vary(self):
        self.assertEqual(rules(slide("Revenue reached $4.7bn", _chart("column", [3.9, 4.2, 4.7]))), [])
        self.assertEqual(rules(slide("Revenue reached $4,700m", _t("b", "body", "FY25 revenue $4.7bn"))), [])
        self.assertEqual(rules(slide("Margin held at 31%", _tbl(["Y", "Margin"], [["FY25", "31%"]]))), [])

    def test_negative_value_missing(self):
        self.assertEqual(rules(slide("Margin held at 31%", _t("b", "body", "Margin 29%"))), ["claim_unsupported"])

    def test_year_and_plain_numbers_ignored(self):
        self.assertEqual(rules(slide("Four drivers explain the 2026 gain", _t("b", "body", "Pricing"))), [])


class Mixed(unittest.TestCase):
    def test_m_and_bn_in_a_list(self):
        s = slide("Sources and uses", _t("l", "body", "$567m equity", "$1.2bn debt", "$118m fees"))
        self.assertEqual(rules(s), ["mixed_units"])
        self.assertEqual(rules(slide("Sources and uses", _t("l", "body", "$567m equity", "$1,200m debt", "$118m fees"))), [])

    def test_percent_and_x_in_a_table_column(self):
        t = _tbl(["Metric", "FY25", "FY26"], [["A", "21%", "3.1x"], ["B", "22%", "25%"], ["C", "9%", "12%"]])
        self.assertEqual(rules(slide("Table", t)), ["mixed_units"])

    def test_metric_per_row_matrix_is_fine(self):
        t = _tbl(["KPI", "Q1", "Q2", "Q3"], [["Rev", "$4m", "$5m", "$6m"], ["Margin", "21%", "22%", "23%"], ["Lev", "2.9x", "2.8x", "2.6x"]])
        self.assertEqual(rules(slide("Table", t)), [])

    def test_kpi_row_percent_and_x_is_not_a_list(self):
        s = slide("Unit economics", _t("k1", "kpi", "$2.4bn"), _t("k2", "kpi", "21.4%"), _t("k3", "kpi", "3.1x"))
        self.assertEqual(rules(s), [])

    def test_kpi_m_and_bn(self):
        s = slide("Drivers", _t("k1", "kpi", "$2.4bn"), _t("k2", "kpi", "$38m"))
        self.assertEqual(rules(s), ["mixed_units"])


class Labels(unittest.TestCase):
    def test_output_label_repeated(self):
        s = slide("Plan", _t("a", "body", "Output: Day 0: legal entity"), _t("b", "body", "Output: Day 30: TSA"),
                  _t("c", "body", "Output: Day 60: ERP"))
        out = claims.check({}, [s])
        self.assertEqual([(f["rule"], f["severity"]) for f in out], [("repeated_label", "minor")])

    def test_two_uses_or_varied_labels_pass(self):
        self.assertEqual(rules(slide("Plan", _t("a", "body", "Output: x"), _t("b", "body", "Output: y"))), [])
        self.assertEqual(rules(slide("Plan", _t("a", "body", "Owner: x"), _t("b", "body", "Date: y"), _t("c", "body", "Risk: z"))), [])


class Direction(unittest.TestCase):
    def test_grows_vs_falling_series(self):
        s = slide("Revenue grows steadily", _chart("line", [5.0, 4.6, 4.1]))
        out = claims.check({}, [s])
        self.assertEqual([(f["rule"], f["severity"]) for f in out], [("claim_direction", "major")])

    def test_grows_with_rising_series_passes(self):
        self.assertEqual(rules(slide("Revenue grows steadily", _chart("line", [4.1, 4.6, 5.0]))), [])

    def test_falls_vs_rising_series(self):
        self.assertEqual(rules(slide("Costs fall every year", _chart("column", [1.0, 2.0, 3.0]))), ["claim_direction"])

    def test_mixed_verbs_or_waterfall_not_judged(self):
        self.assertEqual(rules(slide("Revenue grows then falls", _chart("line", [5.0, 4.6, 4.1]))), [])
        self.assertEqual(rules(slide("Revenue grows", _chart("waterfall", [5.0, -2.0, 3.0]))), [])

    def test_arabic_verbs(self):
        self.assertEqual(rules(slide("ينمو الربح", _chart("line", [5.0, 4.0]))), ["claim_direction"])
        self.assertEqual(rules(slide("تنخفض التكاليف", _chart("line", [5.0, 4.0]))), [])


class RealDeckSlides(unittest.TestCase):
    def test_registry_examples_do_not_raise_major_claims_except_known(self):
        import copy
        from om.deck import archetypes, engine
        majors = {}
        for aid, ex in sorted(archetypes.examples().items()):
            sl = {"id": "e1", "archetype": aid, "blocks": {}, "title": "Example", **copy.deepcopy(ex)}
            d = {"deck_id": "x", "title": "T", "lang": "en", "as_of": "2026-09-30", "slides": [sl]}
            r = engine.build(d, return_slides=True, _stop_before_render=True, critic=False)
            f = [x for x in claims.check(d, r.solved or []) if x["severity"] == "major"]
            if f:
                majors[aid] = [x["rule"] for x in f]
        self.assertLessEqual(len(majors), 1, majors)


if __name__ == "__main__":
    unittest.main()
