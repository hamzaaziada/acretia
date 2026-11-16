"""Connector tests: synced folder (real disk) and Box / SharePoint / Dropbox against fake APIs."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures_office import docx  # noqa: E402
from om import connectors as C  # noqa: E402
from om.rooms import Rooms  # noqa: E402
from om.search import Index  # noqa: E402

CIM = docx([["Revenue was $12.0 million in FY2025."]])
MODEL = b"Metric,FY2025\nRevenue,12.0\n"


class FakeHTTP:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _hit(self, url):
        self.calls.append(url)
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp(url) if callable(resp) else resp
        raise AssertionError(f"unexpected URL {url}")

    def get_json(self, url):
        return self._hit(url)

    def get_bytes(self, url, headers=None):
        return self._hit(url)

    def post_json(self, url, body, headers=None, raw=False):
        key = url + ("|" + headers["Dropbox-API-Arg"] if headers and "Dropbox-API-Arg" in headers else "")
        return self._hit(key)


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.idx = Index(d / "s.db")
        self.rooms = Rooms(self.idx, d)
        self.rid = self.rooms.create("Deal")

    def tearDown(self):
        self.tmp.cleanup()

    def test_synced_folder_incremental(self):
        src = Path(self.tmp.name) / "BoxDrive" / "Project X"
        (src / "1 Overview").mkdir(parents=True)
        (src / "1 Overview" / "CIM.docx").write_bytes(CIM)
        (src / "model.csv").write_bytes(MODEL)
        cfg = C.add_connector(self.rooms, self.rid, {"type": "synced_folder", "path": str(src)})
        r = C.sync(self.rooms, self.rid)[cfg["id"]]
        self.assertEqual(r["added"], 2)
        r2 = C.sync(self.rooms, self.rid)[cfg["id"]]
        self.assertEqual((r2["added"], r2["unchanged"]), (0, 2))
        (src / "model.csv").write_bytes(MODEL + b"EBITDA,3.1\n")
        os.utime(src / "model.csv", (1, 2))
        r3 = C.sync(self.rooms, self.rid)[cfg["id"]]
        self.assertEqual(r3["updated"], 1)
        self.assertEqual(self.idx.search("EBITDA", {"room": self.rid})["total_documents"], 1)

    def test_box_recursive_paged(self):
        api = "https://api.box.com/2.0"
        routes = {
            f"{api}/folders/123/items": lambda u: ({"total_count": 2, "entries": [
                {"type": "folder", "id": "9", "name": "1 Overview"}]} if "offset=0" in u else {"total_count": 2, "entries": [
                {"type": "file", "id": "77", "name": "model.csv", "size": 30, "sha1": "abc"}]}),
            f"{api}/folders/9/items": {"total_count": 1, "entries": [{"type": "file", "id": "55", "name": "CIM.docx", "sha1": "def"}]},
            f"{api}/files/55/content": CIM, f"{api}/files/77/content": MODEL,
        }
        fake = FakeHTTP(routes)
        cfg = C.add_connector(self.rooms, self.rid, {"type": "box", "folder_id": "123"})
        self.assertEqual(cfg["token_env"], "BOX_ACCESS_TOKEN")
        r = C.sync(self.rooms, self.rid, http_factory=lambda c: fake)[cfg["id"]]
        self.assertEqual(r["added"], 2)
        paths = {d["path"] for d in self.rooms.documents(self.rid)}
        self.assertEqual(paths, {"1 Overview/CIM.docx", "model.csv"})
        fake.calls.clear()
        r2 = C.sync(self.rooms, self.rid, http_factory=lambda c: fake)[cfg["id"]]
        self.assertEqual(r2["unchanged"], 2)
        self.assertFalse(any("/content" in u for u in fake.calls))      # unchanged files are not downloaded

    def test_sharepoint_share_link_and_paging(self):
        g = "https://graph.microsoft.com/v1.0"
        routes = {
            f"{g}/shares/": {"id": "ROOT", "parentReference": {"driveId": "D1"}},
            f"{g}/drives/D1/items/ROOT/children": {"value": [{"id": "F1", "name": "Legal", "folder": {}}],
                                                    "@odata.nextLink": f"{g}/next-page"},
            f"{g}/next-page": {"value": [{"id": "X1", "name": "model.csv", "file": {}, "eTag": "e1"}]},
            f"{g}/drives/D1/items/F1/children": {"value": [{"id": "X2", "name": "CIM.docx", "file": {}, "eTag": "e2"}]},
            f"{g}/drives/D1/items/X1/content": MODEL, f"{g}/drives/D1/items/X2/content": CIM,
        }
        cfg = C.add_connector(self.rooms, self.rid, {"type": "sharepoint", "share_url": "https://contoso.sharepoint.com/:f:/s/deal/abc"})
        r = C.sync(self.rooms, self.rid, http_factory=lambda c: FakeHTTP(routes))[cfg["id"]]
        self.assertEqual(r["added"], 2)
        self.assertIn("Legal/CIM.docx", {d["path"] for d in self.rooms.documents(self.rid)})

    def test_dropbox(self):
        api, content = "https://api.dropboxapi.com/2", "https://content.dropboxapi.com/2"
        routes = {
            f"{api}/files/list_folder": {"entries": [
                {".tag": "folder", "path_display": "/Deals/X/1 Overview"},
                {".tag": "file", "id": "id:1", "path_display": "/Deals/X/1 Overview/CIM.docx", "content_hash": "h1"}],
                "has_more": False},
            f'{content}/files/download|{{"path": "id:1"}}': CIM,
        }
        cfg = C.add_connector(self.rooms, self.rid, {"type": "dropbox", "path": "/Deals/X"})
        r = C.sync(self.rooms, self.rid, http_factory=lambda c: FakeHTTP(routes))[cfg["id"]]
        self.assertEqual(r["added"], 1)
        self.assertEqual(self.rooms.documents(self.rid)[0]["path"], "1 Overview/CIM.docx")

    def test_credentials_never_stored(self):
        with self.assertRaises(ValueError):
            C.add_connector(self.rooms, self.rid, {"type": "box", "folder_id": "1", "token": "secret"})
        with self.assertRaises(SystemExit):   # no token in the environment -> clear message
            os.environ.pop("BOX_ACCESS_TOKEN", None)
            C.add_connector(self.rooms, self.rid, {"type": "box", "folder_id": "1"})
            C.sync(self.rooms, self.rid)


if __name__ == "__main__":
    unittest.main()
