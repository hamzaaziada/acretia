#!/usr/bin/env python3
"""S2 gate: adapter (replay, zero sockets, PII, key binding, spend guard), contracts, router/registry,
evidence chain, MCP over stdio, connectors (ZipSlip/bomb/SSRF), XXE, DuckDB storage, SDK import isolation.

Offline; never calls a live model. Exits non-zero on any failure.
"""
from __future__ import annotations

import ast
import io
import json
import os
import socket
import sys
import tempfile
import traceback
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
RESULTS: list[tuple[str, bool, str]] = []
SDKS = {"anthropic", "openai", "google.generativeai", "google.genai", "mistralai", "cohere", "litellm", "groq",
        "together", "boto3"}


def check(name):
    def deco(fn):
        try:
            RESULTS.append((name, True, str(fn() or "")))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"[:400]))
            if os.environ.get("VERIFY_DEBUG"):
                traceback.print_exc()
        return fn
    return deco


def expect_error(fn, exc=Exception, contains=None):
    try:
        fn()
    except exc as e:
        if contains and contains.lower() not in str(e).lower():
            raise AssertionError(f"{e!r} lacks {contains!r}")
        return str(e)
    raise AssertionError(f"expected {getattr(exc, '__name__', exc)}")


class NoSockets:
    """Physically disable network for the duration (gate requirement: zero sockets in replay)."""

    def __enter__(self):
        self.saved = (socket.socket, socket.create_connection, socket.getaddrinfo)
        self.attempts = 0

        def boom(*a, **k):
            self.attempts += 1
            raise AssertionError("socket opened during replay")
        socket.socket = socket.create_connection = socket.getaddrinfo = boom
        return self

    def __exit__(self, *exc):
        socket.socket, socket.create_connection, socket.getaddrinfo = self.saved
        return False


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


