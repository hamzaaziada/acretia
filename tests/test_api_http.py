import json
import sys
import types
import unittest

from om.api import db
from om.api.http import (ApiError, RequestContext, Response, Route, Router, SSE, SSE_KEEPALIVE, parse_json,
                         parse_multipart, render, sanitize_filename, sse_format)


def h(ctx):
    return {}


class RouteTests(unittest.TestCase):
    def test_match_and_decode(self):
        r = Route("GET", "/api/v1/deals/{deal_id}/deliverables/{name}", h)
        self.assertEqual(r.match("GET", "/api/v1/deals/d1/deliverables/Q3%20model%2Bv2.xlsx"),
                         {"deal_id": "d1", "name": "Q3 model+v2.xlsx"})
        self.assertIsNone(r.match("POST", "/api/v1/deals/d1/deliverables/x"))

    def test_no_match_across_slash(self):
        r = Route("GET", "/a/{x}", h)
        self.assertIsNone(r.match("GET", "/a/b/c"))
        self.assertIsNone(r.match("GET", "/a/"))
        self.assertIsNone(r.match("GET", "/a/b/"))
        self.assertEqual(r.match("GET", "/a/b"), {"x": "b"})

    def test_literal_regex_chars_escaped(self):
        r = Route("GET", "/a.b/{x}", h)
        self.assertIsNone(r.match("GET", "/aXb/1"))

    def test_404_vs_405(self):
        router = Router([Route("GET", "/x/{id}", h), Route("DELETE", "/x/{id}", h)])
        route, params = router.resolve("GET", "/x/1")
        self.assertEqual(params, {"id": "1"})
        with self.assertRaises(ApiError) as c:
            router.resolve("POST", "/x/1")
        self.assertEqual((c.exception.status, c.exception.code), (405, "method_not_allowed"))
        self.assertEqual(c.exception.headers["Allow"], "DELETE, GET")
        with self.assertRaises(ApiError) as c:
            router.resolve("GET", "/nope")
        self.assertEqual((c.exception.status, c.exception.code), (404, "not_found"))

    def test_defaults(self):
        r = Route("get", "/x", h)
        self.assertEqual((r.method, r.role, r.csrf), ("GET", "member", True))


class ContextTests(unittest.TestCase):
    def test_require_order(self):
        for role, need, ok in [("owner", "member", True), ("member", "member", True), ("viewer", "member", False),
                               (None, "viewer", False), ("viewer", "public", True), ("member", "owner", False)]:
            ctx = RequestContext(role=role, org_id="org_1")
            if ok:
                ctx.require(need)
            else:
                with self.assertRaises(ApiError) as c:
                    ctx.require(need)
                self.assertEqual((c.exception.status, c.exception.code), (403, "forbidden"))
                self.assertEqual(c.exception.hint, f"Ask an owner of org_1 for {need} access.")

    def test_audit_delegates(self):
        calls = []
        ctx = RequestContext(_audit=lambda c, a, t, d: calls.append((a, t, d)))
        ctx.audit("x.y", "t", {"k": 1})
        self.assertEqual(calls, [("x.y", "t", {"k": 1})])
        RequestContext().audit("noop")

    def test_error_body(self):
        self.assertEqual(ApiError(400, "c", "m").body(), {"error": {"code": "c", "message": "m"}})
        self.assertEqual(ApiError(400, "c", "m", "do x").body()["error"]["hint"], "do x")


class RenderTests(unittest.TestCase):
    def test_kinds(self):
        s, hd, b = render({"a": "é"})
        self.assertEqual((s, b), (200, '{"a":"é"}'.encode()))
        self.assertTrue(hd["Content-Type"].startswith("application/json"))
        self.assertEqual(render([1, 2])[2], b"[1,2]")
        s, hd, b = render((201, {"ok": True}))
        self.assertEqual((s, b), (201, b'{"ok":true}'))
        s, hd, b = render(Response(200, b"%PDF", "application/pdf", {"Content-Disposition": "attachment"}))
        self.assertEqual((hd["Content-Type"], hd["Content-Disposition"], b), ("application/pdf", "attachment", b"%PDF"))
        sse = SSE(iter([]))
        s, hd, b = render(sse)
        self.assertIs(b, sse)
        self.assertEqual(hd["Content-Type"], "text/event-stream")
        with self.assertRaises(TypeError):
            render(object())


class SseTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(sse_format(7, "job", {"a": 1}), b'id: 7\nevent: job\ndata: {"a":1}\n\n')
        self.assertEqual(sse_format(None, "x", {}), b"event: x\ndata: {}\n\n")
        self.assertEqual(SSE_KEEPALIVE, b": keep-alive\n\n")

    def test_no_raw_newlines_in_data(self):
        out = sse_format("a\nb", "e\nvil", {"t": "line1\nline2\r\nid: 99", "ar": "مرحبا"})
        text = out.decode()
        self.assertTrue(text.endswith("\n\n"))
        lines = text[:-2].split("\n")
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[2].startswith("data: "))
        self.assertEqual(json.loads(lines[2][6:])["t"], "line1\nline2\r\nid: 99")


