"""Deals, documents (multipart/raw/zip, indexing, page text), library versions, notifications, demo seed."""
import hashlib
import io
import json
import os
import stat
import time
import unittest
import zipfile
from unittest import mock

from om.api import demo, deals, notify
from om.pdfwrite import PDFWriter
try:
    from tests.test_api_auth import Client, PASSWORD, ServerCase  # noqa: F401
except ImportError:
    from test_api_auth import Client, PASSWORD, ServerCase  # noqa: F401


def pdf(*lines, table=False):
    w = PDFWriter()
    y = 740
    for ln in lines:
        w.text(72, y, ln, size=11)
        y -= 16
    if table:
        for label, a, b in (("Revenue", "1,200", "1,100"), ("EBITDA", "310", "280"), ("Net income", "120", "95")):
            w.text(72, y, label, size=10)
            w.text(300, y, a, size=10)
            w.text(420, y, b, size=10)
            y -= 14
    return w.to_bytes()


def multipart(files, fields=None):
    boundary = "----acretiaTestBoundary"
    out = b""
    for k, v in (fields or {}).items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for name, data, ctype in files:
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out, f"multipart/form-data; boundary={boundary}"


def make_zip(entries, symlink=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
        if symlink:
            zi = zipfile.ZipInfo(symlink[0])
            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(zi, symlink[1])
    return buf.getvalue()


class DealCase(ServerCase):
    def setUp(self):
        super().setUp()
        self.org, self.owner_id = self.make_org()
        self.add_user(self.org, "viewer@acme.example", "viewer")
        self.c = self.client("owner@acme.example")
        s, d, _ = self.c.j("POST", "/api/v1/deals", {"name": "Project Test", "target": "Target Co", "sector": "Industrials"})
        self.assertEqual(s, 201, d)
        self.deal = d["deal_id"]

    def upload_multipart(self, files, fields=None, client=None):
        body, ct = multipart(files, fields)
        return (client or self.c).j("POST", f"/api/v1/deals/{self.deal}/documents", raw=body, headers={"Content-Type": ct})

    def wait_indexed(self):
        self.assertTrue(deals.wait_idle(60))

    def docs(self, **q):
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return self.c.j("GET", f"/api/v1/deals/{self.deal}/documents" + (f"?{qs}" if qs else ""))[1]


class DealTests(DealCase):
    def test_create_get_patch_list(self):
        s, d, _ = self.c.j("GET", f"/api/v1/deals/{self.deal}")
        self.assertEqual((s, d["name"], d["target"], d["sector"], d["status"]), (200, "Project Test", "Target Co", "Industrials", "active"))
        for k in ("counts", "definitions", "deliverables", "activity", "memory_version"):
            self.assertIn(k, d)
        s, d, _ = self.c.j("PATCH", f"/api/v1/deals/{self.deal}", {"name": "Project Renamed", "status": "on_hold",
                                                                  "definitions": {"Net Debt": "Borrowings less cash"}})
        self.assertEqual((s, d["name"], d["status"]), (200, "Project Renamed", "on_hold"))
        self.assertEqual(d["definitions"]["Net Debt"], "Borrowings less cash")
        s, d, _ = self.c.j("PATCH", f"/api/v1/deals/{self.deal}", {"status": "bogus"})
        self.assertEqual((s, d["error"]["code"]), (400, "bad_request"))
        items = self.c.j("GET", "/api/v1/deals")[1]["items"]
        self.assertEqual([i["name"] for i in items], ["Project Renamed"])
        self.assertEqual(self.c.j("GET", "/api/v1/deals?q=renam")[1]["items"][0]["deal_id"], self.deal)
        self.assertEqual(self.c.j("GET", "/api/v1/deals?q=zzz")[1]["items"], [])
        self.assertEqual(self.c.j("GET", "/api/v1/deals?status=active")[1]["items"], [])
        v = self.client("viewer@acme.example")
        self.assertEqual(v.j("POST", "/api/v1/deals", {"name": "nope"})[0], 403)
        self.assertEqual(v.j("PATCH", f"/api/v1/deals/{self.deal}", {"name": "nope"})[0], 403)
        self.assertEqual(v.j("GET", f"/api/v1/deals/{self.deal}")[0], 200)

    def test_new_deal_copies_firm_definitions(self):
        self.conn.execute("UPDATE orgs SET settings_json=? WHERE id=?",
                          (json.dumps({"definitions": {"Adjusted EBITDA": "EBITDA before one-offs", "Net Debt": "Debt less cash"}}), self.org))
        s, d, _ = self.c.j("POST", "/api/v1/deals", {"name": "Project Defs", "definitions": {"Net Debt": "Deal override"}})
        self.assertEqual(s, 201)
        self.assertEqual(d["definitions"], {"Adjusted EBITDA": "EBITDA before one-offs", "Net Debt": "Deal override"})
        s, d, _ = self.c.j("POST", "/api/v1/deals", {"name": "Project Defs 2"})
        self.assertEqual(d["definitions"]["Net Debt"], "Debt less cash")

    def test_activity_lists_uploads_and_versions(self):
        self.upload_multipart([("a.pdf", pdf("hello world"), "application/pdf")])
        self.wait_indexed()
        store = self.st.deal_store(self.conn, self.org)
        store.save_deliverable(self.deal, "Model.txt", b"one", "other", "first")
        d = self.c.j("GET", f"/api/v1/deals/{self.deal}")[1]
        kinds = {a["type"] for a in d["activity"]}
        self.assertTrue({"upload", "deliverable", "event"} <= kinds, kinds)
        up = next(a for a in d["activity"] if a["type"] == "upload")
        self.assertEqual((up["title"], up["actor"]), ("a.pdf", "Olive Owner"))
        self.assertEqual(d["counts"]["documents"], 1)
        self.assertEqual(d["counts"]["indexed"], 1)
        self.assertEqual(d["counts"]["deliverables"], 1)


class BoardTests(DealCase):
    def test_board_shape_and_tenancy(self):
        s, d, _ = self.c.j("GET", "/api/v1/deals/board")
        self.assertEqual(s, 200)
        self.assertIn("generated_at", d)
        self.assertEqual([i["deal_id"] for i in d["items"]], [self.deal])
        row = d["items"][0]
        for k in ("name", "target", "sector", "status", "counts", "latest_deliverable", "signals"):
            self.assertIn(k, row)
        self.assertIsNone(row["latest_deliverable"])
        self.assertEqual(row["signals"], [])

    def test_board_reports_failed_document_and_latest_deliverable(self):
        self.upload_multipart([("broken.pdf", b"%PDF-1.4\nthis is not a real pdf\n%%EOF", "application/pdf")])
        self.wait_indexed()
        self.conn.execute("INSERT INTO deal_deliverables(org_id,deal_id,name,version,kind,sha256,size,note,created_at) "
                          "VALUES(?,?,?,?,?,?,?,?,?)", (self.org, self.deal, "model.xlsx", 2, "xlsx", "0" * 64, 10, "", "2026-11-17T10:00:00Z"))
        row = self.c.j("GET", "/api/v1/deals/board")[1]["items"][0]
        self.assertEqual(row["latest_deliverable"]["name"], "model.xlsx")
        self.assertEqual(row["latest_deliverable"]["version"], 2)
        self.assertEqual([s["kind"] for s in row["signals"]], ["doc_failed"])
        self.assertEqual(row["signals"][0]["severity"], "high")

    def test_board_is_scoped_to_the_org(self):
        other, _ = self.make_org("Other Capital", "o@other.example")
        oc = self.client("o@other.example")
        self.assertEqual(oc.j("GET", "/api/v1/deals/board")[1]["items"], [])
        self.assertEqual(len(self.c.j("GET", "/api/v1/deals/board")[1]["items"]), 1)

    def test_board_requires_a_session(self):
        anon = Client(self.port)
        self.assertEqual(anon.j("GET", "/api/v1/deals/board", csrf=False, cookie=False)[0], 401)


class DocumentTests(DealCase):
    def test_multipart_pdf_indexes_with_text_lines_and_tables(self):
        events = notify.subscribe(self.org)
        data = pdf("Facility Agreement", "Change of Control means a person acquiring 30 per cent", table=True)
        s, d, _ = self.upload_multipart([("Facility Agreement.pdf", data, "application/pdf")], {"folder": "02 Legal"})
        self.assertEqual(s, 201, d)
        doc = d["items"][0]
        self.assertEqual((doc["name"], doc["kind"], doc["folder"], doc["size"]), ("Facility Agreement.pdf", "pdf", "02 Legal", len(data)))
        self.assertIn(doc["status"], ("queued", "indexing", "indexed"))
        self.wait_indexed()
        docs = self.docs()
        self.assertEqual(docs["summary"]["total"], 1)
        self.assertEqual(docs["summary"]["indexed"], 1)
        self.assertEqual(docs["summary"]["progress"], 1.0)
        self.assertEqual(docs["folders"], [{"path": "02 Legal", "count": 1}])
        d1 = docs["items"][0]
        self.assertEqual((d1["status"], d1["progress"], d1["pages"], d1["lang"]), ("indexed", 1.0, 1, "en"))
        s, p, _ = self.c.j("GET", f"/api/v1/documents/{doc['id']}/pages/1/text")
        self.assertEqual(s, 200)
        self.assertIn("Change of Control", p["text"])
        self.assertTrue(p["lines"])
        for ln in p["lines"]:
            self.assertEqual(len(ln["bbox_norm"]), 4)
            self.assertTrue(all(0.0 <= v <= 1.0 for v in ln["bbox_norm"]))
            self.assertLess(ln["bbox_norm"][0], ln["bbox_norm"][2])
        self.assertTrue(any("Change of Control" in ln["text"] for ln in p["lines"]))
        self.assertEqual(self.c.j("GET", f"/api/v1/documents/{doc['id']}/pages/2/text")[0], 404)
        self.assertEqual(self.c.j("GET", f"/api/v1/documents/{doc['id']}/pages/abc/text")[0], 404)
        s, one, _ = self.c.j("GET", f"/api/v1/documents/{doc['id']}")
        self.assertEqual((one["status"], one["deal_name"]), ("indexed", "Project Test"))
        # the file comes back byte-identical, inline, with nosniff
        s, h, body = self.c.req("GET", f"/api/v1/documents/{doc['id']}/file")
        self.assertEqual((s, body), (200, data))
        self.assertEqual(h["content-type"], "application/pdf")
        self.assertTrue(h["content-disposition"].startswith("inline"))
        self.assertEqual(h["x-content-type-options"], "nosniff")
        # document events: per-file status, overall progress
        seen = []
        while True:
            item = events.get(timeout=0.05)
            if item is None:
                break
            seen.append(item)
        events.close()
        docs_ev = [d for _i, ev, d in seen if ev == "document"]
        self.assertTrue(docs_ev)
        self.assertEqual(docs_ev[-1]["status"], "indexed")
        self.assertEqual(docs_ev[-1]["overall"]["progress"], 1.0)
        self.assertIn("queued", {e["status"] for e in docs_ev})

    def test_raw_upload_with_x_filename_and_odd_names(self):
        s, d, _ = self.c.j("POST", f"/api/v1/deals/{self.deal}/documents", raw=pdf("raw upload text"),
                           headers={"X-Filename": "..%2F..%2Fetc%2Fpasswd%20report.pdf", "Content-Type": "application/pdf"})
        self.assertEqual(s, 201, d)
        name = d["items"][0]["name"]
        self.assertNotIn("/", name)
        self.assertNotIn("..", name)
        self.wait_indexed()
        s, d, _ = self.c.j("POST", f"/api/v1/deals/{self.deal}/documents", raw=pdf("x"))
        self.assertEqual((s, d["error"]["code"]), (400, "no_file"))
        self.assertTrue(d["error"]["hint"])

    def test_unsupported_and_dangerous_types_are_refused(self):
        for name, data in (("evil.pdf", b"<html><script>alert(1)</script></html>"), ("a.exe", b"MZ\x90\x00\x03\x00"),
                           ("elf.txt", b"\x7fELF\x01\x01\x01\x00")):
            s, d, _ = self.upload_multipart([(name, data, "application/pdf")])
            self.assertEqual((s, d["error"]["code"]), (415, "unsupported_type"), name)
            self.assertTrue(d["error"]["hint"])
        # a mix keeps the good file and reports the skipped one
        s, d, _ = self.upload_multipart([("ok.pdf", pdf("fine"), "application/pdf"), ("bad.exe", b"MZ\x90\x00", "application/octet-stream")])
        self.assertEqual((s, d["count"], d["skipped"][0]["name"]), (201, 1, "bad.exe"))
        self.wait_indexed()
        self.assertEqual(self.c.j("POST", f"/api/v1/deals/{self.deal}/documents", raw=b"%PDF-1.4", headers={"X-Filename": "x.pdf"},
                                  csrf=False)[0], 403)

    def test_viewer_cannot_upload(self):
        v = self.client("viewer@acme.example")
        s, d, _ = self.upload_multipart([("a.pdf", pdf("x"), "application/pdf")], client=v)
        self.assertEqual(s, 403)

    def test_corrupt_pdf_fails_with_hint_and_notification(self):
        events = notify.subscribe(self.org)
        s, d, _ = self.upload_multipart([("broken.pdf", b"%PDF-1.4\nthis is not a real pdf\n%%EOF", "application/pdf")])
        self.assertEqual(s, 201, d)
        self.wait_indexed()
        doc = self.docs()["items"][0]
        self.assertEqual(doc["status"], "failed")
        self.assertTrue(doc["error"])
        self.assertTrue(doc["hint"])
        self.assertEqual(self.docs()["summary"]["failed"], 1)
        s, p, _ = self.c.j("GET", f"/api/v1/documents/{doc['id']}/pages/1/text")
        self.assertEqual((s, p["error"]["code"]), (409, "not_indexed"))
        s, n, _ = self.c.j("GET", "/api/v1/notifications?unread=1")
        fail = [x for x in n["items"] if x["kind"] == "document_failed"]
        self.assertEqual(len(fail), 1)
        self.assertIn("broken.pdf", fail[0]["title"])
        self.assertEqual(fail[0]["link"], f"/deals/{self.deal}/docs/{doc['id']}")
        self.assertEqual(n["unread_count"], 1)
        s, _, _ = self.c.j("POST", f"/api/v1/notifications/{fail[0]['id']}/read", {})
        self.assertEqual(s, 200)
        self.assertEqual(self.c.j("GET", "/api/v1/notifications?unread=1")[1]["items"], [])
        self.assertEqual(self.c.j("POST", "/api/v1/notifications/read-all", {})[0], 200)
        self.assertIn("failed", {e["status"] for _i, ev, e in iter(lambda: events.get(timeout=0.05), None) if ev == "document"})
        events.close()

    def test_text_office_and_arabic_documents(self):
        arabic = "تقرير مجلس الإدارة السنوي للشركة المصرية للكابلات والمعدات الكهربائية. الإيرادات ارتفعت هذا العام.\n" * 3
        docx = io.BytesIO()
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                                            "<w:p><w:r><w:t>Term sheet clause one</w:t></w:r></w:p></w:body></w:document>")
        s, d, _ = self.upload_multipart([("minutes-ar.txt", arabic.encode("utf-8"), "text/plain"),
                                         ("terms.docx", docx.getvalue(), "application/octet-stream"),
                                         ("prices.csv", b"a,b,c,d\n1,2,3,4\n5,6,7,8\n", "text/csv"),
                                         ("mail.eml", b"From: a@b.example\nSubject: Update\n\nHello team", "message/rfc822")])
        self.assertEqual((s, d["count"]), (201, 4), d)
        self.wait_indexed()
        by = {x["name"]: x for x in self.docs()["items"]}
        self.assertEqual(by["minutes-ar.txt"]["lang"], "ar")
        self.assertEqual(by["terms.docx"]["kind"], "docx")
        self.assertEqual(by["mail.eml"]["kind"], "eml")
        for x in by.values():
            self.assertEqual(x["status"], "indexed", x)
        s, p, _ = self.c.j("GET", f"/api/v1/documents/{by['terms.docx']['id']}/pages/1/text")
        self.assertIn("Term sheet clause one", p["text"])
        s, p, _ = self.c.j("GET", f"/api/v1/documents/{by['mail.eml']['id']}/pages/1/text")
        self.assertIn("Hello team", p["text"])
        s, h, body = self.c.req("GET", f"/api/v1/documents/{by['terms.docx']['id']}/file")
        self.assertTrue(h["content-disposition"].startswith("attachment"))

    def test_xlsx_is_indexed_with_tables(self):
        from om import xlsx
        wb = xlsx.Workbook()
        sh = wb.sheet("Summary")
        sh.set("A1", "Revenue")
        sh.set("B1", 1200)
        data = wb.to_bytes() if hasattr(wb, "to_bytes") else None
        if data is None:
            self.skipTest("om.xlsx.Workbook has no to_bytes in this build")
        s, d, _ = self.upload_multipart([("model.xlsx", data, "application/octet-stream")])
        self.assertEqual(s, 201, d)
        self.wait_indexed()
        doc = self.docs()["items"][0]
        self.assertEqual((doc["kind"], doc["status"]), ("xlsx", "indexed"))

    def test_delete_document(self):
        self.upload_multipart([("a.pdf", pdf("delete me"), "application/pdf")])
        self.wait_indexed()
        did = self.docs()["items"][0]["id"]
        self.assertEqual(self.c.j("DELETE", f"/api/v1/documents/{did}")[0], 200)
        self.assertEqual(self.c.j("GET", f"/api/v1/documents/{did}")[0], 404)
        self.assertEqual(self.docs()["summary"]["total"], 0)


