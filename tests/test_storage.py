import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock
from datetime import datetime, timezone

from om import storage as st

AK = "AKIAIOSFODNN7EXAMPLE"
SK = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
EMPTY = hashlib.sha256(b"").hexdigest()


class LocalBlobTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            b = st.LocalBlobStore(os.path.join(d, "blobs"))
            k = b.put(b"hello")
            self.assertEqual(k, hashlib.sha256(b"hello").hexdigest())
            self.assertEqual(b.get(k), b"hello")
            self.assertTrue(b.exists(k))
            self.assertEqual(b.put(b"hello"), k)
            self.assertEqual(b.list(), [k])
            self.assertTrue(os.path.isfile(os.path.join(d, "blobs", k[:2], k[2:4], k)))
            self.assertTrue(b.delete(k))
            self.assertFalse(b.delete(k))
            self.assertFalse(b.exists(k))
            with self.assertRaises(KeyError):
                b.get(k)

    def test_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            b = st.LocalBlobStore(d)
            for bad in ("../../etc/passwd", "a" * 63, "A" * 64, "/" + "a" * 63, "", "g" * 64):
                with self.assertRaises(ValueError):
                    b.get(bad)
                with self.assertRaises(ValueError):
                    b.delete(bad)


class SigV4Tests(unittest.TestCase):
    def test_aws_get_object_vector(self):
        auth = st.sigv4_authorization(
            "GET", "examplebucket.s3.amazonaws.com", "/test.txt",
            {"Range": "bytes=0-9", "x-amz-content-sha256": EMPTY, "x-amz-date": "20130524T000000Z"},
            EMPTY, AK, SK, "us-east-1", "20130524T000000Z")
        self.assertIn("SignedHeaders=host;range;x-amz-content-sha256;x-amz-date", auth)
        self.assertTrue(auth.endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"))
        self.assertIn(f"Credential={AK}/20130524/us-east-1/s3/aws4_request", auth)

    def test_aws_presigned_vector(self):
        url = st.sigv4_presign("GET", "examplebucket.s3.amazonaws.com", "/test.txt", 86400, AK, SK,
                               "us-east-1", "20130524T000000Z")
        self.assertTrue(url.endswith("X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"))
        self.assertIn("X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request", url)
        self.assertIn("X-Amz-Expires=86400", url)


class FakeS3:
    def __init__(self):
        self.objs, self.calls = {}, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers))
        path = url.split("?")[0].split("//", 1)[1].split("/", 1)[1]
        bucket, _, key = path.partition("/")
        if method == "PUT":
            self.objs[key] = body
            return 200, {}, b""
        if method == "GET" and not key:
            xml = "".join(f"<Contents><Key>{k}</Key></Contents>" for k in sorted(self.objs))
            return 200, {}, ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                             f"<IsTruncated>false</IsTruncated>{xml}</ListBucketResult>").encode()
        if method in ("GET", "HEAD"):
            return (200, {}, self.objs[key]) if key in self.objs else (404, {}, b"")
        if method == "DELETE":
            self.objs.pop(key, None)
            return 204, {}, b""
        return 400, {}, b""


