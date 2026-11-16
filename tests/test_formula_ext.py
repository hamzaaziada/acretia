"""Extended om.formula function library: Excel semantics on values, and one workbook checked against LibreOffice.
Hermetic; the LibreOffice / formulon comparisons skip with a reason when the engine is missing."""
import unittest

from om import formula as fx
from om import recalc
from om.formula import Err
from om.xlsx import Workbook

S = "S"


def calc(formula, data=None, names=None):
    """Evaluate one formula; data is a list of rows placed at A1 on sheet S. The formula sits in Z99."""
    cells = {}
    for r, row in enumerate(data or [], 1):
        for c, v in enumerate(row, 1):
            if v is not None:
                cells[(S, r, c)] = v
    cells[(S, 99, 26)] = formula
    eng = fx.Engine(cells, names)
    eng.calculate()
    return eng.values[(S, 99, 26)]


def near(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(b))


TABLE = [["apple", 10, 1], ["banana", 20, 2], ["cherry", 30, 3], ["apple", 40, 4]]
NUMS = [[3], [1], [4], [1], [5], [9], [2], [6]]


class Lookup(unittest.TestCase):
    def test_vlookup(self):
        self.assertEqual(calc('=VLOOKUP("banana",A1:C4,2,FALSE)', TABLE), 20)
        self.assertEqual(calc('=VLOOKUP("APPLE",A1:C4,3,0)', TABLE), 1)            # first match, case-insensitive
        self.assertEqual(calc('=VLOOKUP("zzz",A1:C4,2,FALSE)', TABLE), Err("#N/A"))
        self.assertEqual(calc('=VLOOKUP("banana",A1:C4,4,FALSE)', TABLE), Err("#REF!"))
        self.assertEqual(calc('=VLOOKUP("b*",A1:C4,2,FALSE)', TABLE), 20)           # wildcard
        grades = [[0, "F"], [60, "D"], [70, "C"], [80, "B"], [90, "A"]]
        self.assertEqual(calc("=VLOOKUP(85,A1:B5,2)", grades), "B")                  # approximate is the default
        self.assertEqual(calc("=VLOOKUP(90,A1:B5,2,TRUE)", grades), "A")
        self.assertEqual(calc("=VLOOKUP(-1,A1:B5,2,TRUE)", grades), Err("#N/A"))

    def test_hlookup(self):
        data = [["q1", "q2", "q3"], [10, 20, 30]]
        self.assertEqual(calc('=HLOOKUP("q2",A1:C2,2,FALSE)', data), 20)
        self.assertEqual(calc('=HLOOKUP("q9",A1:C2,2,FALSE)', data), Err("#N/A"))
        self.assertEqual(calc("=HLOOKUP(2,A1:C2,2,TRUE)", [[1, 2, 3], ["a", "b", "c"]]), "b")

    def test_lookup_and_xlookup(self):
        data = [[1, "a"], [5, "b"], [9, "c"]]
        self.assertEqual(calc("=LOOKUP(6,A1:A3,B1:B3)", data), "b")
        self.assertEqual(calc("=LOOKUP(0,A1:A3,B1:B3)", data), Err("#N/A"))
        self.assertEqual(calc("=XLOOKUP(5,A1:A3,B1:B3)", data), "b")
        self.assertEqual(calc('=XLOOKUP(6,A1:A3,B1:B3,"none")', data), "none")
        self.assertEqual(calc("=XLOOKUP(6,A1:A3,B1:B3,,-1)", data), "b")              # next smaller
        self.assertEqual(calc("=XLOOKUP(6,A1:A3,B1:B3,,1)", data), "c")               # next larger
        self.assertEqual(calc("=XLOOKUP(7,A1:A3,B1:B3)", data), Err("#N/A"))
        self.assertEqual(calc("=XLOOKUP(5,A1:A3,A1:B3)", data), 5)                    # wide return spills; we take its first cell


class Conditional(unittest.TestCase):
    def test_ifs_family(self):
        self.assertEqual(calc('=AVERAGEIF(A1:A4,"apple",B1:B4)', TABLE), 25)
        self.assertEqual(calc('=AVERAGEIF(A1:A4,"kiwi",B1:B4)', TABLE), Err("#DIV/0!"))
        self.assertEqual(calc('=SUMIFS(B1:B4,A1:A4,"apple",C1:C4,">1")', TABLE), 40)
        self.assertEqual(calc('=SUMIFS(B1:B4,A1:A4,"<>apple")', TABLE), 50)
        self.assertEqual(calc('=COUNTIFS(A1:A4,"apple",B1:B4,">=10")', TABLE), 2)
        self.assertEqual(calc('=COUNTIFS(A1:A4,"*an*")', TABLE), 1)                   # wildcard
        self.assertEqual(calc('=MAXIFS(B1:B4,A1:A4,"apple")', TABLE), 40)
        self.assertEqual(calc('=MINIFS(B1:B4,A1:A4,"apple")', TABLE), 10)
        self.assertEqual(calc('=MAXIFS(B1:B4,A1:A4,"none")', TABLE), 0)
        self.assertEqual(calc('=AVERAGEIFS(B1:B4,A1:A4,"apple",C1:C4,"<4")', TABLE), 10)
        self.assertEqual(calc('=SUMIFS(B1:B4,A1:A3,"apple")', TABLE), Err("#VALUE!"))   # mismatched ranges