class ZipTests(DealCase):
    def post_zip(self, data, **kw):
        return self.c.j("POST", f"/api/v1/deals/{self.deal}/documents", raw=data,
                        headers={"X-Filename": "dataroom.zip", "Content-Type": "application/zip", **kw})

    def test_zip_with_folders(self):
        z = make_zip([("01 Financials/FY23/report.pdf", pdf("annual report")), ("01 Financials/budget.pdf", pdf("budget")),
                      ("02 Legal/spa.pdf", pdf("sale and purchase agreement")), ("root.pdf", pdf("root doc")),
                      ("__MACOSX/._root.pdf", b"junk"), ("02 Legal/.DS_Store", b"junk"), ("notes/readme.exe", b"MZ\x90\x00")])
        s, d, _ = self.post_zip(z)
        self.assertEqual(s, 201, d)
        self.assertEqual(d["count"], 4)
        self.assertEqual([x["name"] for x in d["skipped"]], ["readme.exe"])
        self.wait_indexed()
        docs = self.docs()
        folders = {i["name"]: i["folder"] for i in docs["items"]}
        self.assertEqual(folders, {"report.pdf": "01 Financials/FY23", "budget.pdf": "01 Financials", "spa.pdf": "02 Legal", "root.pdf": ""})
        self.assertEqual({f["path"]: f["count"] for f in docs["folders"]},
                         {"": 1, "01 Financials": 1, "01 Financials/FY23": 1, "02 Legal": 1})
        self.assertEqual([i["name"] for i in self.docs(folder="01%20Financials")["items"]], ["budget.pdf", "report.pdf"])
        self.assertEqual(docs["summary"]["indexed"], 4)

    def test_nested_zip_one_level_only(self):
        inner = make_zip([("deep/a.pdf", pdf("inner a"))])
        s, d, _ = self.post_zip(make_zip([("outer/inner.zip", inner), ("top.pdf", pdf("top"))]))
        self.assertEqual((s, d["count"]), (201, 2), d)
        self.wait_indexed()
        self.assertIn("outer/inner/deep", {i["folder"] for i in self.docs()["items"]})
        deeper = make_zip([("l2.zip", make_zip([("l3.zip", make_zip([("a.pdf", pdf("x"))]))]))])
        s, d, _ = self.post_zip(deeper)
        self.assertEqual((s, d["error"]["code"]), (400, "unsafe_archive"))

    def test_zipslip_absolute_symlink_rejected(self):
        for name, z in (("slip", make_zip([("../../evil.pdf", pdf("evil"))])),
                        ("deep slip", make_zip([("a/../../evil.pdf", pdf("evil"))])),
                        ("absolute", make_zip([("/etc/evil.pdf", pdf("evil"))])),
                        ("backslash", make_zip([("..\\..\\evil.pdf", pdf("evil"))])),
                        ("drive", make_zip([("C:/evil.pdf", pdf("evil"))])),
                        ("symlink", make_zip([("ok.pdf", pdf("ok"))], symlink=("link.pdf", "/etc/passwd")))):
            s, d, _ = self.post_zip(z)
            self.assertEqual((s, d["error"]["code"]), (400, "unsafe_archive"), name)
            self.assertTrue(d["error"]["hint"], name)
        self.assertEqual(self.docs()["summary"]["total"], 0, "a rejected archive must add nothing")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "..", "evil.pdf")))

    def test_zip_bomb_and_entry_limits_rejected(self):
        bomb = make_zip([("zeros.txt", b"\x00" * (8 * 1024 * 1024))])
        self.assertLess(len(bomb), 100_000)
        s, d, _ = self.post_zip(bomb)
        self.assertEqual((s, d["error"]["code"]), (400, "unsafe_archive"))
        self.assertIn("ratio", d["error"]["message"])
        many = io.BytesIO()
        with zipfile.ZipFile(many, "w", zipfile.ZIP_STORED) as z:
            for i in range(10_001):
                z.writestr(f"f{i}.txt", b"x")
        s, d, _ = self.post_zip(many.getvalue())
        self.assertEqual((s, d["error"]["code"]), (400, "unsafe_archive"))
        self.assertIn("too many", d["error"]["message"])
        self.assertEqual(self.docs()["summary"]["total"], 0)

    def test_fifty_pdf_zip_indexes_with_progress(self):
        z = make_zip([(f"folder{i % 5}/doc{i:02d}.pdf", pdf(f"Document number {i}", "Revenue 100 200")) for i in range(50)])
        t0 = time.time()
        s, d, _ = self.post_zip(z)
        self.assertEqual((s, d["count"]), (201, 50))
        self.assertTrue(deals.wait_idle(120))
        docs = self.docs(limit=200)
        self.assertEqual(docs["summary"], {"total": 50, "indexed": 50, "indexing": 0, "queued": 0, "failed": 0, "progress": 1.0})
        # 90 s on a developer machine; shared GitHub runners are ~2x slower, so CI gets a looser bar.
        self.assertLess(time.time() - t0, 180 if os.environ.get("CI") else 90)


