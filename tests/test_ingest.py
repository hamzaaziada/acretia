"""P2.4: concurrent, deduplicating, idempotent and resumable ingestion into data rooms."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import om.rooms as rooms_mod  # noqa: E402
from fixtures_office import docx  # noqa: E402
from om.rooms import Rooms  # noqa: E402
from om.search import Index  # noqa: E402
from om.xlsx import Workbook  # noqa: E402


def make_corpus(root: Path) -> dict:
    """60 distinct files + 5 exact duplicates + 2 corrupt + noise; returns expectations."""
    root.mkdir(parents=True)
    (root / "sub").mkdir()
    n = 0
    for i in range(60):
        kind = i % 4
        d = root / ("sub" if i % 5 == 0 else "")
        if kind == 0:
            (d / f"note{i}.txt").write_text(f"Note {i}: unique content number {i} about covenant {i}")
        elif kind == 1:
            (d / f"memo{i}.md").write_text(f"# Memo {i}\nBody text for memo {i}")
        elif kind == 2:
            (d / f"data{i}.csv").write_text(f"a,b\n{i},{i * 2}\n")
        else:
            wb = Workbook()
            wb.sheet("S").set("A1", f"Revenue {i}")
            (d / f"book{i}.xlsx").write_bytes(wb.to_bytes() if i % 8 == 3 else docx([[f"Doc {i} paragraph"]]))
            if i % 8 != 3:
                (d / f"book{i}.xlsx").rename(d / f"letter{i}.docx")
        n += 1
    for k in range(5):  # exact duplicates under other names (sort after the originals)
        (root / f"zz_copy{k}.txt").write_bytes((root / f"note{k * 4}.txt").read_bytes() if (root / f"note{k * 4}.txt").exists()
                                               else (root / "sub" / f"note{k * 4}.txt").read_bytes())
    (root / "bad1.docx").write_bytes(b"not a zip at all")
    (root / "bad2.xlsx").write_bytes(b"PK\x03\x04garbage")
    (root / "empty.txt").write_bytes(b"")
    (root / "photo.bin").write_bytes(b"\x00\x01")
    (root / ".hidden.txt").write_text("secret")
    (root / "__MACOSX").mkdir()
    (root / "__MACOSX" / "x.txt").write_text("junk")
    outside = root.parent / "outside_secret.txt"
    outside.write_text("do not ingest me")
    os.symlink(outside, root / "link.txt")
    return {"added": 60, "duplicates": 5, "failed": {"bad1.docx", "bad2.xlsx", "empty.txt", "photo.bin", "link.txt"}}


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.exp = make_corpus(self.d / "corpus")
        self.idx = Index(self.d / "s.db")
        self.rooms = Rooms(self.idx, self.d / "data")
        self.rid = self.rooms.create("Falcon")

    def tearDown(self):
        self.tmp.cleanup()

    def counts(self):
        db = self.idx.db
        return tuple(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("documents", "chunks", "chunks_fts", "ingest_state", "room_events"))

    def test_ingest_counts_dedupe_and_failures(self):
        rep = self.rooms.ingest("Falcon", self.d / "corpus", workers=8)
        self.assertEqual(rep.added, self.exp["added"])
        self.assertEqual(rep.duplicates, self.exp["duplicates"])
        self.assertEqual({n for n, _ in rep.failed}, self.exp["failed"])
        self.assertTrue(all(r for _, r in rep.failed))
        self.assertEqual(len(self.rooms.documents(self.rid)), 60)
        self.assertGreater(rep.files_per_s, 0)
        names = {d["path"] for d in self.rooms.documents(self.rid)}
        self.assertFalse(any(".hidden" in n or "MACOSX" in n or "link" in n or "zz_copy" in n for n in names))
        self.assertEqual(self.idx.search("covenant", {"room": self.rid})["total_documents"] > 0, True)
        self.assertNotIn("outside_secret", str(self.idx.db.execute("SELECT group_concat(path) FROM documents").fetchone()[0]))

    def test_rerun_is_noop(self):
        self.rooms.ingest(self.rid, self.d / "corpus")
        before = self.counts()
        files = self.d / "data" / "rooms" / str(self.rid) / "files"
        mt = {p: p.stat().st_mtime_ns for p in files.rglob("*") if p.is_file()}
        dbm = (self.d / "s.db").stat().st_mtime_ns
        time.sleep(0.02)
        rep = self.rooms.ingest(self.rid, self.d / "corpus")
        self.assertEqual((rep.added, rep.duplicates), (0, 0))
        self.assertEqual(rep.skipped, 65)
        self.assertEqual(len(rep.failed), 5)
        self.assertEqual(self.counts(), before)
        self.assertEqual({p: p.stat().st_mtime_ns for p in files.rglob("*") if p.is_file()}, mt)
        self.assertEqual((self.d / "s.db").stat().st_mtime_ns, dbm)

    def test_resume_after_stop_and_after_exception(self):
        clean = Rooms(Index(self.d / "clean.db"), self.d / "cdata")
        cid = clean.create("Falcon")
        ref = clean.ingest(cid, self.d / "corpus")

        r1 = self.rooms.ingest(self.rid, self.d / "corpus", stop_after=20)
        self.assertTrue(r1.interrupted)
        self.assertEqual(r1.added + r1.duplicates + r1.skipped + len(r1.failed), 20 + 1)  # +1 pre-rejected symlink

        crashed = []

        def boom(done, total, rel, status):
            crashed.append(done)
            if done >= 45:
                raise RuntimeError("simulated crash")
        with self.assertRaises(RuntimeError):
            self.rooms.ingest(self.rid, self.d / "corpus", progress=boom)
        part = len(self.rooms.documents(self.rid))
        self.assertGreater(part, r1.added)
        self.assertLess(part, 60)

        redone = []
        real = rooms_mod._extract_one
        with mock.patch.object(rooms_mod, "_extract_one", side_effect=lambda p: (redone.append(p.name), real(p))[1]):
            r3 = self.rooms.ingest(self.rid, self.d / "corpus")
        self.assertEqual({d["path"] for d in self.rooms.documents(self.rid)}, {d["path"] for d in clean.documents(cid)})
        self.assertEqual(part + r3.added, ref.added)
        self.assertEqual(len(redone), r3.added + 2)           # only unfinished files (+2 corrupt retried) were extracted
        self.assertEqual({n for n, _ in r3.failed}, {n for n, _ in ref.failed})
        r4 = self.rooms.ingest(self.rid, self.d / "corpus")
        self.assertEqual((r4.added, r4.duplicates), (0, 0))

    def test_resume_totals_match_clean_run(self):
        ref = Rooms(Index(self.d / "c2.db"), self.d / "c2d")
        ref_rep = ref.ingest(ref.create("Falcon"), self.d / "corpus")
        a = self.rooms.ingest(self.rid, self.d / "corpus", stop_after=33)
        b = self.rooms.ingest(self.rid, self.d / "corpus")
        self.assertEqual(a.added + b.added, ref_rep.added)
        self.assertEqual(a.duplicates + b.duplicates, ref_rep.duplicates)
        self.assertEqual({n for n, _ in b.failed}, {n for n, _ in ref_rep.failed})

    def test_extraction_runs_concurrently(self):
        real = rooms_mod._extract_one
        active, peak = [0], [0]
        import threading
        lock = threading.Lock()

        def slow(path):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            try:
                return real(path)
            finally:
                with lock:
                    active[0] -= 1
        with mock.patch.object(rooms_mod, "_extract_one", side_effect=slow):
            t = time.time()
            rep = self.rooms.ingest(self.rid, self.d / "corpus", workers=8)
            wall = time.time() - t
        self.assertEqual(rep.added, 60)
        self.assertGreater(peak[0], 1)
        self.assertLess(wall, 60 * 0.05 * 0.6)

    def test_symlink_dir_and_traversal_safety(self):
        outside = self.d / "elsewhere"
        outside.mkdir()
        (outside / "x.txt").write_text("outside")
        os.symlink(outside, self.d / "corpus" / "linkdir")
        rep = self.rooms.ingest(self.rid, self.d / "corpus")
        self.assertIn("linkdir", {n for n, _ in rep.failed})
        self.assertFalse(any("x.txt" in d["path"] for d in self.rooms.documents(self.rid)))

    def test_single_file_and_list_inputs(self):
        rep = self.rooms.ingest(self.rid, [self.d / "corpus" / "bad1.docx", self.d / "corpus" / "memo1.md"])
        self.assertEqual(rep.added, 1)
        self.assertEqual(len(rep.failed), 1)


if __name__ == "__main__":
    unittest.main()