class Dates(unittest.TestCase):
    def test_serials(self):
        self.assertEqual(calc("=DATE(2024,2,29)"), 45351)
        self.assertEqual(calc("=DATE(2024,14,1)"), calc("=DATE(2025,2,1)"))
        self.assertEqual(calc("=DATE(2024,1,0)"), calc("=DATE(2023,12,31)"))
        self.assertEqual(calc("=YEAR(DATE(2031,7,9))"), 2031)
        self.assertEqual(calc("=MONTH(DATE(2031,7,9))"), 7)
        self.assertEqual(calc("=DAY(DATE(2031,7,9))"), 9)
        self.assertEqual(calc("=DATE(1900,3,1)"), 61)
        self.assertEqual(calc("=YEAR(61)*100+MONTH(61)"), 190003)

    def test_month_arithmetic(self):
        self.assertEqual(calc("=EOMONTH(DATE(2024,1,31),1)"), calc("=DATE(2024,2,29)"))
        self.assertEqual(calc("=EOMONTH(DATE(2024,1,15),-1)"), calc("=DATE(2023,12,31)"))
        self.assertEqual(calc("=EDATE(DATE(2024,1,31),1)"), calc("=DATE(2024,2,29)"))
        self.assertEqual(calc("=EDATE(DATE(2024,3,31),-1)"), calc("=DATE(2024,2,29)"))
        self.assertEqual(calc("=EDATE(DATE(2024,5,15),12)"), calc("=DATE(2025,5,15)"))


class Text(unittest.TestCase):
    def test_text(self):
        self.assertEqual(calc('=CONCATENATE("a",1,TRUE)'), "a1TRUE")
        self.assertEqual(calc('=CONCAT(A1:B2)', [["x", 1], ["y", 2]]), "x1y2")
        self.assertEqual(calc('=TEXTJOIN(", ",TRUE,A1:A4)', [["a"], [None], ["b"], [""]]), "a, b")
        self.assertEqual(calc('=TEXTJOIN("-",FALSE,A1:A3)', [["a"], [None], ["b"]]), "a--b")
        self.assertEqual(calc('=RIGHT("banker",3)'), "ker")
        self.assertEqual(calc('=RIGHT("ab",5)'), "ab")
        self.assertEqual(calc('=RIGHT("abc")'), "c")
        self.assertEqual(calc('=MID("banker",2,3)'), "ank")
        self.assertEqual(calc('=MID("banker",9,3)'), "")
        self.assertEqual(calc('=MID("banker",0,3)'), Err("#VALUE!"))
        self.assertEqual(calc('=UPPER("aBc")&LOWER("DeF")'), "ABCdef")
        self.assertEqual(calc('=TRIM("  a   b  ")'), "a b")
        self.assertEqual(calc('=SUBSTITUTE("a-b-c","-","+")'), "a+b+c")
        self.assertEqual(calc('=SUBSTITUTE("a-b-c","-","+",2)'), "a-b+c")
        self.assertEqual(calc('=SUBSTITUTE("abc","","+")'), "abc")

    def test_value(self):
        self.assertEqual(calc('=VALUE("1,234.5")'), 1234.5)
        self.assertEqual(calc('=VALUE("12%")'), 0.12)
        self.assertEqual(calc('=VALUE("abc")'), Err("#VALUE!"))
        self.assertEqual(calc("=VALUE(7)"), 7)

    def test_long_numbers_keep_precision_in_concatenation(self):
        self.assertEqual(calc('="x"&1234567.891'), "x1234567.891")