class LibraryTests(DealCase):
    def test_versions_diff_undo_restore_byte_identical(self):
        store = self.st.deal_store(self.conn, self.org)
        blobs = [b"line one\nline two\n", b"line one\nline two changed\n", b"line one\nline two changed\nline three\n"]
        for i, b in enumerate(blobs):
            store.save_deliverable(self.deal, "Memo v.txt", b, "other", f"edit {i}")
        base = f"/api/v1/deals/{self.deal}/deliverables"
        s, d, _ = self.c.j("GET", base)
        self.assertEqual((s, d["items"][0]["name"], d["items"][0]["latest_version"], d["items"][0]["versions"]), (200, "Memo v.txt", 3, 3))
        s, d, _ = self.c.j("GET", base + "/Memo%20v.txt/versions")
        self.assertEqual([v["version"] for v in d["items"]], [3, 2, 1])
        s, h, body = self.c.req("GET", base + "/Memo%20v.txt/versions/2/download")
        self.assertEqual((s, body), (200, blobs[1]))
        self.assertEqual(h["x-content-sha256"], hashlib.sha256(blobs[1]).hexdigest())
        self.assertIn("attachment", h["content-disposition"])
        s, d, _ = self.c.j("GET", base + "/Memo%20v.txt/diff?a=1&b=3")
        self.assertEqual((s, d["identical"]), (200, False))
        self.assertTrue(d["changes"][0]["unified"])
        self.assertTrue(any("line three" in ln for ln in d["changes"][0]["unified"]))
        self.assertEqual(self.c.j("GET", base + "/Memo%20v.txt/diff?a=1&b=9")[0], 404)
        self.assertEqual(self.c.j("GET", base + "/Memo%20v.txt/diff?a=x&b=1")[0], 400)
        s, d, _ = self.c.j("POST", base + "/Memo%20v.txt/undo", {})
        self.assertEqual((s, d["version"]), (201, 4))
        self.assertEqual(self.c.req("GET", base + "/Memo%20v.txt/versions/4/download")[2], blobs[1])  # byte-identical to v2
        s, d, _ = self.c.j("POST", base + "/Memo%20v.txt/restore", {"version": 1})
        self.assertEqual((s, d["version"]), (201, 5))
        self.assertEqual(self.c.req("GET", base + "/Memo%20v.txt/versions/5/download")[2], blobs[0])
        self.assertEqual(self.c.j("POST", base + "/Memo%20v.txt/restore", {"version": 99})[0], 404)
        self.assertEqual(self.c.j("POST", base + "/Memo%20v.txt/restore", {})[0], 400)
        single = self.c.j("POST", f"/api/v1/deals/{self.deal}/deliverables/Nothing/undo", {})
        self.assertEqual(single[0], 404)
        store.save_deliverable(self.deal, "Solo.txt", b"only", "other")
        s, d, _ = self.c.j("POST", base + "/Solo.txt/undo", {})
        self.assertEqual((s, d["error"]["code"]), (409, "nothing_to_undo"))
        v = self.client("viewer@acme.example")
        self.assertEqual(v.j("POST", base + "/Memo%20v.txt/undo", {})[0], 403)
        self.assertEqual(v.j("GET", base + "/Memo%20v.txt/versions")[0], 200)

    def test_org_library_listing_filters(self):
        store = self.st.deal_store(self.conn, self.org)
        s, d2, _ = self.c.j("POST", "/api/v1/deals", {"name": "Project Two"})
        store.save_deliverable(self.deal, "Comps.xlsx", b"PK-not-really", "xlsx")
        store.save_deliverable(self.deal, "Comps.xlsx", b"PK-not-really-2", "xlsx")
        store.save_deliverable(self.deal, "Notes.txt", b"notes", "other")
        store.save_deliverable(d2["deal_id"], "Profile deck.pptx", b"PK-deck", "pptx")
        s, lib, _ = self.c.j("GET", "/api/v1/library")
        names = {(i["name"], i["deal_name"], i["latest_version"], i["versions"]) for i in lib["items"]}
        self.assertEqual(names, {("Comps.xlsx", "Project Test", 2, 2), ("Notes.txt", "Project Test", 1, 1),
                                 ("Profile deck.pptx", "Project Two", 1, 1)})
        self.assertEqual(sorted(lib["kinds"]), ["other", "pptx", "xlsx"])
        self.assertEqual([i["name"] for i in self.c.j("GET", "/api/v1/library?kind=pptx")[1]["items"]], ["Profile deck.pptx"])
        self.assertEqual({i["name"] for i in self.c.j("GET", f"/api/v1/library?deal_id={self.deal}")[1]["items"]}, {"Comps.xlsx", "Notes.txt"})
        self.assertEqual([i["name"] for i in self.c.j("GET", "/api/v1/library?q=deck")[1]["items"]], ["Profile deck.pptx"])
        page = self.c.j("GET", "/api/v1/library?limit=2")[1]
        self.assertEqual((len(page["items"]), page["next_cursor"]), (2, "2"))
        self.assertEqual(len(self.c.j("GET", "/api/v1/library?limit=2&cursor=2")[1]["items"]), 1)
        self.assertEqual(self.c.j("GET", "/api/v1/library?q=%25")[1]["items"], [])  # LIKE wildcards are escaped


