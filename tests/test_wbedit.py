"""S4.4: targeted edits, byte-identity of everything not touched, cached-value refresh."""
import io
import re
import unittest
import zipfile

import openpyxl

from om import formula as fx, model3, statements as stm, wbedit, xlsx
from tests.test_model3 import synthetic_companyfacts

CELL = re.compile(r'<c\b[^>]*?\br="([A-Z]+\d+)"[^>]*?(?:/>|>.*?</c>)', re.S)


def parts(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    return z.namelist(), {n: z.read(n) for n in z.namelist()}


def cells(xml):
    return {m.group(1): m.group(0) for m in CELL.finditer(xml)}


def skeleton(xml):
    return CELL.sub("", xml)


class Fixture(unittest.TestCase):
    def assertSurgical(self, old, new, sheet_parts_allowed, touched_cells):
        """Unaffected parts are byte-identical (same order); affected sheets differ only inside the listed <c> elements."""
        n0, p0 = parts(old)
        n1, p1 = parts(new)
        self.assertEqual([n for n in n0 if n in p1], n1)
        for n in n0:
            if n in p1 and n not in sheet_parts_allowed:
                self.assertEqual(p0[n], p1[n], n)
        for n in sheet_parts_allowed:
            a, b = p0[n].decode(), p1[n].decode()
            self.assertEqual(skeleton(a), skeleton(b), f"{n}: non-cell xml changed")
            ca, cb = cells(a), cells(b)
            for k in set(ca) | set(cb):
                if k not in touched_cells.get(n, set()):
                    self.assertEqual(ca.get(k), cb.get(k), f"{n}!{k} changed unexpectedly")


class ModelWorkbookTests(Fixture):
    @classmethod
    def setUpClass(cls):
        s = stm.build(synthetic_companyfacts((2022, 2023, 2024)), "TST")
        cls.data, cls.meta = model3.build(s)
        cls.rows = cls.meta["rows"]

    @staticmethod
    def names_to_parts(data):
        return {n: f"xl/worksheets/sheet{i}.xml" for i, n in enumerate(xlsx.read(data).order, 1)}

    def test_edit_input_is_surgical_and_matches_full_recalc(self):
        tax = f"Assumptions!F{self.rows['Assumptions']['tax']}"
        new, rep = wbedit.edit(self.data, {tax: 0.30})
        self.assertGreater(len(rep["dependents_updated"]), 100)
        self.assertTrue(any(d["cell"].startswith("DCF!") for d in rep["dependents_updated"]))   # across sheets
        self.assertIn("xl/worksheets/sheet2.xml", rep["parts_touched"])
        self.assertFalse(rep["calc_chain_removed"])
        changed = {}
        names = self.names_to_parts(self.data)
        for d in rep["dependents_updated"] + [{"cell": tax}]:
            sh, a1 = d["cell"].rsplit("!", 1)
            changed.setdefault(names[sh], set()).add(a1)
        self.assertSurgical(self.data, new, set(changed), changed)
        # cached values equal a from-scratch recalculation of the edited file
        bk = xlsx.read(new)
        eng = fx.from_book(bk)
        eng.calculate(iterate=True)
        bad = 0
        for (sh, r, c), v in eng.values.items():
            cell = bk.sheets[sh].get((r, c))
            if cell and cell.formula and isinstance(v, float):
                if abs(v - cell.value) > 1e-7 * max(1.0, abs(v)):
                    bad += 1
        self.assertEqual(bad, 0)
        a1 = tax.split("!")[1]
        self.assertAlmostEqual(bk.value("Assumptions", a1), 0.30)
        self.assertEqual(bk.cell("Assumptions", a1).color, "0000FF")                          # style (blue input) preserved
        old = xlsx.read(self.data)
        self.assertNotAlmostEqual(old.value("DCF", "C48"), bk.value("DCF", "C48"))            # value per share moved

    def test_edit_without_recalc_touches_only_targets(self):
        tax = f"Assumptions!F{self.rows['Assumptions']['tax']}"
        new, rep = wbedit.edit(self.data, {tax: 0.30}, recalc=False)
        self.assertEqual(rep["dependents_updated"], [])
        self.assertEqual(rep["parts_touched"], ["xl/worksheets/sheet2.xml"])
        self.assertSurgical(self.data, new, {"xl/worksheets/sheet2.xml"}, {"xl/worksheets/sheet2.xml": {tax.split("!")[1]}})

    def test_formula_and_text_edits(self):
        a = f"Assumptions!G{self.rows['Assumptions']['capex']}"
        new, rep = wbedit.edit(self.data, {a: "=Assumptions!F31+Assumptions!G14", "Cover!B3": "Edited subtitle"})
        bk = xlsx.read(new)
        a1 = a.split("!")[1]
        self.assertEqual(bk.cell("Assumptions", a1).formula, "=Assumptions!F31+Assumptions!G14")
        self.assertEqual(bk.value("Cover", "B3"), "Edited subtitle")
        self.assertAlmostEqual(bk.value("Assumptions", a1), bk.value("Assumptions", "F31") + bk.value("Assumptions", "G14"))
        with self.assertRaises(ValueError):
            wbedit.edit(self.data, {a: "=SUM(("})
        with self.assertRaises(KeyError):
            wbedit.edit(self.data, {"Nope!A1": 1})


def make_openpyxl():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calc"
    ws["A1"], ws["B1"] = "Label", "Value"
    ws["A2"], ws["B2"] = "Base", 10
    ws["A3"], ws["B3"] = "Rate", 0.5
    ws["A4"], ws["B4"] = "Product", "=B2*B3"
    ws["B2"].number_format = "0.00"
    for i in range(6, 9):
        ws[f"A{i}"], ws[f"B{i}"] = f"Row {i}", i
        ws[f"C{i}"] = f"=B{i}*2"
    ws["A10"] = "merged"
    ws.merge_cells("A10:B10")
    ws2 = wb.create_sheet("Other")
    ws2["A1"] = "=Calc!B4+1"
    buf = io.BytesIO()
    wb.save(buf)
    return to_shared_strings(buf.getvalue())


def to_shared_strings(data):
    """This openpyxl writes inline strings; real files (Excel, LibreOffice) use xl/sharedStrings.xml, so convert."""
    z = zipfile.ZipFile(io.BytesIO(data))
    sst, out = [], io.BytesIO()

    def conv(xml):
        def one(m):
            sst.append(m.group(3))
            return f'<c r="{m.group(1)}"{m.group(2)} t="s"><v>{len(sst) - 1}</v></c>'
        return re.sub(r'<c r="([A-Z]+\d+)"([^>]*?) t="inlineStr"><is><t[^>]*>(.*?)</t></is></c>', one, xml)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
        for i in z.infolist():
            b = z.read(i.filename)
            if i.filename.startswith("xl/worksheets/sheet"):
                b = conv(b.decode()).encode()
            if i.filename == "[Content_Types].xml":
                b = b.decode().replace("</Types>", '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>').encode()
            if i.filename == "xl/_rels/workbook.xml.rels":
                b = b.decode().replace("</Relationships>", '<Relationship Id="rId98" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>').encode()
            w.writestr(i.filename, b)
        body = "".join(f"<si><t>{t}</t></si>" for t in sst)
        w.writestr("xl/sharedStrings.xml", f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(sst)}" uniqueCount="{len(sst)}">{body}</sst>')
    return out.getvalue()


def patch_part(data, part, fn):
    z = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
        for i in z.infolist():
            b = z.read(i.filename)
            w.writestr(i.filename, fn(b.decode()).encode() if i.filename == part else b)
    return out.getvalue()


def add_calc_chain(b):
    z = zipfile.ZipFile(io.BytesIO(b))
    out = io.BytesIO()
    override = '<Override PartName="/xl/calcChain.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.calcChain+xml"/>'
    rel = '<Relationship Id="rId99" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/calcChain" Target="calcChain.xml"/>'
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
        for i in z.infolist():
            x = z.read(i.filename)
            if i.filename == "[Content_Types].xml":
                x = x.decode().replace("</Types>", override + "</Types>").encode()
            if i.filename == "xl/_rels/workbook.xml.rels":
                x = x.decode().replace("</Relationships>", rel + "</Relationships>").encode()
            w.writestr(i.filename, x)
        w.writestr("xl/calcChain.xml", '<calcChain xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><c r="B4" i="1"/></calcChain>')
    return out.getvalue()


SHEET1 = "xl/worksheets/sheet1.xml"
SHEET2 = "xl/worksheets/sheet2.xml"


class OpenpyxlWorkbookTests(Fixture):
    def test_shared_strings_and_dependents(self):
        data = make_openpyxl()
        names, p = parts(data)
        self.assertIn("xl/sharedStrings.xml", names)
        new, rep = wbedit.edit(data, {"Calc!B2": 20, "Calc!A3": "Discount"})
        n1, p1 = parts(new)
        self.assertEqual(p["xl/sharedStrings.xml"], p1["xl/sharedStrings.xml"])     # shared strings part untouched
        deps = {d["cell"] for d in rep["dependents_updated"]}
        self.assertEqual(deps, {"Calc!B4", "Other!A1"})
        self.assertSurgical(data, new, {SHEET1, SHEET2}, {SHEET1: {"B2", "A3", "B4"}, SHEET2: {"A1"}})
        bk = xlsx.read(new)
        self.assertEqual(bk.value("Calc", "A3"), "Discount")                          # was t="s", now inline text
        self.assertEqual(bk.value("Calc", "B2"), 20.0)
        self.assertAlmostEqual(bk.value("Calc", "B4"), 10.0)
        self.assertAlmostEqual(bk.value("Other", "A1"), 11.0)
        style = lambda blob: re.search(r'<c r="B2"[^>]*\bs="(\d+)"', blob.decode()).group(1)
        self.assertEqual(style(p[SHEET1]), style(p1[SHEET1]))                         # style of the edited input preserved
        self.assertEqual(n1, names)

    def test_new_cell_in_new_row_and_existing_row(self):
        new, _ = wbedit.edit(make_openpyxl(), {"Calc!D6": 7, "Calc!B20": "=B2+1", "Calc!A5": "gap row"})
        bk = xlsx.read(new)
        self.assertEqual(bk.value("Calc", "D6"), 7.0)
        self.assertAlmostEqual(bk.value("Calc", "B20"), 11.0)
        self.assertEqual(bk.value("Calc", "A5"), "gap row")
        xml = zipfile.ZipFile(io.BytesIO(new)).read(SHEET1).decode()
        self.assertLess(xml.index('r="C6"'), xml.index('r="D6"'))                     # column order kept inside the row
        self.assertLess(xml.index('<row r="10"'), xml.index('<row r="20"'))           # rows kept in order
        openpyxl.load_workbook(io.BytesIO(new))                                       # still a valid workbook

    def test_shared_formula_group(self):
        def share(xml):
            xml = xml.replace("<f>B6*2</f>", '<f t="shared" ref="C6:C8" si="0">B6*2</f>')
            xml = xml.replace("<f>B7*2</f>", '<f t="shared" si="0"/>')
            return xml.replace("<f>B8*2</f>", '<f t="shared" si="0"/>')
        data = patch_part(make_openpyxl(), SHEET1, share)
        self.assertEqual(xlsx.read(data).cell("Calc", "C8").formula, "=B8*2")
        # editing a group member de-shares only that cell
        new, rep = wbedit.edit(data, {"Calc!C7": 99})
        xml = zipfile.ZipFile(io.BytesIO(new)).read(SHEET1).decode()
        self.assertIn('<f t="shared" ref="C6:C8" si="0">B6*2</f>', xml)
        self.assertEqual(xml.count('t="shared"'), 2)
        self.assertEqual(rep["unshared"], ["Calc!C7"])
        bk = xlsx.read(new)
        self.assertEqual(bk.value("Calc", "C7"), 99.0)
        self.assertEqual(bk.cell("Calc", "C8").formula, "=B8*2")
        # editing the master expands the group so the other cells keep their formulas
        new, rep = wbedit.edit(data, {"Calc!C6": 1})
        bk = xlsx.read(new)
        self.assertEqual(bk.cell("Calc", "C7").formula, "=B7*2")
        self.assertEqual(bk.cell("Calc", "C8").formula, "=B8*2")
        self.assertNotIn(b't="shared"', zipfile.ZipFile(io.BytesIO(new)).read(SHEET1))
        self.assertEqual(rep["unshared"], ["Calc!C6", "Calc!C7", "Calc!C8"])

    def test_refuses_merged_and_array(self):
        data = make_openpyxl()
        with self.assertRaises(wbedit.EditRefused):
            wbedit.edit(data, {"Calc!B10": 1})                                         # inside A10:B10
        arr = patch_part(data, SHEET1, lambda x: x.replace("<f>B2*B3</f>", '<f t="array" ref="B4:B5">B2*B3</f>'))
        with self.assertRaises(wbedit.EditRefused):
            wbedit.edit(arr, {"Calc!B5": 1})
        with self.assertRaises(wbedit.EditRefused):
            wbedit.edit(arr, {"Calc!B4": 1})

    def test_calc_chain_removed_only_when_present(self):
        data = make_openpyxl()
        _, rep = wbedit.edit(data, {"Calc!B2": 3})
        self.assertFalse(rep["calc_chain_removed"])
        new, rep = wbedit.edit(add_calc_chain(data), {"Calc!B2": 3})
        n, p = parts(new)
        self.assertTrue(rep["calc_chain_removed"])
        self.assertNotIn("xl/calcChain.xml", n)
        self.assertNotIn(b"calcChain", p["[Content_Types].xml"])
        self.assertNotIn(b"calcChain", p["xl/_rels/workbook.xml.rels"])
        self.assertIn("[Content_Types].xml", rep["parts_touched"])
        openpyxl.load_workbook(io.BytesIO(new))


if __name__ == "__main__":
    unittest.main()