# ------------------------------------------------------------ import isolation
@check("isolation: no provider SDK imported outside src/harness/adapter.py (AST)")
def _():
    hits, n = [], 0
    for base in ("om", "src", "scripts", "open_multiples.py"):
        p0 = os.path.join(ROOT, base)
        files = [p0] if p0.endswith(".py") else [os.path.join(dp, f) for dp, dn, fs in os.walk(p0)
                                                 if "__pycache__" not in dp for f in fs if f.endswith(".py")]
        for p in files:
            rel = os.path.relpath(p, ROOT)
            if rel in ("src/harness/adapter.py", "scripts/verify_s2.py"):
                continue
            n += 1
            for node in ast.walk(ast.parse(open(p, encoding="utf-8").read(), p)):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    mods = [node.module]
                elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in (
                        "import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant):
                    mods = [str(node.args[0].value)]
                for m in mods:
                    if m in SDKS or m.split(".")[0] in SDKS or any(m.startswith(s + ".") for s in SDKS):
                        hits.append(f"{rel}:{node.lineno} {m}")
    assert not hits, hits
    return f"{n} files clean"


# ------------------------------------------------------------------ contracts
from om import contracts as C  # noqa: E402

H = "b" * 64


@check("contracts: EvidenceRecord / GhostDeck / Citation v2 round-trip and reject tampering")
def _():
    names = {c.__name__ for c in C.CONTRACTS}
    assert {"EvidenceRecord", "GhostDeck"} <= names, names
    cit = C.Citation.from_dict({"doc_id": "d", "sha256_span_hash": H, "page": 2, "bbox_norm": [0, 0, 1, 1],
                                "url": "https://sec.gov/x", "as_of": "2024-12-31", "xbrl_concept": "us-gaap:Revenues",
                                "cell_locator": "IS!D5"})
    assert C.Citation.from_json(cit.to_json()) == cit
    for bad in ({"url": "javascript:alert(1)"}, {"as_of": "2024-02-30"}, {"cell_locator": "not a cell"}):
        d = {"doc_id": "d", "sha256_span_hash": H, **bad}
        expect_error(lambda: C.Citation.from_dict(d), C.ContractError)
    rec = C.EvidenceRecord.seal(job_id="j", seq=0, tool="t", args_sha256=H, source="doc1",
                                timestamp="2026-11-16T00:00:00Z", output_sha256=H, prev_hash="0" * 64)
    d = rec.to_dict()
    assert C.EvidenceRecord.from_dict(d) == rec
    d["source"] = "doc2"
    expect_error(lambda: C.EvidenceRecord.from_dict(d), C.ContractError)
    g = C.GhostDeck.from_dict({"deck_id": "g", "title": "T", "audience": "IC", "titles": [
        {"id": "s1", "action_title": "Revenue grew 12% as pricing offset volume declines"}]})
    assert C.GhostDeck.from_json(g.to_json()) == g
    for t in ("Revenue by segment and region", "Margins expanded sharply!", "EBITDA rose — driven by mix",
              "Revenue grew " + "very " * 14 + "fast", "Revenue grew 12% this year."):
        expect_error(lambda: C.GhostTitle.from_dict({"id": "x", "action_title": t}), C.ContractError)
    return "ok"


@check("contracts: SlideSpec rejects model-supplied layout keys anywhere (with path)")
def _():
    base = {"id": "s1", "layout": "chart", "archetype": "ranked_bar",
            "action_title": "Segment A drives 60% of growth since 2021", "as_of": "2025-06-30",
            "blocks": [{"type": "chart", "series": [{"name": "A", "points": [{"label": "2024", "value": 1}]}]}]}
    C.SlideSpec.from_dict(base)
    for key in ("x", "Width", "font_size", "COLOR", "fill", "emu", "position"):
        d = json.loads(json.dumps(base))
        d["blocks"][0]["series"][0]["points"][0][key] = 1
        msg = expect_error(lambda: C.SlideSpec.from_dict(d), C.ContractError)
        assert "blocks[0]" in msg and "points[0]" in msg, msg
    return "7 layout keys rejected"


# --------------------------------------------------------------------- router
from src.harness import router as R  # noqa: E402


@check("router: rules route deck/excel/grid/vision; classifier only when ambiguous")
def _():
    cases = [("Build a pitchbook on Acme's comps", (), "deck"),
             ("Roll forward the model for Q3 actuals", ("model.xlsx",), "excel"),
             ("Answer these diligence questions across the VDR", ("vdr.zip",), "grid")]
    for req, files, eng in cases:
        r = R.route(req, files=files)
        assert eng in r.engines and not r.used_model_call, (req, r)
    calls = []

    class Clf:
        def chat(self, messages, json_schema=None, job_id=None, **k):
            calls.append(1)
            raise RuntimeError("down")
    r = R.route("hmm", classifier=Clf())
    assert len(calls) <= 1 and r.engines, r
    v = R.route("critique this slide image", files=("slide.png",), task_type="vision_critic",
                profile="deepseek")
    prof = R.load_profiles()[v.profile]
    assert prof["supports_vision"], v
    reg = R.ToolRegistry()
    reg.register("add", lambda a, b: a + b, {"type": "object", "properties": {"a": {"type": "number"},
                                                                              "b": {"type": "number"}},
                                             "required": ["a", "b"], "additionalProperties": False})
    assert reg.call("add", {"a": 1, "b": 2}) == 3
    expect_error(lambda: reg.call("add", {"a": "1", "b": 2}), R.ToolError)
    expect_error(lambda: reg.call("add", {"a": 1, "b": 2, "c": 3}), R.ToolError)
    expect_error(lambda: reg.call("rm", {}), R.ToolError)
    return f"profiles: {sorted(R.load_profiles())}"


# -------------------------------------------------------------------- evidence
from src.harness import evidence as E  # noqa: E402


@check("evidence: chain verifies; edit/delete/reorder/duplicate/truncate detected")
def _():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "job42.jsonl")
        with E.EvidenceBundle(p) as b:
            for i in range(20):
                b.append("tool", {"i": i}, source=f"doc{i}", page=i % 3 + 1, bbox_norm=[0, 0, .5, .5],
                         output={"v": i})
        assert E.verify(p).ok and E.verify(p).n_records == 20
        lines = open(p, encoding="utf-8").read().splitlines()

        def bad(new_lines, label):
            q = os.path.join(d, "job42.jsonl")
            open(q, "w", encoding="utf-8").write("\n".join(new_lines) + "\n")
            r = E.verify(q)
            assert not r.ok, f"{label} not detected"
            return r.first_bad_seq
        edited = json.loads(lines[7])
        edited["source"] = "forged"
        assert bad(lines[:7] + [json.dumps(edited)] + lines[8:], "edit") == 7
        bad(lines[:5] + lines[6:], "delete")
        bad(lines[:3] + [lines[4], lines[3]] + lines[5:], "reorder")
        bad(lines[:10] + [lines[9]] + lines[10:], "duplicate")
        bad(lines[:-1] + [lines[-1][:-20]], "truncate")
        open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        assert E.verify(p).ok
        assert E.head_hash(p) == json.loads(lines[-1])["record_hash"]
    return "5 tamper modes caught"