class Statistics(unittest.TestCase):
    def test_rank_large_small(self):
        self.assertEqual(calc("=LARGE(A1:A8,2)", NUMS), 6)
        self.assertEqual(calc("=SMALL(A1:A8,2)", NUMS), 1)
        self.assertEqual(calc("=LARGE(A1:A8,9)", NUMS), Err("#NUM!"))
        self.assertEqual(calc("=RANK(9,A1:A8)", NUMS), 1)
        self.assertEqual(calc("=RANK.EQ(1,A1:A8,1)", NUMS), 1)
        self.assertEqual(calc("=RANK(1,A1:A8)", NUMS), 7)                              # ties share the best rank
        self.assertEqual(calc("=RANK(7,A1:A8)", NUMS), Err("#N/A"))

    def test_product_countblank(self):
        self.assertEqual(calc("=PRODUCT(A1:A3)", [[2], [3], [4]]), 24)
        self.assertEqual(calc("=PRODUCT(A1:A3,2)", [[2], ["x"], [4]]), 16)             # text in ranges is ignored
        self.assertEqual(calc("=COUNTBLANK(A1:A4)", [[1], [None], [""], [2]]), 2)

    def test_branching(self):
        self.assertEqual(calc('=IFS(A1>5,"big",A1>2,"mid",TRUE,"small")', [[3]]), "mid")
        self.assertEqual(calc('=IFS(A1>5,"big")', [[3]]), Err("#N/A"))
        self.assertEqual(calc('=IFS(A1>0,"ok",1/0,"never")', [[3]]), "ok")            # later branches are not evaluated
        self.assertEqual(calc('=SWITCH(A1,1,"one",2,"two","other")', [[2]]), "two")
        self.assertEqual(calc('=SWITCH(A1,1,"one",2,"two","other")', [[9]]), "other")
        self.assertEqual(calc('=SWITCH(A1,1,"one")', [[9]]), Err("#N/A"))
        self.assertEqual(calc("=ISERR(1/0)"), True)
        self.assertEqual(calc("=ISERR(NA())"), False)
        self.assertEqual(calc("=ISERR(5)"), False)
        self.assertEqual(calc("=NA()"), Err("#N/A"))
        self.assertEqual(calc("=IFERROR(NA(),7)"), 7)


class Financial(unittest.TestCase):
    def test_annuity(self):
        pmt = calc("=PMT(0.05/12,360,200000)")
        self.assertTrue(near(pmt, -1073.6432460242797, 1e-9), pmt)
        self.assertTrue(near(calc("=PMT(0,10,1000)"), -100))
        self.assertTrue(near(calc("=PMT(0.05/12,360,200000,0,1)"), pmt / (1 + 0.05 / 12), 1e-9))
        self.assertTrue(near(calc("=FV(0.06/12,10,-200,-500,1)"), 2581.4033740601362, 1e-9))
        self.assertTrue(near(calc("=PV(0.08/12,240,500)"), -59777.14585118777, 1e-9))
        self.assertTrue(near(calc("=PV(0,10,5)"), -50))
        self.assertTrue(near(calc("=RATE(360,-1073.6432460242797,200000)"), 0.05 / 12, 1e-7))
        self.assertTrue(near(calc("=NPER(0.01,-100,1000)"), 10.58867, 1e-5))

    def test_xnpv_xirr(self):
        d = [[-10000, 39448], [2750, 39508], [4250, 39751], [3250, 39859], [2750, 39904]]    # Microsoft's documentation example
        self.assertTrue(near(calc("=XNPV(0.09,A1:A5,B1:B5)", d), 2086.6476020315354, 1e-9))
        self.assertTrue(near(calc("=XIRR(A1:A5,B1:B5)", d), 0.3733625335188315, 1e-7))
        self.assertEqual(calc("=XIRR(A1:A2,B1:B2)", [[100, 39448], [200, 39508]]), Err("#NUM!"))     # no sign change
        self.assertEqual(calc("=XNPV(0.1,A1:A2,B1:B2)", [[-100, 39508], [200, 39448]]), Err("#NUM!"))  # date before the first


