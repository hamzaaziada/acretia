"""Template best-practice checks and .xlsx export validity."""
import io
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import templates as tp  # noqa: E402
from om.sheets import Sheets, to_xlsx  # noqa: E402
from om.search import Index  # noqa: E402

ALLOWED_LITERALS = {0.0, 0.5, 1.0, 100.0, 1_000_000.0}   # unit / convention constants only
NUM_IN_FORMULA = re.compile(r'"[^"]*"|\$?[A-Z]{1,2}\$?\d+|(?<![A-Z$])(\d+\.?\d*)')


def literals(formula: str) -> set[float]:
    formula = re.sub(r"(QUARTILE\([^,]+,)\s*[0-4]\)", r"\1q)", formula)   # the quartile number is a function argument
    return {float(m.group(1)) for m in NUM_IN_FORMULA.finditer(formula) if m.group(1)}


class TemplateTests(unittest.TestCase):
    def all_templates(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "deals.csv").write_text("target,acquirer,announced,n_filings,advisors,sources,ev_revenue_ltm,ev_ebitda_unspecified\n"
                                       "Alpha,Beta,2025-11,1,Bank One,https://sec/x,6.3,18.0\n"
                                       "Gamma,Delta,2024-03,2,Bank Two,https://sec/y,4.1,\n")
        return {"comps": tp.comps(["AAPL", "MSFT", "NVDA"]), "precedents": tp.precedents(tmp / "deals.csv"),
                "dcf": tp.dcf("AAPL"), "lbo": tp.lbo("AAPL")}

    def test_no_hardcoded_numbers_inside_formulas(self):
        for name, (cells, meta) in self.all_templates().items():
            for ref, v in cells.items():
                if isinstance(v, str) and v.startswith("="):
                    bad = literals(v) - ALLOWED_LITERALS
                    self.assertFalse(bad, f"{name}!{ref} hard-codes {bad} in {v}")

    def test_formulas_reference_only_populated_cells(self):
        for name, (cells, meta) in self.all_templates().items():
            for ref, v in cells.items():
                if not (isinstance(v, str) and v.startswith("=")):
                    continue
                body = re.sub(r'"[^"]*"', "", v)
                for a, b in re.findall(r"\$?([A-Z]{1,2})\$?(\d+)", body):
                    target = f"{a}{b}"
                    if ":" in body and re.search(rf"\$?{a}\$?{b}:|:\$?{a}\$?{b}", body):
                        continue  # range endpoints may be blank rows
                    self.assertIn(target, cells, f"{name}!{ref} references empty {target}: {v}")

    def test_dcf_structure(self):
        cells, meta = tp.dcf("AAPL")
        self.assertEqual(cells["J14"], "=J10*(1-J13)+J12*J13")                 # WACC from CAPM build
        self.assertIn("0.5*$C$13", cells["D28"])                                # mid-year switch
        self.assertIn("NPV(", cells["C52"])                                      # live sensitivity
        self.assertEqual(cells["E51"], "=$J$17")                                 # axis centred on base case
        self.assertEqual(meta["formats"]["J14"], "pct")

    def test_stats_rows_and_footnotes(self):
        cells, _ = tp.comps(["AAPL", "MSFT"])
        labels = [v for k, v in cells.items() if k.startswith("A") and v in ("Max", "75th percentile", "Mean", "Median", "25th percentile", "Min")]
        self.assertEqual(labels, ["Max", "75th percentile", "Mean", "Median", "25th percentile", "Min"])
        self.assertTrue(any(isinstance(v, str) and v.startswith("Source:") for v in cells.values()))


class XlsxTests(unittest.TestCase):
    def test_export_is_valid_and_keeps_formulas(self):
        cells = {"A1": "Revenue", "B1": "100", "B2": "=B1*2", "B3": '=OM("AAPL","revenue_ltm")', "B4": "=QUARTILE(B1:B2,1)", "C1": "x & <y>"}
        values = {"B2": 200, "B3": 478834.0, "B4": 125.0}
        z = zipfile.ZipFile(io.BytesIO(to_xlsx("My: sheet?", cells, values)))
        for part in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/worksheets/sheet1.xml"):
            ET.fromstring(z.read(part))                                       # every part is well-formed XML
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        c = {e.get("r"): e for e in sheet.iter(f"{{{ns['m']}}}c")}
        self.assertEqual(c["B2"].find("m:f", ns).text, "B1*2")               # plain formula kept
        self.assertIsNone(c["B3"].find("m:f", ns))                            # data function -> value
        self.assertEqual(c["B3"].find("m:v", ns).text, "478834.0")
        self.assertEqual(c["B4"].find("m:f", ns).text, "QUARTILE.INC(B1:B2,1)")
        self.assertIn("My- sheet-", z.read("xl/workbook.xml").decode())        # sheet name sanitised

    def test_sheet_storage_roundtrip(self):
        idx = Index(Path(tempfile.mkdtemp()) / "s.db")
        s = Sheets(idx.db)
        sid = s.create("DCF", {"A1": "x", "zz": "bad key"}, {"formats": {}})
        s.save(sid, {"A1": "1", "B2": "=A1+1", "nope!": "2", "C3": ""})
        got = s.get(sid)
        self.assertEqual(got["cells"], {"A1": "1", "B2": "=A1+1"})
        self.assertEqual(s.create("DCF"), sid + 1)
        self.assertEqual(s.get(sid + 1)["name"], "DCF (2)")


if __name__ == "__main__":
    unittest.main()