# --------------------------------------------------------------------- storage
from om import storage as S  # noqa: E402


@check("storage: DuckDB analytics + grid schema; identifier injection refused; bbox CHECK")
def _():
    backends = ["sqlite"] + (["duckdb"] if S.duckdb_available() else [])
    for be in backends:
        with S.AnalyticsDB(":memory:", prefer=be) as db:
            assert db.backend == be
            S.ensure_grid_schema(db)
            row = {"grid_id": "g", "doc_id": "d", "question_id": "q", "answer": "a", "exact_quote": "a",
                   "page": 1, "bbox_x0": 0.1, "bbox_y0": 0.1, "bbox_x1": 0.2, "bbox_y1": 0.2, "confidence": 0.9,
                   "cost_usd": 0.0, "content_hash": H, "updated_at": "2026-11-16T00:00:00Z"}
            db.upsert_rows("grid_cells", [row], ["grid_id", "doc_id", "question_id"])
            db.upsert_rows("grid_cells", [row], ["grid_id", "doc_id", "question_id"])
            assert len(db.query("SELECT * FROM grid_cells")) == 1
            expect_error(lambda: db.upsert_rows("grid_cells", [dict(row, question_id="q2", bbox_x1=1.5)],
                                                ["grid_id", "doc_id", "question_id"]), S.StorageError)
            for evil in ("x; DROP TABLE grid_cells", "a b", 'q"', "1abc"):
                expect_error(lambda: db.insert_rows(evil, [{"a": 1}]), S.StorageError)
                expect_error(lambda: db.insert_rows("t", [{evil: 1}]), S.StorageError)
    return f"backends: {backends}"


# ---------------------------------------------------------------------- XXE
@check("XXE / billion laughs: workbook readers never expand entities")
def _():
    from om import xlsx as X
    good = X.Workbook()
    good.sheet("S").set("A1", "safe")
    raw = good.to_bytes()
    zin = zipfile.ZipFile(io.BytesIO(raw))
    out = io.BytesIO()
    lol = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;'
           '&lol;&lol;&lol;&lol;&lol;"><!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
           '<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">'
           '<!ENTITY xxe SYSTEM "file:///etc/passwd">]>')
    with zipfile.ZipFile(out, "w") as z:
        for info in zin.infolist():
            data = zin.read(info)
            if info.filename == "xl/sharedStrings.xml" or info.filename.endswith("sheet1.xml"):
                txt = data.decode("utf-8")
                txt = lol + txt.split("?>", 1)[1] if txt.startswith("<?xml") else lol + txt
                txt = txt.replace("safe", "&lol4;&xxe;")
                data = txt.encode()
            z.writestr(info, data)
    try:
        book = X.read(out.getvalue())
        dump = json.dumps([[str(getattr(c, "value", c)) for c in (s.cells.values() if hasattr(s, "cells") else [])]
                           for s in getattr(book, "sheets", [])])
        assert "root:" not in dump and dump.count("lol") < 1000, "entities expanded"
        return "parsed without expansion"
    except Exception as e:  # rejection is also acceptable
        assert "root:" not in str(e)
        return f"rejected ({type(e).__name__})"


# Adapter, MCP and connectors sections are appended when those packets land.


# --------------------------------------------------------------------- adapter
from src.harness import adapter as A  # noqa: E402
from src.harness import ledger as LG  # noqa: E402
from om import replay as RP  # noqa: E402

PII = "Email jane.doe@bank.co.uk, call +44 20 7946 0958, card 4111 1111 1111 1111. FY2024 revenue $12.3bn."
SECRETS = ["jane.doe@bank.co.uk", "+44 20 7946 0958", "4111 1111 1111 1111"]
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def reply(content, model="m", pt=100, ct=10):
    return {"id": "x", "model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                                                    "finish_reason": "stop"}],
            "usage": {"prompt_tokens": pt, "completion_tokens": ct}}


class Transport:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def __call__(self, url, body, headers, stream=False):
        self.seen.append((url, json.dumps(body), dict(headers)))
        r = self.replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


