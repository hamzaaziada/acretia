"""Form D funding rounds: parsing, classification, amendment chaining, search."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import formd  # noqa: E402
from om.search import Index  # noqa: E402

SUB = ["ACCESSIONNUMBER", "FILE_NUM", "FILING_DATE", "SIC_CODE", "SCHEMAVERSION", "SUBMISSIONTYPE", "TESTORLIVE"]
ISS = ["ACCESSIONNUMBER", "IS_PRIMARYISSUER_FLAG", "CIK", "ENTITYNAME", "CITY", "STATEORCOUNTRY", "STATEORCOUNTRYDESCRIPTION",
       "JURISDICTIONOFINC", "ENTITYTYPE", "YEAROFINC_VALUE_ENTERED"]
OFF = ["ACCESSIONNUMBER", "INDUSTRYGROUPTYPE", "REVENUERANGE", "FEDERALEXEMPTIONS_ITEMS_LIST", "ISAMENDMENT", "PREVIOUSACCESSIONNUMBER",
       "SALE_DATE", "YETTOOCCUR", "ISEQUITYTYPE", "ISDEBTTYPE", "ISPOOLEDINVESTMENTFUNDTYPE", "TOTALOFFERINGAMOUNT", "TOTALAMOUNTSOLD",
       "TOTALREMAINING", "TOTALNUMBERALREADYINVESTED", "NUMBERNONACCREDITEDINVESTORS"]

ROWS = [  # acc, filed, type, cik, name, state, industry, amendment, prev, sale, offering, sold, investors, pooled, live
    ("A1", "05-AUG-2026", "D", 11, "Acme Robotics, Inc.", "CA", "Other Technology", "false", "", "2026-07-30", "20000000", "12000000", "14", "false", "LIVE"),
    ("A2", "20-SEP-2026", "D/A", 11, "Acme Robotics, Inc.", "CA", "Other Technology", "true", "A1", "2026-07-30", "20000000", "18500000", "19", "false", "LIVE"),
    ("F1", "10-AUG-2026", "D", 22, "Sequoia Growth Fund IX, L.P.", "CA", "Pooled Investment Fund", "false", "", "2026-08-01", "Indefinite", "900000000", "80", "true", "LIVE"),
    ("V1", "11-AUG-2026", "D", 33, "Blue Harbor Private Credit Income Fund", "NY", "Other", "false", "", "2026-08-02", "Indefinite", "300000000", "400", "false", "LIVE"),
    ("R1", "12-AUG-2026", "D", 44, "Maple Street Apartments LLC", "TX", "Residential", "false", "", "2026-08-03", "8000000", "5000000", "30", "false", "LIVE"),
    ("P1", "13-AUG-2026", "D", 55, "Listed Chips Corp", "DE", "Other Technology", "false", "", "2026-08-04", "500000000", "500000000", "3", "false", "LIVE"),
    ("T1", "14-AUG-2026", "D", 66, "Test Filer Inc", "CA", "Other Technology", "false", "", "2026-08-05", "1", "1", "1", "false", "TEST"),
    ("E1", "15-AUG-2026", "D", 77, "Evergreen Holdings Inc", "NY", "Other", "false", "", "2019-01-01", "Indefinite", "70000000", "120", "false", "LIVE"),
]


def quarter_zip() -> bytes:
    def tsv(cols, rows):
        return "\t".join(cols) + "\n" + "\n".join("\t".join(r) for r in rows) + "\n"
    sub = [(a, "021-1", f, "", "X0708", t, live) for a, f, t, cik, n, st, ind, am, pv, sd, off, sold, inv, pool, live in ROWS]
    iss = [(a, "YES", str(cik), n, "San Francisco", st, st, "Delaware", "Corporation", "2021") for a, f, t, cik, n, st, *_ in ROWS]
    off = [(a, ind, "$1 - $1,000,000", "06b", am, pv, sd, "false", "true", "false", pool, o, s, "0", inv, "0")
           for a, f, t, cik, n, st, ind, am, pv, sd, o, s, inv, pool, live in ROWS]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("2026Q3_d/FORMDSUBMISSION.tsv", tsv(SUB, sub))
        z.writestr("2026Q3_d/ISSUERS.tsv", tsv(ISS, iss))
        z.writestr("2026Q3_d/OFFERING.tsv", tsv(OFF, off))
        z.writestr("2026Q3_d/RELATEDPERSONS.tsv", "ACCESSIONNUMBER\tFIRSTNAME\nA1\tJane\nA1\tJohn\n")
    return buf.getvalue()


class FormDTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "2026Q3_d.zip").write_bytes(quarter_zip())
        self.rounds = formd.Rounds(Index(self.tmp / "s.db").db)
        self.res = self.rounds.load_quarter(None, "2026Q3", "unused", self.tmp, public_ciks={55})

    def test_funds_and_test_filings_excluded(self):
        names = {r["company"] for r in self.rounds.search(category="all", limit=50)["results"]}
        self.assertNotIn("Sequoia Growth Fund IX, L.P.", names)
        self.assertNotIn("Test Filer Inc", names)

    def test_classification(self):
        cat = {r["company"]: r["category"] for r in self.rounds.search(category="all", limit=50)["results"]}
        self.assertEqual(cat["Acme Robotics, Inc."], "company")
        self.assertEqual(cat["Blue Harbor Private Credit Income Fund"], "vehicle")
        self.assertEqual(cat["Maple Street Apartments LLC"], "real_estate")
        self.assertEqual(cat["Listed Chips Corp"], "public_pipe")
        self.assertEqual(cat["Evergreen Holdings Inc"], "vehicle")      # continuous offering since 2019

    def test_amendment_merged_latest_amount_wins(self):
        acme = self.rounds.search("Acme")["results"]
        self.assertEqual(len(acme), 1)
        r = acme[0]
        self.assertEqual((r["round_id"], r["latest_accession"], r["filings"]), ("A1", "A2", 2))
        self.assertEqual(r["amount_sold"], 18_500_000)
        self.assertEqual(r["investors"], 19)
        self.assertEqual((r["first_filed"], r["last_filed"]), ("2026-08-05", "2026-09-20"))
        self.assertEqual(r["related_persons"], 2)
        self.assertEqual(r["securities"], "equity")
        self.assertIn("/data/11/A1/", formd.parse_quarter(quarter_zip(), "q")[0]["url"])

    def test_search_filters_and_stats(self):
        self.assertEqual(self.rounds.search()["total"], 1)                               # default: private companies only
        self.assertEqual(self.rounds.search(min_sold=100_000_000, category="all")["total"], 2)   # vehicle 300m + PIPE 500m; fund excluded
        self.assertEqual(self.rounds.search(state="TX", category="real_estate")["total"], 1)
        st = self.rounds.stats()
        self.assertEqual(st["rounds"], 1)
        self.assertEqual(st["median_sold"], 18_500_000)
        self.assertEqual(st["by_quarter"][0]["quarter"], "2026-Q3")
        self.assertEqual({c["category"] for c in st["categories"]}, {"company", "vehicle", "real_estate", "public_pipe"})

    def test_merge_is_order_independent(self):
        # load the amendment first, then the original (as happens when newer quarters load before older ones)
        rows = formd.parse_quarter(quarter_zip(), "2026Q3")
        r2 = formd.Rounds(Index(Path(tempfile.mkdtemp()) / "s.db").db)
        acme = [f for f in rows if f["cik"] == 11]
        r2.upsert([acme[1]])
        r2.upsert([acme[0]])
        got = r2.search("Acme")["results"]
        self.assertEqual(len(got), 1)
        g = got[0]
        self.assertEqual((g["first_filed"], g["last_filed"], g["latest_accession"], g["filings"], g["amount_sold"]),
                         ("2026-08-05", "2026-09-20", "A2", 2, 18_500_000))

    def test_reload_is_idempotent(self):
        self.rounds.load_quarter(None, "2026Q3", "unused", self.tmp, public_ciks={55})
        self.assertEqual(self.rounds.search(category="all")["total"], 5)

    def test_parsers(self):
        self.assertEqual(formd._date("30-SEP-2026"), "2026-09-30")
        self.assertIsNone(formd._num("Indefinite"))
        self.assertEqual(formd._num("1,250,000"), 1_250_000)


if __name__ == "__main__":
    unittest.main()