class S3Tests(unittest.TestCase):
    def make(self):
        t = FakeS3()
        clock = lambda: datetime(2013, 5, 24, tzinfo=timezone.utc)
        return st.S3BlobStore("http://minio:9000", "bkt", "us-east-1", AK, SK, transport=t, clock=clock), t

    def test_put_get_list_delete(self):
        s, t = self.make()
        k = s.put(b"data")
        self.assertEqual(s.get(k), b"data")
        self.assertTrue(s.exists(k))
        self.assertEqual(s.list(), [k])
        self.assertTrue(s.delete(k))
        self.assertFalse(s.exists(k))
        with self.assertRaises(KeyError):
            s.get(k)
        m, url, h = t.calls[0]
        self.assertEqual(url, f"http://minio:9000/bkt/{k}")
        self.assertTrue(h["Authorization"].startswith(f"AWS4-HMAC-SHA256 Credential={AK}/20130524/us-east-1/s3/"))
        self.assertEqual(h["x-amz-content-sha256"], hashlib.sha256(b"data").hexdigest())

    def test_secret_not_in_repr_and_bad_key(self):
        s, _ = self.make()
        self.assertNotIn(SK, repr(s))
        self.assertNotIn(SK, str(s.presign_url("GET", "a" * 64)))
        with self.assertRaises(ValueError):
            s.get("../x")

    def test_presign(self):
        s, _ = self.make()
        u = s.presign_url("GET", "a" * 64, 60)
        self.assertTrue(u.startswith("http://minio:9000/bkt/" + "a" * 64 + "?X-Amz-Algorithm="))
        self.assertIn("X-Amz-Expires=60", u)

    def test_missing_credentials(self):
        old = {k: os.environ.pop(k, None) for k in ("ACRETIA_S3_ACCESS_KEY", "ACRETIA_S3_SECRET_KEY")}
        try:
            with self.assertRaises(st.StorageError):
                st.S3BlobStore("h", "b")
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


class KVTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.now = [1000.0]
        self.kv = st.SQLiteKV(os.path.join(self.d.name, "kv.sqlite"), clock=lambda: self.now[0])

    def tearDown(self):
        self.kv.close()
        self.d.cleanup()

    def test_kv(self):
        self.assertIsNone(self.kv.get("a"))
        self.kv.set("a", "x")
        self.assertEqual(self.kv.get("a"), "x")
        self.assertEqual(self.kv.incr("n"), 1)
        self.assertEqual(self.kv.incr("n", 4), 5)
        self.assertTrue(self.kv.delete("a"))
        self.assertFalse(self.kv.delete("a"))

    def test_queue_fifo_ack_nack_lease(self):
        for p in (b"1", b"2", b"3"):
            self.kv.enqueue("q", p)
        a = self.kv.dequeue("q", lease=10)
        self.assertEqual(a.payload, b"1")
        self.assertEqual(self.kv.dequeue("q", lease=10).payload, b"2")
        self.assertTrue(self.kv.ack(a))
        self.assertEqual(self.kv.qsize("q"), 2)
        c = self.kv.dequeue("q", lease=10)
        self.assertEqual(c.payload, b"3")
        self.assertIsNone(self.kv.dequeue("q"))
        self.kv.nack(c)  # immediately visible again
        self.assertEqual(self.kv.dequeue("q", lease=10).attempts, 2)
        self.now[0] += 11  # leases expire
        got = [self.kv.dequeue("q", lease=10) for _ in range(3)]
        self.assertEqual([g.payload for g in got if g], [b"2", b"3"])
        self.assertIsNone(self.kv.dequeue("other"))

    def test_concurrent_dequeue_once(self):
        n = 200
        for i in range(n):
            self.kv.enqueue("q", str(i))
        other = st.SQLiteKV(os.path.join(self.d.name, "kv.sqlite"), clock=lambda: self.now[0])
        seen, lock = [], threading.Lock()

        def worker(kv):
            while True:
                it = kv.dequeue("q", lease=1000)
                if it is None:
                    return
                with lock:
                    seen.append(it.payload)
                kv.ack(it)

        ts = [threading.Thread(target=worker, args=(self.kv if i % 2 else other,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        other.close()
        self.assertEqual(len(seen), n)
        self.assertEqual(len(set(seen)), n)

    def test_lease_tokens_unique_and_stale_ack_rejected(self):
        self.kv.enqueue("q", b"job")
        a = self.kv.dequeue("q", lease=10)
        self.now[0] += 11  # A's lease expires; B takes the job
        b = self.kv.dequeue("q", lease=10)
        self.assertNotEqual(a.token, b.token)
        self.assertFalse(self.kv.ack(a))          # stale worker: must not delete the live lease
        self.assertFalse(self.kv.nack(a))
        self.assertEqual(self.kv.qsize("q"), 1)
        self.assertTrue(self.kv.ack(b))
        self.assertEqual(self.kv.qsize("q"), 0)

    def test_bare_int_ack_nack_raises_and_keeps_live_lease(self):
        self.kv.enqueue("q", b"job")
        a = self.kv.dequeue("q", lease=10)
        self.now[0] += 11
        b = self.kv.dequeue("q", lease=10)            # B now holds the item
        for bad in (a.id, str(a.id), None, (a.id,), (a.id, None)):
            with self.assertRaises(TypeError) as cm:
                self.kv.ack(bad)
            self.assertIn("Lease", str(cm.exception))
            with self.assertRaises(TypeError):
                self.kv.nack(bad)
        self.assertEqual(self.kv.qsize("q"), 1)       # still there, still leased by B
        self.assertTrue(self.kv.ack((b.id, b.token)))  # explicit (id, token) is fenced and allowed
        self.assertEqual(self.kv.qsize("q"), 0)

    def test_dead_letter_after_max_attempts_and_requeue(self):
        i = self.kv.enqueue("q", b"poison", max_attempts=3)
        for n in range(3):
            lease = self.kv.dequeue("q", lease=10)
            self.assertEqual(lease.attempts, n + 1)
            self.now[0] += 11  # worker crashes: lease expires
        self.assertIsNone(self.kv.dequeue("q"))
        self.assertEqual(self.kv.qsize("q"), 0)
        d = self.kv.dlq_list("q")
        self.assertEqual([(x["id"], x["payload"], x["attempts"]) for x in d], [(i, b"poison", 3)])
        self.assertIn("max attempts", d[0]["last_error"])
        self.assertEqual(self.kv.dlq_requeue("q"), 1)
        self.assertEqual(self.kv.dlq_list("q"), [])
        again = self.kv.dequeue("q", lease=10)
        self.assertEqual((again.payload, again.attempts), (b"poison", 1))

    def test_nack_with_error_goes_to_dlq_on_last_attempt(self):
        self.kv.enqueue("q", b"x", max_attempts=2)
        self.assertTrue(self.kv.nack(self.kv.dequeue("q"), error="boom1"))
        l2 = self.kv.dequeue("q")
        self.assertTrue(self.kv.nack(l2, error="boom2"))
        self.assertIsNone(self.kv.dequeue("q"))
        self.assertEqual(self.kv.dlq_list("q")[0]["last_error"], "boom2")
        self.assertFalse(self.kv.ack(l2))
        self.assertEqual(self.kv.dlq_requeue("q", self.kv.dlq_list("q")[0]["id"]), 1)

    def test_default_max_attempts_is_five(self):
        self.kv.enqueue("q", b"x")
        for _ in range(5):
            self.assertIsNotNone(self.kv.dequeue("q", lease=1))
            self.now[0] += 2
        self.assertIsNone(self.kv.dequeue("q"))
        self.assertEqual(len(self.kv.dlq_list("q")), 1)

    def test_old_database_is_migrated(self):
        import sqlite3
        path = os.path.join(self.d.name, "old.sqlite")
        c = sqlite3.connect(path)
        c.executescript("CREATE TABLE queue(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,"
                        " payload BLOB NOT NULL, visible_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);"
                        "INSERT INTO queue(name,payload,visible_at) VALUES('q',x'41',0);")
        c.commit()
        c.close()
        kv = st.SQLiteKV(path, clock=lambda: self.now[0])
        self.addCleanup(kv.close)
        lease = kv.dequeue("q")
        self.assertEqual(lease.payload, b"A")
        self.assertTrue(kv.ack(lease))

    def test_redis_encoding_has_token_fencing(self):
        self.assertIn("':t'", st.RedisKV._DEQ)
        self.assertIn("ARGV[2]", st.RedisKV._ACK)
        self.assertIn("then return 0", st.RedisKV._ACK)
        self.assertIn("then return 0", st.RedisKV._NACK)
        self.assertIn("KEYS[3]", st.RedisKV._DEQ)

    def test_redis_commands_offline(self):
        sent = []

        class Fake(st.RedisKV):
            def __init__(self):
                self._clock = lambda: 100.0

            def _cmd(self, *a):
                sent.append(a)
                if a[0] == "EVAL" and a[1] == st.RedisKV._DEQ:
                    return [b"7", b"p", 1]
                return {"INCR": 7}.get(a[0], 1)

        r = Fake()
        self.assertEqual(r.enqueue("q", b"p", max_attempts=2), 7)
        self.assertIn(("HSET", "q:q:data", "7", b"p", "7:max", "2"), sent)
        lease = r.dequeue("q", lease=5)
        self.assertEqual((lease.id, lease.queue, len(lease.token)), (7, "q", 32))
        ev = [a for a in sent if a[0] == "EVAL"][0]
        self.assertEqual(ev[1], st.RedisKV._DEQ)
        self.assertIn(lease.token, ev)
        self.assertTrue(r.ack(lease))
        ack = sent[-1]
        self.assertEqual((ack[1], ack[-2:]), (st.RedisKV._ACK, ("7", lease.token)))
        r.nack(lease, error="e")
        self.assertIn(lease.token, sent[-1])
        with self.assertRaises(st.StorageError):
            r.ack(st.Lease(7, b"", 1, "q"))  # no token -> refused
        for bad in (7, "7", (7, "tok")):
            with self.assertRaises(TypeError):
                r.ack(bad)
            with self.assertRaises(TypeError):
                r.nack(bad)

    def test_redis_unreachable_is_clear(self):
        with self.assertRaises(st.StorageError):
            st.RedisKV("redis://127.0.0.1:1/0", timeout=0.2)

    def test_resp_encode(self):
        self.assertEqual(st.RedisKV.encode("SET", "k", b"v"), b"*3\r\n$3\r\nSET\r\n$1\r\nk\r\n$1\r\nv\r\n")


class DBTests(unittest.TestCase):
    def test_sqlite_pragmas(self):
        with tempfile.TemporaryDirectory() as d:
            for dsn in (os.path.join(d, "a.sqlite"), "sqlite:///" + os.path.join(d, "b.sqlite")):
                db = st.connect(dsn)
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertGreaterEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 1000)
                db.close()
            self.assertTrue(os.path.exists(os.path.join(d, "b.sqlite")))

    def test_postgres_needs_psycopg(self):
        try:
            import psycopg  # noqa: F401
            self.skipTest("psycopg installed")
        except ImportError:
            with self.assertRaises(st.StorageError):
                st.connect("postgres://u:p@h/db")


class FromEnvTests(unittest.TestCase):
    def test_local_default(self):
        with tempfile.TemporaryDirectory() as d:
            s = st.from_env({"ACRETIA_BLOB_ROOT": d + "/b", "ACRETIA_KV_PATH": d + "/kv.db", "ACRETIA_DB": d + "/m.db"})
            self.assertIsInstance(s.blobs, st.LocalBlobStore)
            self.assertIsInstance(s.kv, st.SQLiteKV)
            self.assertIsInstance(s.db, sqlite3.Connection)
            s.kv.close()
            s.db.close()

    def test_s3(self):
        with tempfile.TemporaryDirectory() as d:
            s = st.from_env({"ACRETIA_BLOB_BACKEND": "s3", "ACRETIA_S3_ENDPOINT": "http://m:9000",
                             "ACRETIA_S3_BUCKET": "b", "ACRETIA_S3_ACCESS_KEY": AK, "ACRETIA_S3_SECRET_KEY": SK,
                             "ACRETIA_KV_PATH": d + "/kv.db"}, connect_db=False)
            self.assertIsInstance(s.blobs, st.S3BlobStore)
            self.assertNotIn(SK, repr(s.blobs))
            s.kv.close()

    def test_errors(self):
        with self.assertRaises(st.StorageError):
            st.from_env({"ACRETIA_BLOB_BACKEND": "gcs"})
        with self.assertRaises(st.StorageError):
            st.from_env({"ACRETIA_BLOB_BACKEND": "s3"})


BACKENDS = ["sqlite"] + (["duckdb"] if st.duckdb_available() else [])


class AnalyticsTests(unittest.TestCase):
    def each(self):
        for b in BACKENDS:
            with self.subTest(backend=b):
                db = st.AnalyticsDB(":memory:", prefer=b)
                self.assertEqual(db.backend, b)
                yield db
                db.close()

    def test_insert_query_and_types(self):
        for db in self.each():
            n = db.insert_rows("t", [{"a": 1, "b": 1.5, "c": "x", "d": {"k": 1}}, {"a": 2, "b": None, "c": "y", "d": None}])
            self.assertEqual(n, 2)
            rows = db.query("SELECT * FROM t WHERE a >= ? ORDER BY a", [1])
            self.assertEqual([r["a"] for r in rows], [1, 2])
            self.assertEqual(json.loads(rows[0]["d"]), {"k": 1})
            self.assertTrue(db.table_exists("t"))
            self.assertFalse(db.table_exists("nope"))
            db.executemany("INSERT INTO t (a, c) VALUES (?, ?)", [(3, "z"), (4, "w")])
            self.assertEqual(db.query("SELECT count(*) AS n FROM t")[0]["n"], 4)
            self.assertEqual(db.insert_rows("t", []), 0)

    def test_identifier_injection_rejected(self):
        for db in self.each():
            for bad in ("x; DROP TABLE y", "a b", 'a"b', "a'b", "1a", "", "a" * 64, "a-b"):
                with self.assertRaises(st.StorageError):
                    db.insert_rows(bad, [{"a": 1}])
                with self.assertRaises(st.StorageError):
                    db.insert_rows("ok", [{bad: 1}])
                with self.assertRaises(st.StorageError):
                    db.upsert_rows("ok", [{"a": 1}], [bad])
                with self.assertRaises(st.StorageError):
                    db.table_exists(bad)
            self.assertFalse(db.table_exists("ok"))
            db.insert_rows("a" * 63, [{"a": 1}])

    def test_upsert_idempotent(self):
        for db in self.each():
            rows = [{"k": "a", "v": 1}, {"k": "b", "v": 2}]
            db.upsert_rows("u", rows, ["k"])
            db.upsert_rows("u", rows, ["k"])
            self.assertEqual(db.query("SELECT count(*) AS n FROM u")[0]["n"], 2)
            db.upsert_rows("u", [{"k": "a", "v": 9}], "k")
            self.assertEqual(db.query("SELECT v FROM u WHERE k = ?", ["a"])[0]["v"], 9)
            db.upsert_rows("keys", [{"k": 1}], ["k"])
            db.upsert_rows("keys", [{"k": 1}], ["k"])
            self.assertEqual(len(db.query("SELECT * FROM keys")), 1)

    def test_grid_schema(self):
        for db in self.each():
            st.ensure_grid_schema(db)
            st.ensure_grid_schema(db)
            cell = {"grid_id": "g", "doc_id": "d", "question_id": "q", "answer": "42", "exact_quote": "forty-two",
                    "page": 3, "bbox_x0": 0.1, "bbox_y0": 0.2, "bbox_x1": 0.9, "bbox_y1": 1.0,
                    "confidence": 0.8, "cost_usd": 0.01, "content_hash": "h", "updated_at": "2026-01-01T00:00:00Z"}
            db.upsert_rows("grid_cells", [cell], ["grid_id", "doc_id", "question_id"])
            db.upsert_rows("grid_cells", [dict(cell, answer="43")], ["grid_id", "doc_id", "question_id"])
            self.assertEqual(db.query("SELECT answer FROM grid_cells")[0]["answer"], "43")
            with self.assertRaises(st.StorageError):
                db.insert_rows("grid_cells", [dict(cell, question_id="q2", bbox_x1=1.5)])
            with self.assertRaises(st.StorageError):
                db.insert_rows("grid_cells", [dict(cell, question_id="q3", bbox_y0=-0.1)])
            with self.assertRaises(st.StorageError):
                db.insert_rows("grid_cells", [cell])  # primary key duplicate
            db.insert_rows("grid_cells", [dict(cell, question_id="q4", bbox_x0=None)])
            db.insert_rows("grid_runs", [{"run_id": "r", "grid_id": "g", "est_cost_usd": 1.0}])
            self.assertEqual(len(db.query("SELECT * FROM grid_runs")), 1)

    def test_context_manager_and_closed(self):
        with st.AnalyticsDB(prefer="sqlite") as db:
            db.execute("CREATE TABLE z (a INTEGER)")
        with self.assertRaises(st.StorageError):
            db.query("SELECT 1")

    def test_fallback_when_duckdb_missing(self):
        with mock.patch.object(st, "_duckdb", None):
            db = st.AnalyticsDB(":memory:", prefer="duckdb")
            self.assertEqual(db.backend, "sqlite")
            db.insert_rows("t", [{"a": 1}])
            self.assertEqual(db.query("SELECT a FROM t"), [{"a": 1}])
            db.close()
            with tempfile.TemporaryDirectory() as d:
                a = st.connect(f"duckdb:///{d}/g.duckdb")
                self.assertEqual(a.backend, "sqlite")
                self.assertTrue(a.path.endswith("g.sqlite"))
                a.close()
        with mock.patch.dict(sys.modules, {"duckdb": None}):
            with self.assertRaises(ImportError):
                import duckdb  # noqa: F401

    def test_connect_dsn(self):
        with tempfile.TemporaryDirectory() as d:
            for dsn in ("duckdb://:memory:", f"duckdb:///{d}/sub/g.duckdb", f"duckdb:////{d.lstrip('/')}/h.duckdb"):
                a = st.connect(dsn)
                self.assertIsInstance(a, st.AnalyticsDB)
                a.insert_rows("t", [{"a": 1}])
                a.close()
            self.assertTrue(os.path.isfile(f"{d}/sub/g.duckdb" if st.duckdb_available() else f"{d}/sub/g.sqlite"))

    def test_from_env_analytics(self):
        with tempfile.TemporaryDirectory() as d:
            s = st.from_env({"ACRETIA_BLOB_ROOT": d + "/b", "ACRETIA_KV_PATH": d + "/kv.db", "ACRETIA_DB": d + "/m.db",
                             "ACRETIA_ANALYTICS": f"sqlite:///{d}/a.sqlite"})
            self.assertIsInstance(s.analytics, st.AnalyticsDB)
            self.assertEqual(s.analytics.backend, "sqlite")
            s.analytics.close(); s.kv.close(); s.db.close()
            s = st.from_env({"ACRETIA_BLOB_ROOT": d + "/b", "ACRETIA_KV_PATH": d + "/kv.db"}, connect_db=False)
            self.assertIsNone(s.analytics)
            s.kv.close()

    def test_threads_file_db(self):
        for b in BACKENDS:
            with self.subTest(backend=b), tempfile.TemporaryDirectory() as d:
                db = st.AnalyticsDB(os.path.join(d, "t.db"), prefer=b)
                errs = []

                def work(i):
                    try:
                        for j in range(10):
                            db.insert_rows("t", [{"w": i, "j": j}])
                            db.query("SELECT count(*) AS n FROM t")
                    except Exception as e:  # pragma: no cover
                        errs.append(e)

                ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
                [t.start() for t in ts]
                [t.join() for t in ts]
                self.assertEqual(errs, [])
                self.assertEqual(db.query("SELECT count(*) AS n FROM t")[0]["n"], 80)
                db.close()


if __name__ == "__main__":
    unittest.main()