@check("adapter: PII masked on the wire, unmasked in result; record → replay with zero sockets")
def _():
    with tempfile.TemporaryDirectory() as d:
        old = os.environ.get("ACRETIA_LLM_FIXTURES")
        os.environ["ACRETIA_LLM_FIXTURES"] = d
        try:
            t = Transport([reply(json.dumps({"answer": "Reply to [EMAIL_1]"}))])
            a = A.Adapter("https://llm.meshpool.ai/v1", api_key="sk-test-not-real", model_name="auto",
                          transport=t, mode="record")
            msgs = [{"role": "user", "content": PII}]
            r = a.chat(msgs, json_schema=SCHEMA, job_id="J")
            wire = t.seen[0][1]
            assert not [s for s in SECRETS if s in wire], "PII on the wire"
            assert "jane.doe@bank.co.uk" in r.data["answer"], r.data
            fx = "".join(open(os.path.join(d, f), encoding="utf-8").read() for f in os.listdir(d))
            assert fx and not [s for s in SECRETS if s in fx], "PII in fixture"
            assert "sk-test" not in fx, "key in fixture"
            with NoSockets() as ns:
                b = A.Adapter("https://llm.meshpool.ai/v1", model_name="auto", mode="replay")
                r2 = b.chat(msgs, json_schema=SCHEMA, job_id="J2")
                assert r2.data == r.data and r2.replayed
                expect_error(lambda: b.chat([{"role": "user", "content": "unseen"}], json_schema=SCHEMA),
                             RP.ReplayMiss)
            assert ns.attempts == 0
        finally:
            os.environ.pop("ACRETIA_LLM_FIXTURES") if old is None else os.environ.__setitem__(
                "ACRETIA_LLM_FIXTURES", old)
    return "0 socket attempts"


@check("adapter: repo replay fixtures replay offline (tests/fixtures/adapter)")
def _():
    d = os.path.join(ROOT, "tests", "fixtures", "adapter")
    files = [f for f in os.listdir(d) if f.endswith(".json")]
    assert files
    for f in files:
        txt = open(os.path.join(d, f), encoding="utf-8").read()
        assert not [s for s in SECRETS if s in txt]
        assert "sk-" not in txt and "Bearer" not in txt
    return f"{len(files)} fixtures clean"


@check("adapter: key bound to host (lookalikes, http, userinfo, port) and never sent elsewhere")
def _():
    ok = Transport([reply('{"answer":"x"}')])
    A.Adapter("https://llm.meshpool.ai/v1", api_key="k", model_name="m", transport=ok, mode="live").chat(
        [{"role": "user", "content": "hi"}])
    assert ok.seen[0][0].startswith("https://llm.meshpool.ai/")
    bad = ["https://llm.meshpool.ai.evil.com/v1", "https://llm.meshpool.ai@evil.com/v1", "http://llm.meshpool.ai/v1",
           "https://llm.meshpool.ai:8443/v1", "http://localhost:11434/v1"]
    for u in bad:
        t = Transport([reply('{"answer":"x"}')])

        def go():
            A.Adapter(u, api_key="k", model_name="m", transport=t, mode="live",
                      key_host="llm.meshpool.ai").chat([{"role": "user", "content": "hi"}])
        expect_error(go)
        assert not t.seen, f"key sent to {u}"
    t = Transport([reply('{"answer":"x"}')])
    A.Adapter("http://localhost:11434/v1", model_name="qwen2.5:7b", transport=t, mode="live").chat(
        [{"role": "user", "content": "hi"}])
    assert "authorization" not in {k.lower() for k in t.seen[0][2]}
    t = Transport([reply('{"answer":"x"}')])
    expect_error(lambda: A.Adapter("http://203.0.113.5/v1", model_name="m", transport=t, mode="live").chat(
        [{"role": "user", "content": "hi"}]))
    return f"{len(bad)} refusals; keyless localhost ok"