class ParseJsonTests(unittest.TestCase):
    def test_ok_and_empty(self):
        self.assertEqual(parse_json(b'{"a":1}'), {"a": 1})
        self.assertIsNone(parse_json(b""))

    def test_errors(self):
        for body in (b"{bad", b"\xff\xfe"):
            with self.assertRaises(ApiError) as c:
                parse_json(body)
            self.assertEqual((c.exception.status, c.exception.code), (400, "bad_json"))
            self.assertTrue(c.exception.hint)
        with self.assertRaises(ApiError) as c:
            parse_json(b"[" + b"1," * 10 + b"1]", limit=5)
        self.assertEqual((c.exception.status, c.exception.code), (413, "too_large"))
        self.assertTrue(c.exception.hint)


class MultipartTests(unittest.TestCase):
    def body(self, b="XYZ"):
        return (f'--{b}\r\nContent-Disposition: form-data; name="kind"\r\n\r\nmodel\r\n'
                f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="a b.pdf"\r\n'
                f'Content-Type: application/pdf\r\n\r\n').encode() + b"%PDF\r\n--x\r\n\x00\xff" + f"\r\n--{b}--\r\n".encode()

    def test_happy(self):
        parts = parse_multipart(self.body(), "multipart/form-data; boundary=XYZ", 10_000)
        self.assertEqual(parts[0], ("kind", None, "text/plain", b"model"))
        self.assertEqual(parts[1], ("file", "a b.pdf", "application/pdf", b"%PDF\r\n--x\r\n\x00\xff"))
        parts = parse_multipart(self.body(), 'multipart/form-data; boundary="XYZ"', 10_000)
        self.assertEqual(len(parts), 2)

    def test_missing_boundary(self):
        with self.assertRaises(ApiError) as c:
            parse_multipart(self.body(), "multipart/form-data", 10_000)
        self.assertEqual(c.exception.status, 400)

    def test_oversize(self):
        with self.assertRaises(ApiError) as c:
            parse_multipart(self.body(), "multipart/form-data; boundary=XYZ", 10)
        self.assertEqual((c.exception.status, c.exception.code), (413, "too_large"))


class SanitizeTests(unittest.TestCase):
    def test_adversarial(self):
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename("C:\\x\\y.pdf"), "y.pdf")
        self.assertEqual(sanitize_filename(".htaccess"), "htaccess")
        self.assertEqual(sanitize_filename("تقرير المالية.xlsx"), "تقرير المالية.xlsx")
        self.assertEqual(sanitize_filename("a<b>:c|d?.txt"), "a_b_c_d_.txt")
        self.assertEqual(sanitize_filename("a..b"), "a.b")
        for bad in ("", "...", "/", "..", "   ", None):
            out = sanitize_filename(bad)
            self.assertTrue(out and not out.startswith("."), repr(bad))
        long = sanitize_filename("a" * 500 + ".pdf")
        self.assertLessEqual(len(long), 180)
        self.assertTrue(long.endswith(".pdf"))
        self.assertLessEqual(len(sanitize_filename("b" * 500)), 180)


class DbTests(unittest.TestCase):
    def test_new_id(self):
        i = db.new_id("usr")
        self.assertRegex(i, r"^usr_[0-9a-f]{16}$")
        self.assertNotEqual(i, db.new_id("usr"))
        with self.assertRaises(ValueError):
            db.new_id("deal")

    def test_now(self):
        self.assertRegex(db.now(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_migrate_idempotent(self):
        name = "om.api._fake_schema_mod"
        mod = types.ModuleType(name)
        mod.SCHEMA = "CREATE TABLE IF NOT EXISTS fake_t (id TEXT PRIMARY KEY, org_id TEXT NOT NULL);"
        sys.modules[name] = mod
        try:
            conn = db.connect(":memory:")
            mods = (name, "om.api.does_not_exist_yet")
            self.assertEqual(db.migrate(conn, mods), [name])
            self.assertEqual(db.migrate(conn, mods), [name])
            conn.execute("INSERT INTO fake_t VALUES('a','o')")
            self.assertEqual(db.rows(conn.execute("SELECT * FROM fake_t")), [{"id": "a", "org_id": "o"}])
            sv = db.rows(conn.execute("SELECT module, sha256 FROM schema_versions"))
            self.assertEqual(len(sv), 1)
            self.assertEqual(len(sv[0]["sha256"]), 64)
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            del sys.modules[name]

    def test_migrate_reraises_inner_import_error(self):
        name = "om.api._fake_broken_mod"
        sys.modules.pop(name, None)
        import importlib.abc, importlib.util

        class Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
            def find_spec(self, fullname, path, target=None):
                return importlib.util.spec_from_loader(fullname, self) if fullname == name else None

            def create_module(self, spec):
                return None

            def exec_module(self, module):
                import not_a_real_dependency_xyz  # noqa

        f = Finder()
        sys.meta_path.insert(0, f)
        try:
            with self.assertRaises(ModuleNotFoundError):
                db.migrate(db.connect(":memory:"), (name,))
        finally:
            sys.meta_path.remove(f)

    def test_tx_rollback_and_file_db(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(os.path.join(d, "sub", "x.sqlite"))
            conn.execute("CREATE TABLE t(a)")
            with db.tx(conn):
                conn.execute("INSERT INTO t VALUES(1)")
            with self.assertRaises(RuntimeError):
                with db.tx(conn):
                    conn.execute("INSERT INTO t VALUES(2)")
                    raise RuntimeError
            self.assertEqual([r[0] for r in conn.execute("SELECT a FROM t")], [1])
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            conn.close()


if __name__ == "__main__":
    unittest.main()