class DemoTests(ServerCase):
    def test_seed_is_idempotent_and_usable(self):
        with mock.patch.dict(os.environ, {"ACRETIA_DEMO_PASSWORD": "demo-test-pass-1"}):
            r1 = demo.seed(self.tmp, self.st)
            r2 = demo.seed(self.tmp, self.st)
        self.assertEqual(r1["deals"], r2["deals"])
        self.assertEqual(r1["documents_added"], 12)
        self.assertEqual(r2["documents_added"], 0)
        c = self.conn
        self.assertEqual(c.execute("SELECT COUNT(*) FROM orgs").fetchone()[0], 1)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM users").fetchone()[0], 3)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM deals").fetchone()[0], 2)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 12)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM documents WHERE status='indexed'").fetchone()[0], 12)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM notifications WHERE kind='welcome'").fetchone()[0], 1)
        roles = {r["email"]: r["role"] for r in c.execute("SELECT u.email, m.role FROM users u JOIN memberships m ON m.user_id=u.id")}
        self.assertEqual(roles, {"owner@meridian.example": "owner", "analyst@meridian.example": "member", "lp@meridian.example": "viewer"})
        names = {r[0] for r in c.execute("SELECT name FROM deals")}
        self.assertEqual(names, {"Project Nile \u2014 ElSewedy Electric", "Project Atlas \u2014 Apple Inc."})
        # sign in over HTTP with the demo password and browse
        owner = Client(self.port)
        s, d, _ = owner.login("owner@meridian.example", "demo-test-pass-1")
        self.assertEqual((s, d["org"]["name"], d["role"]), (200, "Meridian Capital Partners", "owner"))
        deals_list = owner.j("GET", "/api/v1/deals")[1]["items"]
        self.assertEqual(len(deals_list), 2)
        nile = next(x for x in deals_list if "Nile" in x["name"])
        detail = owner.j("GET", f"/api/v1/deals/{nile['deal_id']}")[1]
        self.assertEqual(detail["counts"]["documents"], 6)
        self.assertIn("Adjusted EBITDA", detail["definitions"])
        self.assertIn("Net Debt", detail["definitions"])
        self.assertEqual(detail["deliverables"][0]["latest_version"], 2)
        docs = owner.j("GET", f"/api/v1/deals/{nile['deal_id']}/documents")[1]
        self.assertEqual(docs["summary"]["indexed"], 6)
        self.assertEqual(len(docs["folders"]), 5)
        fac = next(x for x in docs["items"] if x["name"].startswith("Facility Agreement"))
        page = owner.j("GET", f"/api/v1/documents/{fac['id']}/pages/1/text")[1]
        self.assertIn("Change of Control", page["text"])
        self.assertTrue(page["lines"] and len(page["lines"][0]["bbox_norm"]) == 4)
        ar = next(x for x in docs["items"] if x["name"].startswith("Annual Report"))
        page = owner.j("GET", f"/api/v1/documents/{ar['id']}/pages/1/text")[1]
        self.assertIn("68,420", page["text"])
        self.assertTrue(page["tables"], "income statement should be detected as a table")
        # viewer and member can sign in; viewer cannot mutate
        lp = Client(self.port)
        self.assertEqual(lp.login("lp@meridian.example", "demo-test-pass-1")[0], 200)
        self.assertEqual(lp.j("POST", "/api/v1/deals", {"name": "x"})[0], 403)
        self.assertTrue(self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] > 0)


if __name__ == "__main__":
    unittest.main()