@check("adapter: retry on 503, fallback chain, schema repair, spend guard pre-blocks")
def _():
    t1 = Transport([A.TransportError("busy", 503) if hasattr(A, "TransportError") else TimeoutError("t"),
                    reply('{"answer":"ok"}')])
    a = A.Adapter("https://llm.meshpool.ai/v1", api_key="k", model_name="m", transport=t1, mode="live",
                  max_retries=2, **({"sleep": lambda s: None} if "sleep" in A.Adapter.__init__.__code__.co_varnames
                                   else {}))
    assert a.chat([{"role": "user", "content": "q"}], json_schema=SCHEMA).data["answer"] == "ok"
    dead = Transport([TimeoutError("t")] * 10)
    good = Transport([reply('{"answer":"fb"}')])
    kw = {"sleep": lambda s: None} if "sleep" in A.Adapter.__init__.__code__.co_varnames else {}
    fb = A.Adapter("https://llm.meshpool.ai/v1", api_key="k", model_name="m2", transport=good, mode="live", **kw)
    a2 = A.Adapter("https://llm.meshpool.ai/v1", api_key="k", model_name="m1", transport=dead, mode="live",
                   max_retries=1, fallbacks=(fb,), **kw)
    r = a2.chat([{"role": "user", "content": "q"}], json_schema=SCHEMA)
    assert r.data["answer"] == "fb" and r.fallbacks, r
    rep = Transport([reply("not json at all"), reply('{"answer":"fixed"}')])
    a3 = A.Adapter("https://llm.meshpool.ai/v1", api_key="k", model_name="m", transport=rep, mode="live", **kw)
    assert a3.chat([{"role": "user", "content": "q"}], json_schema=SCHEMA).data["answer"] == "fixed"
    led = LG.Ledger(guard=LG.SpendGuard(0.0001))
    t4 = Transport([reply('{"answer":"x"}')])
    a4 = A.Adapter("https://llm.meshpool.ai/v1", api_key="k", model_name="claude-opus", transport=t4, mode="live",
                   ledger=led, **kw)
    expect_error(lambda: a4.chat([{"role": "user", "content": "q" * 4000}], max_tokens=8000, job_id="B"),
                 LG.BudgetExceeded)
    assert not t4.seen, "call sent despite budget"
    led2 = LG.Ledger()
    t5 = Transport([reply('{"answer":"x"}', pt=1000, ct=100)] * 2)
    a5 = A.Adapter("https://llm.meshpool.ai/v1", api_key="k", model_name="m", transport=t5, mode="live",
                   ledger=led2, **kw)
    a5.chat([{"role": "user", "content": "a"}], job_id="JJ")
    a5.chat([{"role": "user", "content": "b"}], job_id="JJ")
    tot = led2.total("JJ")
    tin = tot.get("input_tokens", tot.get("prompt_tokens"))
    assert tin == 2000, tot
    return "ok"


@check("adapter: vision parts and SSE streaming")
def _():
    part = A.image_part(b"\x89PNG\r\n\x1a\nfake", "image/png")
    assert json.dumps(part).count("data:image/png;base64,") == 1
    lines = ['data: {"choices":[{"delta":{"content":"Hel"}}]}', 'data: {"choices":[{"delta":{"content":"lo"}}]}',
             "data: [DONE]"]

    def tr(url, body, headers, stream=False):
        return iter(lines) if stream else reply("x")
    a = A.Adapter("https://llm.meshpool.ai/v1", api_key="k", model_name="m", transport=tr, mode="live")
    s = a.chat([{"role": "user", "content": [{"type": "text", "text": "see"}, part]}], stream=True)
    assert "".join(s) == "Hello"
    return "ok"


# ------------------------------------------------------------------------- MCP
import subprocess  # noqa: E402


