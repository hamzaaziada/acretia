"""Data-room tests: VDR export import, extraction per format, page citations, room-scoped search & matrix."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures_office import sample_vdr_zip  # noqa: E402
from om.matrix import Column, MatrixStore  # noqa: E402
from om.rooms import Rooms  # noqa: E402
from om.search import Index  # noqa: E402

HAS_PDF = bool(shutil.which("pdftotext") or Path("/opt/homebrew/bin/pdftotext").exists())


class RoomTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.idx = Index(d / "s.db")
        self.rooms = Rooms(self.idx, d)
        self.rid = self.rooms.create("Project Falcon")
        self.res = self.rooms.add_zip(self.rid, sample_vdr_zip(), source="datasite-export")

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_counts_and_skips(self):
        expected = 4 if HAS_PDF else 3
        self.assertEqual(self.res.added, expected)
        self.assertGreaterEqual(self.res.skipped, 2)          # __MACOSX junk + unsupported .bin
        docs = {d["path"]: d for d in self.rooms.documents(self.rid)}
        self.assertIn("Project Falcon/2. Financials/2.1 Model.xlsx", docs)
        self.assertEqual(docs["Project Falcon/1. Overview/1.1 CIM.docx"]["pages"], 3)
        self.assertEqual(docs["Project Falcon/2. Financials/2.1 Model.xlsx"]["pages"], 2)

    def test_reimport_is_idempotent(self):
        again = self.rooms.add_zip(self.rid, sample_vdr_zip())
        self.assertEqual((again.added, again.updated), (0, 0))
        self.assertEqual(again.unchanged, self.res.added)

    def test_room_scoped_search_with_page_citation(self):
        r = self.idx.search('"net revenue retention"', {"room": self.rid})
        self.assertEqual(r["total_documents"], 1)
        p = r["results"][0]["passages"][0]
        self.assertIn("p.2", p["section"])                      # page 2 of the CIM
        self.assertEqual(self.idx.search('"net revenue retention"', {"public_only": True})["total_documents"], 0)

    def test_xlsx_and_pptx_text(self):
        self.assertEqual(self.idx.search('"Adjusted EBITDA"', {"room": self.rid, "forms": ["XLSX"]})["total_documents"], 1)
        r = self.idx.search("cold-chain ARR", {"room": self.rid})
        self.assertTrue(any(d["form"] == "PPTX" for d in r["results"]))   # speaker notes are indexed

    @unittest.skipUnless(HAS_PDF, "pdftotext not installed")
    def test_pdf_pages(self):
        r = self.idx.search('"change of control"', {"room": self.rid})
        self.assertEqual(r["results"][0]["form"], "PDF")
        self.assertIn("p.1", r["results"][0]["passages"][0]["section"])
        lit = self.idx.search("litigation", {"room": self.rid})
        self.assertIn("p.2", lit["results"][0]["passages"][0]["section"])

    def test_original_file_is_kept_for_citations(self):
        doc = self.rooms.documents(self.rid)[0]
        self.assertTrue(self.rooms.file_path(doc["doc_id"]).exists())

    def test_matrix_over_room_extractive(self):
        store = MatrixStore(self.idx)
        doc_ids = [d["doc_id"] for d in self.rooms.documents(self.rid) if d["path"].endswith("CIM.docx")]
        mid = store.create("falcon", doc_ids, [Column("Revenue", "What was FY2025 revenue?", "currency"),
                                                Column("Customer concentration", "How concentrated are the top customers?")])
        store.run(mid, None)
        cells = store.cells(mid)[doc_ids[0]]
        self.assertIn("84.2", cells["Revenue"]["answer"])
        self.assertAlmostEqual(cells["Revenue"]["value"], 84.2)
        self.assertIn("p.2", cells["Revenue"]["citations"][0]["section"])
        self.assertIn("41%", cells["Customer concentration"]["answer"])

    @unittest.skipUnless(HAS_PDF, "pdftotext not installed")
    def test_matrix_phrase_with_joining_word(self):
        store = MatrixStore(self.idx)
        pdf = [d["doc_id"] for d in self.rooms.documents(self.rid) if d["path"].endswith(".pdf")]
        mid = store.create("legal", pdf, [Column("Change of control", "Are there change of control provisions in material contracts?")])
        store.run(mid, None)
        self.assertIn("change of control clause", store.cells(mid)[pdf[0]]["Change of control"]["answer"])

    def test_path_traversal_rejected(self):
        r = self.rooms.add_file(self.rid, "../../etc/passwd.txt", b"nope")
        self.assertEqual(r.skipped, 1)


if __name__ == "__main__":
    unittest.main()
