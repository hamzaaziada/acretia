#!/usr/bin/env python3
"""M1 gate: contracts, storage adapters, LLM router (replay + PII), DealMemory.

Independent of the executors' unit tests. Offline; exits non-zero on any failure.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import random
import socket
import sys
import tempfile
import threading
import traceback
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESULTS: list[tuple[str, bool, str]] = []


def check(name):
    def deco(fn):
        try:
            detail = fn() or ""
            RESULTS.append((name, True, str(detail)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"[:300]))
            if os.environ.get("VERIFY_DEBUG"):
                traceback.print_exc()
        return fn
    return deco


def expect_error(fn, exc, contains=None):
    try:
        fn()
    except exc as e:
        if contains and contains not in str(e):
            raise AssertionError(f"error message {str(e)!r} lacks {contains!r}")
        return str(e)
    raise AssertionError("expected %s" % exc.__name__)


# ------------------------------------------------------------ hermetic environment
# Scrub every variable that could select or authenticate a live model provider, and stop the keystore reading
# the user's Keychain or secrets files. Runs before any check.
import re as _re  # noqa: E402

_SCRUB = _re.compile(r"(_API_KEY|_AUTH_TOKEN|_BASE_URL)$|^(OM_PROVIDER_|OM_FALLBACK_|OM_MODEL_|OM_STAGE_|MESHPOOL_|"
                     r"ANTHROPIC_|OPENAI_|GEMINI_|DEEPSEEK_|ACRETIA_LLM_)|^GOOGLE_API_KEY$")
SCRUBBED = sorted(k for k in os.environ if _SCRUB.search(k))
for _k in SCRUBBED:
    del os.environ[_k]
os.environ["ACRETIA_LLM_MODE"] = "replay"
print("hermetic: scrubbed env vars (names only): " + (", ".join(SCRUBBED) or "none")
      + "; ACRETIA_LLM_MODE=replay")

try:
    from om import keystore as _ks  # noqa: E402
    for _fn, _val in (("get", lambda *a, **k: None), ("load_into_env", lambda *a, **k: []),
                      ("_find", lambda *a, **k: None), ("_file_read", lambda *a, **k: {}),
                      ("_file_write", lambda *a, **k: None), ("put", lambda *a, **k: None),
                      ("delete", lambda *a, **k: None)):
        if hasattr(_ks, _fn):
            setattr(_ks, _fn, _val)
except ImportError:
    pass


# ---------------------------------------------------------------- contracts
from om import contracts as C  # noqa: E402

H = "a" * 64


def cit(**kw):
    base = dict(doc_id="d1", sha256_span_hash=H, page=3, bbox_norm=[0.1, 0.2, 0.3, 0.4], quote="Revenue 1,234")
    base.update(kw)
    return base


@check("contracts: all 13 contracts present")
def _():
    names = {c.__name__ for c in C.CONTRACTS}
    need = {"Citation", "WorkbookGraph", "ModelSpec", "ModelManifest", "SlideSpec", "SolvedSlideLayout",
            "SlideRepairPatch", "DeckSpec", "GridSpec", "GridCell", "DealMemory", "Job", "ValidationReport"}
    missing = need - names
    assert not missing, missing
    return f"{len(names)} contracts"


SAMPLES = {
    "Citation": cit(),
    "ModelManifest": {"workbook_sha256": H, "outputs": [
        {"id": "rev_fy24", "sheet": "IS", "ref": "D5", "units": "USD m", "citations": [cit()]},
        {"id": "ebitda", "sheet": "IS", "ref": "D5:H5", "units": "USD m", "citations": []}]},
    "ModelSpec": {"ticker": "AAPL", "model_type": "lbo", "years": [2024, 2025, 2026]},
    "GridCell": {"doc_id": "d1", "question_id": "q1", "answer": "42", "content_hash": H, "citations": [cit()]},
    "ValidationReport": {"target": "x.xlsx", "passed": False, "findings": [
        {"rule": "bs_balance", "severity": "critical", "message": "BS off by 1", "location": "BS!D40"}]},
}


@check("contracts: round-trip dict + JSON for samples")
def _():
    by = {c.__name__: c for c in C.CONTRACTS}
    for name, d in SAMPLES.items():
        cls = by[name]
        obj = cls.from_dict(json.loads(json.dumps(d)))
        obj.validate()
        assert cls.from_dict(obj.to_dict()) == obj, name
        assert cls.from_json(obj.to_json()) == obj, name
        # JSON must be strict (no NaN) and stable
        json.loads(obj.to_json())
    return f"{len(SAMPLES)} round-trips"


@check("contracts: adversarial inputs rejected with field path")
def _():
    M = C.ModelManifest
    bad_bbox = json.loads(json.dumps(SAMPLES["ModelManifest"]))
    bad_bbox["outputs"][0]["citations"][0]["bbox_norm"][1] = 1.01
    msg = expect_error(lambda: M.from_dict(bad_bbox), C.ContractError)
    assert "outputs[0]" in msg and "bbox_norm" in msg, msg
    cases = [
        (C.Citation, cit(bbox_norm=[-0.01, 0, 0.5, 0.5]), "bbox_norm"),
        (C.Citation, cit(bbox_norm=[0.5, 0, 0.4, 0.5]), "bbox_norm"),
        (C.Citation, cit(bbox_norm=[0, 0, float("nan"), 1]), "bbox_norm"),
        (C.Citation, cit(bbox_norm=[0, 0, 1]), "bbox_norm"),
        (C.Citation, cit(sha256_span_hash="a" * 63), "sha256_span_hash"),
        (C.Citation, cit(sha256_span_hash="A" * 64), "sha256_span_hash"),
        (C.Citation, cit(sha256_span_hash="g" * 64), "sha256_span_hash"),
        (C.Citation, cit(page=True), "page"),
        (C.Citation, cit(evil=1), "evil"),
        (C.ModelSpec, {"ticker": "X", "model_type": "ponzi"}, "model_type"),
        (C.ModelSpec, {"ticker": "X", "model_type": "lbo", "years": [2025, 2024]}, "years"),
        (C.ModelManifest, {"workbook_sha256": H, "outputs": [SAMPLES["ModelManifest"]["outputs"][1]] * 2}, "outputs"),
        (C.ValidationReport, dict(SAMPLES["ValidationReport"], passed=True), ""),
        (C.Job, {"id": "j", "kind": "k", "status": "done"}, "status"),
        (C.Job, {"id": "j", "kind": "k", "cost_usd": -1}, "cost_usd"),
    ]
    for cls, d, needle in cases:
        m = expect_error(lambda: cls.from_dict(d), C.ContractError)
        assert needle in m, (cls.__name__, needle, m)
    expect_error(lambda: C.Citation.from_json('{"doc_id": '), C.ContractError)
    expect_error(lambda: C.Citation.from_json('{"doc_id":"d","sha256_span_hash":"%s","bbox_norm":[0,0,NaN,1]}' % H),
                 C.ContractError)
    return f"{len(cases) + 3} adversarial cases"


@check("contracts: mutation after construction caught by validate()")
def _():
    c = C.Citation.from_dict(cit())
    try:
        c.sha256_span_hash = "zz"
    except Exception:
        return "frozen"
    expect_error(c.validate, C.ContractError)


@check("contracts: sha256_hex matches hashlib")
def _():
    assert C.sha256_hex("héllo") == hashlib.sha256("héllo".encode()).hexdigest()
    assert C.sha256_hex(b"\x00") == hashlib.sha256(b"\x00").hexdigest()


@check("contracts: random fuzz never escapes ContractError")
def _():
    rng = random.Random(7)
    junk = [None, 1, -1, 1.5, float("inf"), "", "x" * 3, [], {}, [1, 2], {"a": 1}, True]
    n = 0
    for cls in C.CONTRACTS:
        for _ in range(60):
            d = {k: rng.choice(junk) for k in rng.sample(["id", "doc_id", "page", "bbox_norm", "outputs", "slides",
                                                          "status", "findings", "versions", "name", "ticker",
                                                          "model_type", "nodes", "edges"], 4)}
            try:
                cls.from_dict(d)
            except C.ContractError:
                pass
            n += 1
        for bad in (None, [], "str", 3):
            try:
                cls.from_dict(bad)
            except C.ContractError:
                pass
    return f"{n} fuzz inputs"


# ------------------------------------------------------------------ storage
from om import storage as S  # noqa: E402


def _ref_sign(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


@check("storage: SigV4 header auth = AWS doc vector")
def _():
    auth = S.sigv4_authorization(
        "GET", "examplebucket.s3.amazonaws.com", "/test.txt",
        {"host": "examplebucket.s3.amazonaws.com", "range": "bytes=0-9",
         "x-amz-content-sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
         "x-amz-date": "20130524T000000Z"},
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1", "20130524T000000Z")
    assert auth.endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"), auth


@check("storage: SigV4 presign = AWS doc vector")
def _():
    url = S.sigv4_presign("GET", "examplebucket.s3.amazonaws.com", "/test.txt", 86400,
                          "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1",
                          "20130524T000000Z")
    assert "X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404" in url, url


@check("storage: S3 store via fake transport; secret not in repr/headers")
def _():
    blobs = {}
    seen = []

    def transport(method, url, headers, body):
        seen.append((method, url, dict(headers)))
        key = url.split("?")[0].rsplit("/", 1)[-1]
        if method == "PUT":
            blobs[key] = body
            return 200, {}, b""
        if method == "GET" and key in blobs:
            return 200, {}, blobs[key]
        if method == "HEAD":
            return (200 if key in blobs else 404), {}, b""
        return 404, {}, b""

    secret = "SUPERSECRETvalue123456"
    s3 = S.S3BlobStore("http://minio:9000", "bkt", access_key="AK", secret_key=secret, transport=transport)
    k = s3.put(b"hello")
    assert k == hashlib.sha256(b"hello").hexdigest()
    assert s3.get(k) == b"hello"
    assert secret not in repr(s3)
    assert all(secret not in json.dumps(h) for _, _, h in seen)
    assert all("Authorization" in h or "authorization" in h for _, _, h in seen)
    expect_error(lambda: s3.get("../../etc/passwd"), (ValueError, S.StorageError))


@check("storage: local blobs content-addressed, traversal rejected")
def _():
    with tempfile.TemporaryDirectory() as d:
        b = S.LocalBlobStore(os.path.join(d, "blobs"))
        k = b.put(b"x" * 1000)
        assert b.get(k) == b"x" * 1000 and b.exists(k)
        assert b.put(b"x" * 1000) == k
        for bad in ("../" + k, k[:-1], k.upper(), "/etc/passwd", k + "/..", ""):
            expect_error(lambda: b.get(bad), (ValueError, S.StorageError))
        b.delete(k)
        assert not b.exists(k)


@check("storage: SQLite WAL + queue exactly-once under 16 threads, lease expiry")
def _():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "kv.sqlite")
        db = S.connect(p)
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal", mode
        db.close()
        kv = S.SQLiteKV(p)
        for i in range(300):
            kv.enqueue("q", json.dumps({"i": i}))
        got, lock = [], threading.Lock()

        def worker():
            mine = S.SQLiteKV(p)
            while True:
                lease = mine.dequeue("q", lease=60)
                if lease is None:
                    break
                with lock:
                    got.append(json.loads(lease.payload)["i"])
                mine.ack(lease)
        ts = [threading.Thread(target=worker) for _ in range(16)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert sorted(got) == list(range(300)), (len(got), len(set(got)))
        now = [1000.0]
        kv2 = S.SQLiteKV(os.path.join(d, "k2.sqlite"), clock=lambda: now[0])
        kv2.enqueue("q", "job")
        l1 = kv2.dequeue("q", lease=10)
        assert kv2.dequeue("q", lease=10) is None
        now[0] += 11
        l2 = kv2.dequeue("q", lease=10)
        assert l2 is not None and l2.attempts > l1.attempts
        assert kv2.incr("n") == 1 and kv2.incr("n", 5) == 6
        return "300 items once"


@check("storage: postgres DSN without driver fails clearly")
def _():
    try:
        import psycopg  # noqa: F401
        return "psycopg installed; skipped"
    except ImportError:
        expect_error(lambda: S.connect("postgres://u:p@h/db"), S.StorageError)


# Router/PII/replay and DealMemory sections are appended below.


# ------------------------------------------------------- PII / replay / router
from om import pii, replay  # noqa: E402
from om import llm as L  # noqa: E402

PII_TEXT = ("Call Jane Doe at +44 20 7946 0958 or (212) 555-0147, email jane.doe@bank.co.uk. "
            "IBAN GB82 WEST 1234 5698 7654 32, card 4111 1111 1111 1111, SSN 123-45-6789, NINO JG103759A. "
            "FY2024 revenue was $12.3bn, up 1,234.5 on 2023-12-31; CIK 0000320193; EBITDA 4,111.")
SECRETS = ["+44 20 7946 0958", "(212) 555-0147", "jane.doe@bank.co.uk", "GB82 WEST 1234 5698 7654 32",
           "4111 1111 1111 1111", "123-45-6789", "JG103759A", "Jane Doe"]
KEEP = ["FY2024", "$12.3bn", "1,234.5", "2023-12-31", "0000320193", "4,111"]


@check("pii: masks emails/phones/IBAN/card/SSN/NINO/names; keeps financials; round-trips")
def _():
    m = pii.Masker(names=("Jane Doe",))
    masked, mapping = m.mask(PII_TEXT)
    leaked = [s for s in SECRETS if s in masked]
    assert not leaked, leaked
    lost = [s for s in KEEP if s not in masked]
    assert not lost, (lost, masked)
    assert pii.unmask(masked, mapping) == PII_TEXT
    m2, _ = m.mask("again: jane.doe@bank.co.uk")
    assert [p for p in mapping if mapping[p] == "jane.doe@bank.co.uk"][0] in m2, "placeholder not stable"
    # invalid checksums must not be masked as IBAN / card
    neg, _ = pii.Masker().mask("ref 4111 1111 1111 1112 and GB00 WEST 1234 5698 7654 32")
    assert "4111 1111 1111 1112" in neg, neg
    return f"{len(mapping)} placeholders"


class _Fake:
    def __init__(self, reply=None, exc=None, name="fake"):
        self.name, self.model, self.reply, self.exc, self.seen = name, "m", reply, exc, []

    def complete_json(self, system, parts, schema, repair_note=None, **kw):
        self.seen.append(system + "\n" + "\n".join(p.text for p in parts))
        if self.exc:
            raise self.exc
        return L.Result(dict(self.reply or {"answer": "ok"}), {"input_tokens": 500, "output_tokens": 50},
                        f"{self.name}:m")


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


@check("router: provider never sees PII; record → replay with zero network")
def _():
    with tempfile.TemporaryDirectory() as d:
        old = {k: os.environ.get(k) for k in ("ACRETIA_LLM_FIXTURES", "ACRETIA_LLM_MODE")}
        os.environ["ACRETIA_LLM_FIXTURES"] = d
        try:
            fake = _Fake({"answer": "Reply to [EMAIL_1] please"})
            stage = L.TASK_STAGES["extraction"]
            r = L.Router(overrides={stage: fake}, mode="record")
            res = r.complete_task("extraction", "You extract.", [L.Part(PII_TEXT)], SCHEMA, job_id="J1",
                                  pii_names=["Jane Doe"])
            sent = fake.seen[0]
            assert not [s for s in SECRETS if s in sent], "PII reached provider"
            assert "jane.doe@bank.co.uk" in res.data["answer"], res.data
            files = os.listdir(d)
            assert files, "no fixture recorded"
            blob = open(os.path.join(d, files[0]), encoding="utf-8").read()
            assert not [s for s in SECRETS if s in blob], "PII in fixture"
            # replay with the network physically disabled
            real_socket, real_conn = socket.socket, socket.create_connection

            def boom(*a, **k):
                raise AssertionError("network call in replay mode")
            socket.socket, socket.create_connection = boom, boom
            try:
                r2 = L.Router(mode="replay")
                res2 = r2.complete_task("extraction", "You extract.", [L.Part(PII_TEXT)], SCHEMA, job_id="J2",
                                        pii_names=["Jane Doe"])
                assert res2.data == res.data, (res2.data, res.data)
                expect_error(lambda: r2.complete_task("extraction", "different", [L.Part("x")], SCHEMA),
                             replay.ReplayMiss)
            finally:
                socket.socket, socket.create_connection = real_socket, real_conn
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return "fixture PII-free; replay offline"


@check("router: fallback chain on 5xx/timeout, not on 4xx; meter sums per job")
def _():
    ok = _Fake({"answer": "B"}, name="b")
    chain = [_Fake(exc=L.TransportError("down", 503), name="a"), _Fake(exc=TimeoutError("t"), name="t"), ok]
    meter = L.Meter()
    r = L.Router(chains={"ask": chain}, mode="live", meter=meter)
    res = r.complete_json("ask", "s", [L.Part("q")], SCHEMA, job_id="JOB")
    assert res.data["answer"] == "B" and len(res.fallbacks) >= 2, res.fallbacks
    r.complete_json("ask", "s", [L.Part("q2")], SCHEMA, job_id="JOB")
    t = meter.totals("JOB")
    assert t["input_tokens"] == 1000 and t["output_tokens"] == 100 and t["calls"] == 2, t
    assert t["cost_usd"] > 0
    r4 = L.Router(chains={"ask": [_Fake(exc=L.TransportError("bad", 400)), _Fake({"answer": "no"})]}, mode="live")
    expect_error(lambda: r4.complete_json("ask", "s", [L.Part("q")], SCHEMA), L.LLMError)


@check("router: MeshPool key bound to llm.meshpool.ai only")
def _():
    good = "https://llm.meshpool.ai/v1"
    L.key_host_guard(good, L.MESHPOOL_HOST)
    bad = ["https://llm.meshpool.ai.evil.com/v1", "https://llm.meshpool.ai@evil.com/v1", "http://llm.meshpool.ai/v1",
           "https://llm.meshpool.ai:8443/v1", "https://evil.com/llm.meshpool.ai", "https://LLM.MESHPOOL.AI.evil.com",
           "https://xllm.meshpool.ai/v1", "https://llm.meshpool.ai./v1"]
    for u in bad:
        expect_error(lambda: L.key_host_guard(u, L.MESHPOOL_HOST), Exception)
    return f"{len(bad)} lookalikes refused"


@check("router: repo fixtures contain no PII-looking strings")
def _():
    d = os.path.join(ROOT, "tests", "fixtures", "llm")
    m = pii.Masker()
    for f in os.listdir(d):
        txt = open(os.path.join(d, f), encoding="utf-8").read()
        _, mp = m.mask(txt)
        assert not mp, (f, mp)
    return f"{len(os.listdir(d))} fixtures clean"


# ---------------------------------------------------------------- DealMemory
from om import deals as D  # noqa: E402
from om import xlsx as X  # noqa: E402
from om import pptx as P  # noqa: E402


def _book(rev, formula):
    wb = X.Workbook()
    s = wb.sheet("IS")
    s.set("A1", "Revenue")
    s.set("B1", rev)
    s.set("C1", 50)
    s.set("D1", formula)
    o = wb.sheet("Other")
    o.set("A1", "untouched")
    return wb.to_bytes()


def _deck(title):
    d = P.Deck()
    sl = d.slide() if hasattr(d, "slide") else d.add_slide()
    sl.text(title, 1, 1, 6, 1) if hasattr(sl, "text") else None
    return d.to_bytes()


@check("deals: xlsx diff exact, undo restores bytes, history monotonic, org isolation")
def _():
    with tempfile.TemporaryDirectory() as d:
        blobs = S.LocalBlobStore(os.path.join(d, "b"))
        st = D.DealStore(os.path.join(d, "deals.sqlite"), blobs)
        deal = st.create_deal("Project Atlas", definitions={"Adjusted EBITDA": "EBITDA + SBC"},
                              formatting={"units": "USD m"})
        v1 = _book(100, "=B1+C1")
        v2 = _book(120, "=B1*C1")
        st.save_deliverable(deal.deal_id, "model", v1, "xlsx")
        st.save_deliverable(deal.deal_id, "model", v2, "xlsx")
        diff = st.diff(deal.deal_id, "model", 1, 2)
        refs = sorted((c["sheet"], c["ref"]) for c in diff["changes"])
        assert refs == [("IS", "B1"), ("IS", "D1")], refs
        st.undo(deal.deal_id, "model")
        h = st.history(deal.deal_id, "model")
        assert [x["version"] for x in h] == [1, 2, 3], h
        assert st.get_version(deal.deal_id, "model", 3) == v1
        assert st.diff(deal.deal_id, "model", 1, 3)["identical"] is True
        st.restore(deal.deal_id, "model", 2)
        assert st.get_version(deal.deal_id, "model", 4) == v2
        for bad in (0, -1, 99, True, "1"):
            expect_error(lambda: st.get_version(deal.deal_id, "model", bad), D.DealError)
        expect_error(lambda: st.get("deal-000000000000"), D.DealError)
        st.save_deliverable(deal.deal_id, "junk", b"PK\x03\x04garbage", "xlsx")
        st.save_deliverable(deal.deal_id, "junk", b"not a zip", "xlsx")
        expect_error(lambda: st.diff(deal.deal_id, "junk", 1, 2), D.DealError)
        other = st.for_org("evilcorp")
        expect_error(lambda: other.get(deal.deal_id), D.DealError)
        expect_error(lambda: other.get_version(deal.deal_id, "model", 1), D.DealError)
        assert other.list() == []
        st.set_definition(deal.deal_id, "Net Debt", "Debt - cash")
        mem = st.get(deal.deal_id)
        assert C.DealMemory.from_json(mem.to_json()) == mem
        dd = st.diff_definitions(deal.deal_id, mem.versions[0].version, mem.versions[-1].version)
        assert "Net Debt" in json.dumps(dd)
    return "2-cell diff; undo byte-exact"


@check("deals: pptx text diff")
def _():
    def pptx_zip(text):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("ppt/slides/slide1.xml", '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/'
                       '2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
                       '<p:sp><p:txBody><a:p><a:r><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>'
                       '</p:sld>' % text)
            z.writestr("ppt/slides/slide2.xml", '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/'
                       '2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
                       '<p:sp><p:txBody><a:p><a:r><a:t>Same</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>'
                       '</p:sld>')
        return b.getvalue()
    with tempfile.TemporaryDirectory() as d:
        st = D.DealStore(os.path.join(d, "x.sqlite"), S.LocalBlobStore(os.path.join(d, "b")))
        deal = st.create_deal("Deck")
        st.save_deliverable(deal.deal_id, "deck", pptx_zip("Revenue grew 10%"), "pptx")
        st.save_deliverable(deal.deal_id, "deck", pptx_zip("Revenue grew 12%"), "pptx")
        ch = st.diff(deal.deal_id, "deck", 1, 2)["changes"]
        assert len(ch) == 1 and ch[0]["slide"] in (1, 0) and "Revenue grew 12%" in ch[0]["added"], ch


# --------------------------------------------------------------------- main
@check("hermetic: fake keys present, sockets patched, live-mode Router uses only fake providers (chain fallback + override)")
def _():
    import socket as _socket
    from om import llm as L
    fake_keys = {"MESHPOOL_API_KEY": "mp-fake\u2014key", "ANTHROPIC_API_KEY": "sk-ant-fake", "OPENAI_API_KEY": "sk-fake"}
    saved_env = {k: os.environ.get(k) for k in list(fake_keys) + ["ACRETIA_LLM_MODE"]}
    saved_sock = (_socket.socket, _socket.create_connection, _socket.getaddrinfo)
    attempts = []
    calls = []

    def boom(*a, **k):
        attempts.append(1)
        raise AssertionError("socket attempted")

    class Fake:
        def __init__(self, name, fail=False):
            self.name, self.model, self.fail = name, name + "-model", fail

        def complete_json(self, system, parts, schema, repair_note=None, **kw):
            calls.append(self.name)
            if self.fail:
                raise L.TransportError("503 service unavailable", status=503)
            return L.Result(data={"answer": self.name}, usage={"input": 1, "output": 1}, model=self.model)

    schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
    try:
        os.environ.update(fake_keys)
        os.environ["ACRETIA_LLM_MODE"] = "live"
        _socket.socket = _socket.create_connection = _socket.getaddrinfo = boom
        parts = [L.Part("hello")]
        r = L.Router(chains={"ask": [Fake("fail503", fail=True), Fake("ok")]}, mode="live").complete_json(
            "ask", "sys", parts, schema)
        assert r.data == {"answer": "ok"}, r.data
        assert calls == ["fail503", "ok"], calls
        calls.clear()
        r = L.Router(overrides={"ask": Fake("only")}, mode="live").complete_json("ask", "sys", parts, schema)
        assert r.data == {"answer": "only"} and calls == ["only"], (r.data, calls)
    finally:
        _socket.socket, _socket.create_connection, _socket.getaddrinfo = saved_sock
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert not attempts, f"{len(attempts)} socket attempts"
    assert not any(k in os.environ for k in fake_keys), "fake keys leaked after restore"
    return "chain fell through 503 to fake_ok; override used alone; 0 socket attempts"


def main() -> int:
    width = max(len(n) for n, _, _ in RESULTS)
    fails = 0
    for name, ok, detail in RESULTS:
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    print(f"\nM1 gate: {len(RESULTS) - fails}/{len(RESULTS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