class AgainstLibreOffice(unittest.TestCase):
    """One workbook that uses every new function; cached values (om.formula) must match LibreOffice and formulon."""

    def build(self, with_xlookup=False):
        wb = Workbook()
        d = wb.sheet("Data")
        rows = [("apple", 10, 1, 44927), ("banana", 20, 2, 45000), ("cherry", 30, 3, 45100), ("apple", 40, 4, 45200),
                ("Date apple", 5, 6, 45300), ("kiwi", 50, 7, 45400)]
        for i, row in enumerate(rows, 1):
            for j, v in enumerate(row, 1):
                d.set((i, j), v)
        for i, v in enumerate([3, 1, 4, 1, 5, 9, 2, 6], 1):
            d.set((i, 6), v)
        d.set("G1", "  a   b ")
        d.set("G2", "1,234.5")
        d.set("H1", -10000), d.set("H2", 2750), d.set("H3", 4250), d.set("H4", 3250), d.set("H5", 2750)
        for i, v in enumerate([39448, 39508, 39751, 39859, 39904], 1):
            d.set((i, 9), v)
        t = wb.sheet("Test")
        fs = ['=VLOOKUP("banana",Data!A1:D6,2,FALSE)', '=VLOOKUP(2.5,Data!C1:D6,2)', '=VLOOKUP("b*",Data!A1:D6,3,FALSE)',
              '=HLOOKUP(10,Data!B1:D2,2,FALSE)', '=LOOKUP(25,Data!B1:B6,Data!C1:C6)',
              '=AVERAGEIF(Data!A1:A6,"apple",Data!B1:B6)', '=AVERAGEIFS(Data!B1:B6,Data!A1:A6,"apple",Data!C1:C6,">1")',
              '=SUMIFS(Data!B1:B6,Data!A1:A6,"apple",Data!C1:C6,">=1")', '=COUNTIFS(Data!A1:A6,"*apple",Data!B1:B6,">=5")',
              '=MAXIFS(Data!B1:B6,Data!A1:A6,"apple")', '=MINIFS(Data!B1:B6,Data!A1:A6,"apple")',
              "=YEAR(Data!D1)", "=MONTH(Data!D2)", "=DAY(Data!D3)", "=DATE(2024,14,31)", "=EOMONTH(Data!D1,3)", "=EDATE(Data!D1,13)",
              '=CONCATENATE(Data!A1,"-",Data!B1)', "=CONCAT(Data!A1:B2)", '=TEXTJOIN(";",TRUE,Data!A1:A3)', '=RIGHT(Data!A2,3)',
              "=MID(Data!A2,2,3)", "=UPPER(Data!A1)", "=LOWER(Data!A5)", "=TRIM(Data!G1)", '=SUBSTITUTE(Data!A1,"p","P",2)',
              "=VALUE(Data!G2)", "=LARGE(Data!F1:F8,3)", "=SMALL(Data!F1:F8,3)", "=RANK(5,Data!F1:F8)", "=RANK.EQ(1,Data!F1:F8,1)",
              "=PRODUCT(Data!C1:C4)", "=COUNTBLANK(Data!F1:F10)", '=IFS(Data!B1>20,"big",Data!B1>5,"mid",TRUE,"small")',
              '=SWITCH(Data!C2,1,"one",2,"two","other")', "=ISERR(1/0)", "=ISERR(NA())", "=IFERROR(NA(),-1)",
              "=PMT(0.05/12,360,200000)", "=FV(0.06/12,10,-200,-500,1)", "=PV(0.08/12,240,500)", "=RATE(360,-1073.64324602428,200000)",
              "=XNPV(0.09,Data!H1:H5,Data!I1:I5)", "=XIRR(Data!H1:H5,Data!I1:I5)", "=VLOOKUP(\"zz\",Data!A1:D6,2,FALSE)",
              "=IFERROR(VLOOKUP(\"zz\",Data!A1:D6,2,FALSE),\"missing\")"]
        if with_xlookup:
            fs = ['=XLOOKUP("cherry",Data!A1:A6,Data!B1:B6)', '=XLOOKUP("zz",Data!A1:A6,Data!B1:B6,"none")', "=XLOOKUP(25,Data!B1:B6,Data!C1:C6,,-1)"]
        for i, f in enumerate(fs, 1):
            t.set((i, 1), f)
        fx.calculate_workbook(wb)
        return wb.to_bytes(), len(fs)

    def test_values_match_libreoffice(self):
        if not recalc.daemon().available():
            self.skipTest(f"LibreOffice unavailable: {recalc.daemon().reason}")
        data, n = self.build()
        r = recalc.compare(data, engines=["cached", "libreoffice", "om"])
        self.assertTrue(r["engines"]["libreoffice"]["available"], r["engines"]["libreoffice"]["reason"])
        self.assertEqual(r["divergences"], [], r["divergences"][:3])
        self.assertGreaterEqual(r["compared_cells"], n)
        self.assertEqual(r["engines"]["om"]["cannot_evaluate"], {})

    def test_values_match_formulon(self):
        data, n = self.build()
        r = recalc.compare(data, engines=["cached", "formulon", "om"])
        if not r["engines"]["formulon"]["available"]:
            self.skipTest(r["engines"]["formulon"]["reason"])
        self.assertEqual(r["divergences"], [], r["divergences"][:3])

    def test_xlookup_against_formulon(self):
        data, n = self.build(with_xlookup=True)
        r = recalc.compare(data, engines=["cached", "formulon", "om"])
        if not r["engines"]["formulon"]["available"]:
            self.skipTest(r["engines"]["formulon"]["reason"])
        self.assertEqual(r["divergences"], [], r["divergences"][:3])


if __name__ == "__main__":
    unittest.main()