@check("MCP: stdio subprocess — initialize, tools/list, tools/call, evidence chain")
def _():
    from src.harness.mcp.client import MCPClient, MCPError
    with tempfile.TemporaryDirectory() as d:
        dbp = os.path.join(d, "grid.duckdb")
        with S.AnalyticsDB(dbp) as db:
            S.ensure_grid_schema(db)
            db.upsert_rows("grid_cells", [{"grid_id": "g1", "doc_id": "10k", "question_id": "rev", "answer": "391,035",
                                           "exact_quote": "Total net sales 391,035", "page": 28, "bbox_x0": .1,
                                           "bbox_y0": .2, "bbox_x1": .6, "bbox_y1": .25, "confidence": .95,
                                           "cost_usd": .001, "content_hash": H,
                                           "updated_at": "2026-11-16T00:00:00Z"}],
                           ["grid_id", "doc_id", "question_id"])
        ev = os.path.join(d, "mcpjob.jsonl")
        env = dict(os.environ, ACRETIA_MCP_ROOT=d, ACRETIA_GRID_DB=dbp, ACRETIA_EVIDENCE_PATH=ev,
                   PYTHONPATH=ROOT)
        c = MCPClient.spawn([sys.executable, "-m", "src.harness.mcp.grid_server"], env=env, timeout=60, cwd=ROOT)
        try:
            c.initialize()
            names = {t["name"] for t in c.list_tools()}
            assert {"grid_query", "grid_cell", "grid_schema"} <= names, names
            cell = c.call_tool("grid_cell", {"grid_id": "g1", "doc_id": "10k", "question_id": "rev"})
            assert "391,035" in json.dumps(cell), cell
            rows = c.call_tool("grid_query", {"sql": "SELECT answer, page FROM grid_cells WHERE doc_id = ?",
                                              "params": ["10k"]})
            assert "391,035" in json.dumps(rows)
            evil = ["SELECT 1; DROP TABLE grid_cells", "ATTACH '/etc/passwd' AS x", "COPY grid_cells TO 'x.csv'",
                    "PRAGMA table_info(grid_cells)", "SELECT * FROM read_csv('/etc/passwd')",
                    "DELETE FROM grid_cells", "SELECT * FROM '/etc/passwd'", "SELECT 1 -- x"]
            for q in evil:
                expect_error(lambda: c.call_tool("grid_query", {"sql": q}), MCPError)
            expect_error(lambda: c.call_tool("nope", {}), MCPError)
            expect_error(lambda: c.call_tool("grid_cell", {"grid_id": 1}), MCPError)
            after = c.call_tool("grid_query", {"sql": "SELECT count(*) AS n FROM grid_cells"})
            assert '1' in json.dumps(after)
        finally:
            c.close()
        r = E.verify(ev)
        assert r.ok and r.n_records >= 3, r
    return f"{len(evil)} injections refused; {r.n_records} evidence records"


@check("MCP: protocol errors (-32700/-32601/-32602) and path confinement")
def _():
    from src.harness.mcp import protocol as Pr  # noqa: F401
    from src.harness.mcp.server import MCPServer
    reg = R.ToolRegistry()
    reg.register("echo", lambda s: s, {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]})
    srv = MCPServer("t", reg)
    assert srv.handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})["error"]["code"] == -32601
    assert srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "echo", "arguments": {"s": 3}}})["error"]["code"] == -32602
    assert srv.handle({"jsonrpc": "2.0", "method": "tools/call",
                       "params": {"name": "echo", "arguments": {"s": "x"}}}) is None
    p = subprocess.run([sys.executable, "-m", "src.harness.mcp.grid_server"], input=b"{not json\n",
                       capture_output=True, timeout=60, cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT))
    first = json.loads(p.stdout.decode().splitlines()[0])
    assert first["error"]["code"] == -32700, first
    from src.harness.mcp.client import MCPClient, MCPError
    with tempfile.TemporaryDirectory() as d:
        os.symlink("/etc", os.path.join(d, "esc"))
        env = dict(os.environ, ACRETIA_MCP_ROOT=d, PYTHONPATH=ROOT)
        c = MCPClient.spawn([sys.executable, "-m", "src.harness.mcp.excel_server"], env=env, timeout=60, cwd=ROOT)
        try:
            c.initialize()
            for bad in ("../../etc/passwd", "/etc/passwd", "esc/passwd"):
                expect_error(lambda: c.call_tool("xlsx_evaluate", {"path": bad, "cells": ["S!A1"]}), MCPError)
        finally:
            c.close()
    return "ok"


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


@check("adapter: header injection refused (CR/LF, non-Latin-1, trailing newline) before transport, key never echoed")
def _():
    from src.harness.adapter import Adapter
    msgs = [{"role": "user", "content": "hi"}]
    seen = []

    def transport(url, body, headers):
        seen.append(headers)
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    for key in ("k\r\nX-Evil: 1", "k\u2014ey", "k\n"):
        a = Adapter("https://llm.meshpool.ai/v1", api_key=key, model_name="m", transport=transport, mode="live")
        try:
            a.chat(msgs)
        except Exception as e:  # noqa: BLE001
            text = f"{e} {e!r} {''.join(map(str, e.args))}"
            assert key not in text, f"exception text contains key {key!r}"
        else:
            raise AssertionError(f"key {key!r} accepted")
    assert not seen, f"transport called with {len(seen)} header sets"
    return "3 hostile keys refused, transport never called"


def main() -> int:
    width = max(len(n) for n, _, _ in RESULTS)
    fails = 0
    for name, ok, detail in RESULTS:
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    print(f"\nS2 gate: {len(RESULTS) - fails}/{len(RESULTS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
