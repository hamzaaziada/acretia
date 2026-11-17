"""Storage adapters (D-003): blobs, KV + durable queue, and the relational DB connection.

Standard library only. SQLite (WAL) is the system of record; S3/MinIO, Redis and Postgres are optional
adapters selected by environment variables in `from_env()`. Secrets come from arguments or the environment
and are never logged or shown in `repr()`.
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import os
import re
import socket
import sqlite3
import tempfile
import threading
import time
import urllib.error
import uuid
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import namedtuple
from datetime import datetime, timezone

__all__ = [
    "StorageError", "BlobStore", "LocalBlobStore", "S3BlobStore", "sigv4_authorization", "sigv4_presign",
    "SQLiteKV", "RedisKV", "Lease", "connect", "from_env", "Storage",
]

_KEY_RE = re.compile(r"\A[0-9a-f]{64}\Z")


class StorageError(RuntimeError):
    pass


def _check_key(key: str) -> str:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise ValueError("blob key must be 64 lowercase hex characters (sha256)")
    return key


# --------------------------------------------------------------------------- blobs

class BlobStore:
    """Content-addressed blob interface. `put` returns the sha256 hex key."""

    def put(self, data: bytes) -> str:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError

    def list(self, prefix: str = "") -> list[str]:
        raise NotImplementedError


class LocalBlobStore(BlobStore):
    def __init__(self, root: str = "storage/blobs"):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        _check_key(key)
        return os.path.join(self.root, key[:2], key[2:4], key)

    def put(self, data: bytes) -> str:
        data = bytes(data)
        key = hashlib.sha256(data).hexdigest()
        path = self._path(key)
        if os.path.exists(path):
            return key
        d = os.path.dirname(path)
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return key

    def get(self, key: str) -> bytes:
        try:
            with open(self._path(key), "rb") as f:
                return f.read()
        except FileNotFoundError:
            raise KeyError(key) from None

    def exists(self, key: str) -> bool:
        return os.path.isfile(self._path(key))

    def delete(self, key: str) -> bool:
        try:
            os.unlink(self._path(key))
            return True
        except FileNotFoundError:
            return False

    def list(self, prefix: str = "") -> list[str]:
        out = []
        for dirpath, _dirs, files in os.walk(self.root):
            for n in files:
                if _KEY_RE.match(n) and n.startswith(prefix):
                    out.append(n)
        return sorted(out)


# --------------------------------------------------------------------------- AWS Signature V4

def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _q(s: str, safe: str = "-_.~") -> str:
    return urllib.parse.quote(s, safe=safe)


def _canonical_query(query) -> str:
    items = query.items() if isinstance(query, dict) else (query or [])
    return "&".join(f"{_q(str(k))}={_q(str(v))}" for k, v in sorted((str(k), str(v)) for k, v in items))


def _signing_key(secret_key: str, date: str, region: str, service: str) -> bytes:
    k = _hmac(("AWS4" + secret_key).encode("utf-8"), date)
    for part in (region, service, "aws4_request"):
        k = _hmac(k, part)
    return k


def _sign(method, path, query, headers, payload_hash, secret_key, region, service, amz_date):
    """Return (signed_headers, scope_date, signature). `headers` must already include host."""
    lower = {k.lower().strip(): " ".join(str(v).split()) for k, v in headers.items()}
    names = sorted(lower)
    canonical_headers = "".join(f"{n}:{lower[n]}\n" for n in names)
    signed = ";".join(names)
    canonical = "\n".join([method.upper(), _q(path, "/-_.~"), _canonical_query(query),
                           canonical_headers, signed, payload_hash])
    date = amz_date[:8]
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    sig = hmac.new(_signing_key(secret_key, date, region, service), to_sign.encode(), hashlib.sha256).hexdigest()
    return signed, scope, sig


def sigv4_authorization(method, host, path, headers, payload_hash, access_key, secret_key, region,
                        amz_date, query=None, service="s3") -> str:
    """Authorization header value for header-based SigV4. `headers` are the extra headers to sign
    (e.g. Range, x-amz-content-sha256, x-amz-date); host is added automatically."""
    h = dict(headers)
    h["host"] = host
    signed, scope, sig = _sign(method, path, query, h, payload_hash, secret_key, region, service, amz_date)
    return (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={sig}")


def sigv4_presign(method, host, path, expires, access_key, secret_key, region, amz_date,
                  query=None, service="s3", scheme="https") -> str:
    """Query-string presigned URL (payload UNSIGNED-PAYLOAD, signed header: host)."""
    q = dict(query or {})
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    q.update({"X-Amz-Algorithm": "AWS4-HMAC-SHA256", "X-Amz-Credential": f"{access_key}/{scope}",
              "X-Amz-Date": amz_date, "X-Amz-Expires": str(int(expires)), "X-Amz-SignedHeaders": "host"})
    _signed, _scope, sig = _sign(method, path, q, {"host": host}, "UNSIGNED-PAYLOAD", secret_key, region,
                                 service, amz_date)
    return f"{scheme}://{host}{_q(path, '/-_.~')}?{_canonical_query(q)}&X-Amz-Signature={sig}"


def _urllib_transport(method, url, headers, body):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


class S3BlobStore(BlobStore):
    """S3 / MinIO blob store, path-style addressing. `transport(method, url, headers, body) ->
    (status, headers, body)` is injectable for tests."""

    def __init__(self, endpoint, bucket, region="us-east-1", access_key=None, secret_key=None,
                 transport=None, prefix="", clock=None):
        access_key = access_key or os.environ.get("ACRETIA_S3_ACCESS_KEY")
        secret_key = secret_key or os.environ.get("ACRETIA_S3_SECRET_KEY")
        if not access_key or not secret_key:
            raise StorageError("S3 credentials missing (pass them or set ACRETIA_S3_ACCESS_KEY/SECRET_KEY)")
        if "//" not in endpoint:
            endpoint = "https://" + endpoint
        u = urllib.parse.urlsplit(endpoint)
        self.scheme, self.host = u.scheme, u.netloc
        self.bucket, self.region, self.prefix = bucket, region, prefix
        self._access_key, self._secret_key = access_key, secret_key
        self._transport = transport or _urllib_transport
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"S3BlobStore(endpoint={self.scheme}://{self.host!r}, bucket={self.bucket!r}, region={self.region!r})"

    def _path(self, key=None):
        p = f"/{self.bucket}"
        return p + f"/{self.prefix}{_check_key(key)}" if key is not None else p + "/"

    def _request(self, method, key=None, body=b"", query=None, ok=(200,)):
        amz_date = self._clock().strftime("%Y%m%dT%H%M%SZ")
        path = self._path(key)
        payload_hash = hashlib.sha256(body).hexdigest()
        extra = {"x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        auth = sigv4_authorization(method, self.host, path, extra, payload_hash, self._access_key,
                                   self._secret_key, self.region, amz_date, query)
        url = f"{self.scheme}://{self.host}{_q(path, '/-_.~')}"
        if query:
            url += "?" + _canonical_query(query)
        headers = dict(extra, Authorization=auth)
        status, _h, data = self._transport(method, url, headers, body or None)
        if status not in ok:
            raise StorageError(f"S3 {method} failed with HTTP {status}")
        return status, data

    def put(self, data: bytes) -> str:
        data = bytes(data)
        key = hashlib.sha256(data).hexdigest()
        self._request("PUT", key, data)
        return key

    def get(self, key: str) -> bytes:
        status, data = self._request("GET", key, ok=(200, 404))
        if status == 404:
            raise KeyError(key)
        return data

    def exists(self, key: str) -> bool:
        status, _ = self._request("HEAD", key, ok=(200, 404))
        return status == 200

    def delete(self, key: str) -> bool:
        existed = self.exists(key)
        self._request("DELETE", key, ok=(200, 204, 404))
        return existed

    def list(self, prefix: str = "") -> list[str]:
        out, token = [], None
        while True:
            q = {"list-type": "2", "prefix": self.prefix + prefix}
            if token:
                q["continuation-token"] = token
            _s, data = self._request("GET", None, query=q)
            root = ET.fromstring(data)
            ns = root.tag.partition("}")[0] + "}" if root.tag.startswith("{") else ""
            for k in root.iter(f"{ns}Key"):
                name = (k.text or "")[len(self.prefix):]
                if _KEY_RE.match(name):
                    out.append(name)
            if (root.findtext(f"{ns}IsTruncated") or "").lower() == "true":
                token = root.findtext(f"{ns}NextContinuationToken")
                if token:
                    continue
            return sorted(out)

    def presign_url(self, method: str, key: str, expires: int = 3600, now=None) -> str:
        amz_date = (now or self._clock()).strftime("%Y%m%dT%H%M%SZ")
        return sigv4_presign(method, self.host, self._path(key), expires, self._access_key,
                             self._secret_key, self.region, amz_date, scheme=self.scheme)


# --------------------------------------------------------------------------- KV + queue

Lease = namedtuple("Lease", "id payload attempts queue token", defaults=(None, None))

DEFAULT_MAX_ATTEMPTS = 5
DLQ_SUFFIX = ".dlq"


def _b(v) -> bytes:
    return v.encode("utf-8") if isinstance(v, str) else bytes(v)


class SQLiteKV:
    """Key/value store and durable FIFO queue with leases, in one SQLite file (WAL). Thread-safe, and safe
    across processes (writes use BEGIN IMMEDIATE)."""

    def __init__(self, path: str = "storage/kv.sqlite", clock=time.time):
        self._clock = clock
        self._lock = threading.RLock()
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30, isolation_level=None)
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v);"
            "CREATE TABLE IF NOT EXISTS queue(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,"
            " payload BLOB NOT NULL, visible_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);"
            "CREATE INDEX IF NOT EXISTS queue_ready ON queue(name, visible_at, id);")
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(queue)")}
        for col, ddl in (("lease_token", "TEXT"), ("max_attempts", f"INTEGER NOT NULL DEFAULT {DEFAULT_MAX_ATTEMPTS}"),
                         ("last_error", "TEXT")):
            if col not in cols:
                try:
                    self._db.execute(f"ALTER TABLE queue ADD COLUMN {col} {ddl}")
                except sqlite3.OperationalError:  # another process added it first
                    pass

    def close(self):
        with self._lock:
            self._db.close()

    def _tx(self, fn):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                r = fn(self._db)
                self._db.execute("COMMIT")
                return r
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    # key/value
    def get(self, key, default=None):
        with self._lock:
            row = self._db.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return default if row is None else row[0]

    def set(self, key, value):
        self._tx(lambda d: d.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                                     (key, value)))

    def delete(self, key) -> bool:
        return self._tx(lambda d: d.execute("DELETE FROM kv WHERE k=?", (key,)).rowcount > 0)

    def incr(self, key, amount: int = 1) -> int:
        def f(d):
            row = d.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
            n = (int(row[0]) if row else 0) + amount
            d.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, n))
            return n
        return self._tx(f)

    # queue
    def enqueue(self, name, payload, delay: float = 0.0, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> int:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise StorageError("max_attempts must be an int >= 1")
        return self._tx(lambda d: d.execute(
            "INSERT INTO queue(name,payload,visible_at,max_attempts) VALUES(?,?,?,?)",
            (name, _b(payload), self._clock() + delay, max_attempts)).lastrowid)

    @staticmethod
    def _to_dlq(d, row_id, name, error, now):
        d.execute("UPDATE queue SET name=?, lease_token=NULL, visible_at=?, last_error=? WHERE id=?",
                  (name + DLQ_SUFFIX, now, error, row_id))

    def dequeue(self, name, lease: float = 30.0):
        """Return the oldest visible item as a Lease (with a unique ``token``) and hide it for `lease` seconds,
        or None. An item whose attempts are exhausted moves to ``<name>.dlq`` instead of being delivered."""
        def f(d):
            now = self._clock()
            while True:
                row = d.execute("SELECT id,payload,attempts,max_attempts,last_error FROM queue WHERE name=? "
                                "AND visible_at<=? ORDER BY id LIMIT 1", (name, now)).fetchone()
                if row is None:
                    return None
                if row[2] >= row[3]:
                    self._to_dlq(d, row[0], name, row[4] or "lease expired without ack (max attempts reached)", now)
                    continue
                token = uuid.uuid4().hex
                d.execute("UPDATE queue SET visible_at=?, attempts=attempts+1, lease_token=? WHERE id=?",
                          (now + lease, token, row[0]))
                return Lease(row[0], bytes(row[1]), row[2] + 1, name, token)
        return self._tx(f)

    @staticmethod
    def _fence(item):
        """(id, token) from a ``Lease`` or an ``(id, token)`` pair. A bare id is refused (N2/F19): it would bypass
        the lease fence and delete an item another worker now holds."""
        if hasattr(item, "token") and hasattr(item, "id"):
            if item.token is None:
                raise StorageError("ack/nack need the Lease returned by dequeue (this one has no token)")
            return item.id, item.token
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], str) and item[1]:
            return item[0], item[1]
        raise TypeError("ack/nack need the Lease returned by dequeue() or an (id, token) pair, not a bare id "
                        f"({type(item).__name__}): a bare id is unfenced and could delete another worker's live "
                        "lease. Migrate: lease = kv.dequeue(...); kv.ack(lease)")

    def ack(self, item_id) -> bool:
        """Delete the item iff ``(id, lease_token)`` still matches the live lease; a stale worker gets False."""
        i, tok = self._fence(item_id)
        return self._tx(lambda d: d.execute("DELETE FROM queue WHERE id=? AND lease_token=?", (i, tok)).rowcount > 0)

    def nack(self, item_id, delay: float = 0.0, error: str | None = None) -> bool:
        """Release the lease (token-fenced). Records ``error``; an exhausted item moves to the dead-letter queue."""
        i, tok = self._fence(item_id)

        def f(d):
            row = d.execute("SELECT name,attempts,max_attempts,lease_token FROM queue WHERE id=?", (i,)).fetchone()
            if row is None or row[3] != tok:
                return False
            now = self._clock()
            if error is not None:
                d.execute("UPDATE queue SET last_error=? WHERE id=?", (error, i))
            if row[1] >= row[2]:
                self._to_dlq(d, i, row[0], error or "max attempts reached", now)
            else:
                d.execute("UPDATE queue SET visible_at=?, lease_token=NULL WHERE id=?", (now + delay, i))
            return True
        return self._tx(f)

    def qsize(self, name) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM queue WHERE name=?", (name,)).fetchone()[0]

    def dlq_list(self, name) -> list:
        with self._lock:
            rows = self._db.execute("SELECT id,payload,attempts,last_error FROM queue WHERE name=? ORDER BY id",
                                    (name + DLQ_SUFFIX,)).fetchall()
        return [{"id": r[0], "payload": bytes(r[1]), "attempts": r[2], "last_error": r[3]} for r in rows]

    def dlq_requeue(self, name, item_id=None) -> int:
        """Move dead-lettered items (one, or all) back to ``name`` with a fresh attempt budget. Returns the count."""
        def f(d):
            q, args = "UPDATE queue SET name=?, attempts=0, visible_at=?, lease_token=NULL WHERE name=?", \
                [name, self._clock(), name + DLQ_SUFFIX]
            if item_id is not None:
                q += " AND id=?"
                args.append(getattr(item_id, "id", item_id) if not isinstance(item_id, dict) else item_id["id"])
            return d.execute(q, args).rowcount
        return self._tx(f)


class RedisKV:
    """Minimal RESP2 client with the same API as SQLiteKV. Queue = sorted set scored by visibility time,
    claimed atomically with a Lua script. Needs a reachable Redis server; no third-party package."""

    # Fields per item in hash KEYS[2]: <id> payload, <id>:n attempts, <id>:t lease token, <id>:max, <id>:err.
    # KEYS[3] is the dead-letter zset. ARGV: now, lease, token, default max_attempts.
    _DEQ = ("while true do "
            "local m=redis.call('ZRANGEBYSCORE',KEYS[1],'-inf',ARGV[1],'LIMIT',0,1)[1] "
            "if not m then return false end "
            "local n=tonumber(redis.call('HGET',KEYS[2],m..':n') or 0) "
            "local mx=tonumber(redis.call('HGET',KEYS[2],m..':max') or ARGV[4]) "
            "if n>=mx then "
            "redis.call('ZREM',KEYS[1],m) redis.call('ZADD',KEYS[3],ARGV[1],m) "
            "redis.call('HDEL',KEYS[2],m..':t') "
            "if not redis.call('HGET',KEYS[2],m..':err') then "
            "redis.call('HSET',KEYS[2],m..':err','lease expired without ack (max attempts reached)') end "
            "else "
            "redis.call('ZADD',KEYS[1],tonumber(ARGV[1])+tonumber(ARGV[2]),m) "
            "local a=redis.call('HINCRBY',KEYS[2],m..':n',1) "
            "redis.call('HSET',KEYS[2],m..':t',ARGV[3]) "
            "return {m,redis.call('HGET',KEYS[2],m),a} "
            "end end")
    # ack: only if the live lease token matches. ARGV: id, token
    _ACK = ("if redis.call('HGET',KEYS[2],ARGV[1]..':t')~=ARGV[2] then return 0 end "
            "redis.call('HDEL',KEYS[2],ARGV[1],ARGV[1]..':n',ARGV[1]..':t',ARGV[1]..':max',ARGV[1]..':err') "
            "return redis.call('ZREM',KEYS[1],ARGV[1])")
    # nack: token-fenced; ARGV: id, token, visible_at, error ('' for none). Exhausted items go to the DLQ.
    _NACK = ("if redis.call('HGET',KEYS[2],ARGV[1]..':t')~=ARGV[2] then return 0 end "
             "if ARGV[4]~='' then redis.call('HSET',KEYS[2],ARGV[1]..':err',ARGV[4]) end "
             "redis.call('HDEL',KEYS[2],ARGV[1]..':t') "
             "local n=tonumber(redis.call('HGET',KEYS[2],ARGV[1]..':n') or 0) "
             "local mx=tonumber(redis.call('HGET',KEYS[2],ARGV[1]..':max') or ARGV[5]) "
             "if n>=mx then redis.call('ZREM',KEYS[1],ARGV[1]) redis.call('ZADD',KEYS[3],ARGV[3],ARGV[1]) return 1 end "
             "return redis.call('ZADD',KEYS[1],'XX','CH',ARGV[3],ARGV[1])+1")

    def __init__(self, url: str = "redis://localhost:6379/0", clock=time.time, timeout: float = 5.0):
        u = urllib.parse.urlsplit(url)
        self._addr = (u.hostname or "localhost", u.port or 6379)
        self._password = urllib.parse.unquote(u.password) if u.password else None
        self._dbn = int((u.path or "/0").lstrip("/") or 0)
        self._clock, self._timeout = clock, timeout
        self._lock = threading.RLock()
        self._sock = None
        self._buf = b""
        try:
            self._cmd("PING")
        except OSError as e:
            raise StorageError(f"cannot reach Redis at {self._addr[0]}:{self._addr[1]}: {e.__class__.__name__}") from None

    def __repr__(self):
        return f"RedisKV({self._addr[0]}:{self._addr[1]}/{self._dbn})"

    @staticmethod
    def encode(*args) -> bytes:
        out = [b"*%d\r\n" % len(args)]
        for a in args:
            a = a if isinstance(a, bytes) else str(a).encode("utf-8")
            out.append(b"$%d\r\n%s\r\n" % (len(a), a))
        return b"".join(out)

    def _readline(self):
        while b"\r\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("redis closed connection")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\r\n")
        return line

    def _readn(self, n):
        while len(self._buf) < n + 2:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("redis closed connection")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n + 2:]
        return data

    def _read(self):
        line = self._readline()
        t, rest = line[:1], line[1:]
        if t == b"+":
            return rest.decode()
        if t == b"-":
            raise StorageError("redis error: " + rest.decode(errors="replace"))
        if t == b":":
            return int(rest)
        if t == b"$":
            n = int(rest)
            return None if n < 0 else self._readn(n)
        if t == b"*":
            n = int(rest)
            return None if n < 0 else [self._read() for _ in range(n)]
        raise StorageError("bad RESP reply")

    def _connect(self):
        self._sock = socket.create_connection(self._addr, timeout=self._timeout)
        self._buf = b""
        if self._password:
            self._sock.sendall(self.encode("AUTH", self._password))
            self._read()
        if self._dbn:
            self._sock.sendall(self.encode("SELECT", self._dbn))
            self._read()

    def _cmd(self, *args):
        with self._lock:
            if self._sock is None:
                self._connect()
            try:
                self._sock.sendall(self.encode(*args))
                return self._read()
            except (OSError, ConnectionError):
                self._sock = None
                raise

    def close(self):
        with self._lock:
            if self._sock:
                self._sock.close()
                self._sock = None

    def get(self, key, default=None):
        v = self._cmd("GET", "kv:" + key)
        return default if v is None else v

    def set(self, key, value):
        self._cmd("SET", "kv:" + key, value)

    def delete(self, key) -> bool:
        return self._cmd("DEL", "kv:" + key) > 0

    def incr(self, key, amount: int = 1) -> int:
        return self._cmd("INCRBY", "kv:" + key, amount)

    def enqueue(self, name, payload, delay: float = 0.0, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> int:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise StorageError("max_attempts must be an int >= 1")
        i = self._cmd("INCR", f"q:{name}:seq")
        self._cmd("HSET", f"q:{name}:data", str(i), _b(payload), f"{i}:max", str(max_attempts))
        self._cmd("ZADD", f"q:{name}", repr(self._clock() + delay), str(i))
        return i

    def _deq_args(self, name, lease, token):
        return ("EVAL", self._DEQ, 3, f"q:{name}", f"q:{name}:data", f"q:{name}:dlq", repr(self._clock()),
                repr(lease), token, DEFAULT_MAX_ATTEMPTS)

    def dequeue(self, name, lease: float = 30.0):
        token = uuid.uuid4().hex
        r = self._cmd(*self._deq_args(name, lease, token))
        if not r:
            return None
        return Lease(int(r[0]), r[1], int(r[2]), name, token)

    def _lease(self, lease):
        if not (hasattr(lease, "id") and hasattr(lease, "token") and hasattr(lease, "queue")):
            raise TypeError("RedisKV ack/nack need the Lease returned by dequeue(), not a bare id or pair: a bare id "
                            f"is unfenced ({type(lease).__name__}). Migrate: lease = kv.dequeue(...); kv.ack(lease)")
        if lease.queue is None or lease.token is None:
            raise StorageError("RedisKV ack/nack need the Lease returned by dequeue")
        return lease.queue, str(lease.id), lease.token

    def ack(self, lease) -> bool:
        name, i, tok = self._lease(lease)
        return self._cmd("EVAL", self._ACK, 2, f"q:{name}", f"q:{name}:data", i, tok) > 0

    def nack(self, lease, delay: float = 0.0, error: str | None = None) -> bool:
        name, i, tok = self._lease(lease)
        return self._cmd("EVAL", self._NACK, 3, f"q:{name}", f"q:{name}:data", f"q:{name}:dlq", i, tok,
                         repr(self._clock() + delay), error or "", DEFAULT_MAX_ATTEMPTS) > 0

    def qsize(self, name) -> int:
        return self._cmd("ZCARD", f"q:{name}")

    def dlq_list(self, name) -> list:
        out = []
        for m in self._cmd("ZRANGE", f"q:{name}:dlq", 0, -1) or []:
            i = m.decode()
            payload, n, err = self._cmd("HMGET", f"q:{name}:data", i, f"{i}:n", f"{i}:err")
            out.append({"id": int(i), "payload": payload, "attempts": int(n or 0),
                        "last_error": err.decode() if err else None})
        return out

    def dlq_requeue(self, name, item_id=None) -> int:
        ids = [str(item_id["id"] if isinstance(item_id, dict) else getattr(item_id, "id", item_id))] \
            if item_id is not None else [m.decode() for m in self._cmd("ZRANGE", f"q:{name}:dlq", 0, -1) or []]
        n = 0
        for i in ids:
            if self._cmd("ZREM", f"q:{name}:dlq", i) > 0:
                self._cmd("HSET", f"q:{name}:data", f"{i}:n", "0")
                self._cmd("HDEL", f"q:{name}:data", f"{i}:t", f"{i}:err")
                self._cmd("ZADD", f"q:{name}", repr(self._clock()), i)
                n += 1
        return n


# --------------------------------------------------------------------------- analytics DB (DuckDB optional)

try:  # DuckDB is optional (MIT, D-018); SQLite is the graceful fallback.
    import duckdb as _duckdb  # type: ignore
except Exception:  # pragma: no cover - depends on environment
    _duckdb = None

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def duckdb_available() -> bool:
    return _duckdb is not None


def _ident(name) -> str:
    if not isinstance(name, str) or not _IDENT.match(name):
        raise StorageError(f"invalid SQL identifier {name!r}")
    return name


def _integrity_errors() -> tuple:
    errs = [sqlite3.IntegrityError]
    if _duckdb is not None:
        errs.append(_duckdb.ConstraintException)
    return tuple(errs)


class AnalyticsDB:
    """Embedded analytics store: DuckDB when importable (and `prefer="duckdb"`), otherwise SQLite.
    SQL uses `?` placeholders on both backends. The connection is opened lazily on first use.

    Thread safety: DuckDB connections must not be shared across threads unguarded, so one connection is
    shared and every operation (including fetching its result) runs under a single re-entrant lock.
    Concurrent writers are therefore serialised, which is correct for both backends and cheap at grid scale.
    Integrity/CHECK violations surface as `StorageError`."""

    def __init__(self, path: str = ":memory:", prefer: str = "duckdb"):
        if prefer not in ("duckdb", "sqlite"):
            raise StorageError(f"unknown analytics backend {prefer!r}")
        self.backend = "duckdb" if (prefer == "duckdb" and _duckdb is not None) else "sqlite"
        self.path = path
        self._lock = threading.RLock()
        self._conn = None
        self._closed = False

    def _c(self):
        if self._closed:
            raise StorageError("AnalyticsDB is closed")
        if self._conn is None:
            if self.path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            if self.backend == "duckdb":
                self._conn = _duckdb.connect(self.path)
            else:
                c = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
                c.execute("PRAGMA busy_timeout=30000")
                if self.path != ":memory:":
                    c.execute("PRAGMA journal_mode=WAL")
                self._conn = c
        return self._conn

    def _run(self, fn):
        try:
            return fn()
        except _integrity_errors() as e:
            raise StorageError(f"constraint violation: {e}") from e

    def execute(self, sql: str, params=()) -> None:
        with self._lock:
            c = self._c()
            self._run(lambda: c.execute(sql, list(params or ())))
            if self.backend == "sqlite":
                c.commit()

    def executemany(self, sql: str, seq) -> None:
        seq = [list(p) for p in seq]
        if not seq:
            return
        with self._lock:
            c = self._c()
            self._run(lambda: c.executemany(sql, seq))
            if self.backend == "sqlite":
                c.commit()

    def query(self, sql: str, params=()) -> list:
        with self._lock:
            cur = self._c().execute(sql, list(params or ()))
            if cur.description is None:
                return []
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def table_exists(self, table: str) -> bool:
        _ident(table)
        if self.backend == "duckdb":
            sql = "SELECT 1 FROM information_schema.tables WHERE table_name = ?"
        else:
            sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?"
        return bool(self.query(sql, [table]))

    def _coltype(self, v) -> str:
        d = self.backend == "duckdb"
        if isinstance(v, bool):
            return "BOOLEAN" if d else "INTEGER"
        if isinstance(v, int):
            return "BIGINT" if d else "INTEGER"
        if isinstance(v, float):
            return "DOUBLE" if d else "REAL"
        return "VARCHAR" if d else "TEXT"

    @staticmethod
    def _val(v):
        return json.dumps(v, sort_keys=True) if isinstance(v, (dict, list, tuple)) else v

    def _prep(self, table, rows, pk=None):
        _ident(table)
        rows = list(rows)
        if not rows:
            return None, None, []
        cols = [_ident(k) for k in rows[0].keys()]
        for r in rows:
            extra = set(r) - set(cols)
            if extra:
                raise StorageError(f"row has columns not in first row: {sorted(extra)}")
        if pk:
            for k in pk:
                if _ident(k) not in cols:
                    raise StorageError(f"key column {k!r} missing from rows")
        if not self.table_exists(table):
            defs = []
            for c in cols:
                first = next((r[c] for r in rows if r.get(c) is not None), None)
                defs.append(f"{c} {self._coltype(first)}")
            if pk:
                defs.append("PRIMARY KEY (" + ", ".join(pk) + ")")
            self.execute(f"CREATE TABLE {table} ({', '.join(defs)})")
        data = [[self._val(r.get(c)) for c in cols] for r in rows]
        return cols, data, rows

    def insert_rows(self, table: str, rows: list) -> int:
        with self._lock:
            cols, data, rows = self._prep(table, rows)
            if not rows:
                return 0
            self.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", data)
            return len(rows)

    def upsert_rows(self, table: str, rows: list, key_cols) -> int:
        key_cols = [_ident(k) for k in ([key_cols] if isinstance(key_cols, str) else key_cols)]
        if not key_cols:
            raise StorageError("upsert_rows needs at least one key column")
        with self._lock:
            cols, data, rows = self._prep(table, rows, key_cols)
            if not rows:
                return 0
            rest = [c for c in cols if c not in key_cols]
            action = ("DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in rest)) if rest else "DO NOTHING"
            self.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                f"ON CONFLICT ({', '.join(key_cols)}) {action}", data)
            return len(rows)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def ensure_grid_schema(db: AnalyticsDB) -> None:
    """Create the document-grid tables (S5.2). Idempotent. bbox values are page-relative fractions in [0, 1]."""
    d = db.backend == "duckdb"
    txt, real, big = ("VARCHAR", "DOUBLE", "BIGINT") if d else ("TEXT", "REAL", "INTEGER")
    box = ",\n    ".join(f"CHECK ({c} IS NULL OR ({c} >= 0 AND {c} <= 1))"
                         for c in ("bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"))
    db.execute(f"""CREATE TABLE IF NOT EXISTS grid_cells (
    grid_id {txt} NOT NULL, doc_id {txt} NOT NULL, question_id {txt} NOT NULL,
    answer {txt}, exact_quote {txt}, page {big},
    bbox_x0 {real}, bbox_y0 {real}, bbox_x1 {real}, bbox_y1 {real},
    confidence {real}, cost_usd {real}, content_hash {txt}, updated_at {txt},
    PRIMARY KEY (grid_id, doc_id, question_id),
    {box},
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CHECK (cost_usd IS NULL OR cost_usd >= 0)
)""")
    db.execute(f"""CREATE TABLE IF NOT EXISTS grid_runs (
    run_id {txt} PRIMARY KEY, grid_id {txt} NOT NULL, n_docs {big}, n_questions {big}, n_cells {big},
    est_cost_usd {real}, actual_cost_usd {real}, status {txt}, created_at {txt}, finished_at {txt}
)""")


def _analytics_from_dsn(dsn: str) -> AnalyticsDB:
    m = re.match(r"(?i)duckdb://(.*)$", dsn)
    if m:
        rest = m.group(1)
        if rest in ("", ":memory:", "/:memory:"):
            path = ":memory:"
        elif rest.startswith("//"):
            path = urllib.parse.unquote(rest[1:])  # duckdb:////abs -> /abs
        else:
            path = urllib.parse.unquote(rest[1:] if rest.startswith("/") else rest)  # duckdb:///rel -> rel
        if _duckdb is None and path != ":memory:" and path.endswith(".duckdb"):
            path = path[: -len(".duckdb")] + ".sqlite"  # never write SQLite bytes into a .duckdb file
        return AnalyticsDB(path, prefer="duckdb")
    path = dsn
    if dsn.startswith("sqlite:"):
        path = urllib.parse.unquote(urllib.parse.urlsplit(dsn).path)
        if dsn.startswith("sqlite:///") and not dsn.startswith("sqlite:////"):
            path = path[1:]
        path = path or ":memory:"
    return AnalyticsDB(path, prefer="sqlite")


# --------------------------------------------------------------------------- relational DB

def connect(dsn: str = "storage/acretia.sqlite"):
    """SQLite (WAL, foreign keys, busy timeout) for `sqlite:///path` or a plain path; an `AnalyticsDB` for `duckdb:///path` / `duckdb://:memory:` (SQLite
    fallback when duckdb is not installed); Postgres for
    `postgres://` / `postgresql://` only when psycopg is importable."""
    if re.match(r"(?i)duckdb://", dsn):
        return _analytics_from_dsn(dsn)
    if re.match(r"(?i)postgres(ql)?://", dsn):
        try:
            import psycopg  # type: ignore
        except ImportError:
            raise StorageError("Postgres DSN given but psycopg is not installed (pip install psycopg[binary])") from None
        return psycopg.connect(dsn)
    path = dsn
    if dsn.startswith("sqlite:"):
        path = urllib.parse.unquote(urllib.parse.urlsplit(dsn).path)
        if dsn.startswith("sqlite:///") and not dsn.startswith("sqlite:////"):
            path = path[1:]  # sqlite:///rel/path -> rel/path ; sqlite:////abs -> /abs
        if not path:
            path = ":memory:"
    if path != ":memory:":
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


Storage = namedtuple("Storage", "blobs kv db analytics", defaults=(None,))


def from_env(env=None, connect_db: bool = True) -> Storage:
    """Build adapters from ACRETIA_BLOB_BACKEND (local|s3), ACRETIA_BLOB_ROOT, ACRETIA_S3_ENDPOINT/BUCKET/
    REGION/ACCESS_KEY/SECRET_KEY, ACRETIA_KV (sqlite|redis), ACRETIA_KV_PATH, ACRETIA_REDIS_URL, ACRETIA_DB, ACRETIA_ANALYTICS (default duckdb:///storage/grid.duckdb, or storage/grid.sqlite
    without duckdb; opened lazily)."""
    e = os.environ if env is None else env
    backend = e.get("ACRETIA_BLOB_BACKEND", "local").lower()
    if backend == "local":
        blobs = LocalBlobStore(e.get("ACRETIA_BLOB_ROOT", "storage/blobs"))
    elif backend == "s3":
        try:
            blobs = S3BlobStore(e["ACRETIA_S3_ENDPOINT"], e["ACRETIA_S3_BUCKET"],
                                e.get("ACRETIA_S3_REGION", "us-east-1"),
                                e.get("ACRETIA_S3_ACCESS_KEY"), e.get("ACRETIA_S3_SECRET_KEY"))
        except KeyError as k:
            raise StorageError(f"missing environment variable {k.args[0]}") from None
    else:
        raise StorageError(f"unknown ACRETIA_BLOB_BACKEND {backend!r}")
    kvb = e.get("ACRETIA_KV", "sqlite").lower()
    if kvb == "sqlite":
        kv = SQLiteKV(e.get("ACRETIA_KV_PATH", "storage/kv.sqlite"))
    elif kvb == "redis":
        kv = RedisKV(e.get("ACRETIA_REDIS_URL", "redis://localhost:6379/0"))
    else:
        raise StorageError(f"unknown ACRETIA_KV {kvb!r}")
    db = connect(e.get("ACRETIA_DB", "storage/acretia.sqlite")) if connect_db else None
    analytics = None
    if connect_db:
        default = "duckdb:///storage/grid.duckdb" if _duckdb is not None else "storage/grid.sqlite"
        analytics = _analytics_from_dsn(e.get("ACRETIA_ANALYTICS", default))
    return Storage(blobs, kv, db, analytics)
