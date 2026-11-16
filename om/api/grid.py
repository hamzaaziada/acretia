"""Matrix grid API (SPEC §4 grid; PLAN P-J2, S7.2; parity items 1-14).

Documents x prompts, every cell an extractive answer quoted verbatim from `document_pages.lines_json` with page + bbox, minted
as a citation token. Cells stream: a background thread fills `queued` cells and appends rows to `grid_events`; the SSE route tails
that table (replay-able through Last-Event-ID). Pure stdlib + om.matrix helpers + om.xlsx writer; no model call anywhere here
(a column's `model` is recorded, and a live engine is wired through the job runner, never from a request thread).

Tables owned: grids, grid_columns, grid_rows, grid_cells, grid_inputs, grid_events, grid_citations.
Tables read (owned by the documents worker): documents(id, org_id, deal_id, name, ...), document_pages(org_id, doc_id, page, text,
lines_json, tables_json). lines_json = [{"text": str, "bbox_norm": [x0, y0, x1, y1]}] (0..1, top-left origin); `bbox`/`box` accepted.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import threading
import time
from collections import defaultdict

from om import matrix as _matrix
from om.api import db as _db
from om.api.http import SSE, ApiError, Response, Route

SCHEMA = """
CREATE TABLE IF NOT EXISTS grids(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, deal_id TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL,
  auto_rows INTEGER NOT NULL DEFAULT 0, source_grid_id TEXT);
CREATE INDEX IF NOT EXISTS grids_deal ON grids(org_id, deal_id);
CREATE TABLE IF NOT EXISTS grid_columns(
  id TEXT PRIMARY KEY, grid_id TEXT NOT NULL, org_id TEXT NOT NULL, position INTEGER NOT NULL, name TEXT NOT NULL,
  prompt TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'text', depends_on_json TEXT NOT NULL DEFAULT '{}',
  run_condition_json TEXT, model TEXT NOT NULL DEFAULT 'extractive', format_rules_json TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS grid_columns_grid ON grid_columns(grid_id);
CREATE TABLE IF NOT EXISTS grid_rows(
  id TEXT PRIMARY KEY, grid_id TEXT NOT NULL, org_id TEXT NOT NULL, doc_id TEXT NOT NULL, position INTEGER NOT NULL,
  folder TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS grid_rows_grid ON grid_rows(grid_id);
CREATE TABLE IF NOT EXISTS grid_cells(
  grid_id TEXT NOT NULL, row_id TEXT NOT NULL, col_id TEXT NOT NULL, org_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('queued','running','done','skipped','failed')),
  value TEXT NOT NULL DEFAULT '', citations_json TEXT NOT NULL DEFAULT '[]', meta_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL, PRIMARY KEY(grid_id, row_id, col_id));
CREATE INDEX IF NOT EXISTS grid_cells_state ON grid_cells(grid_id, state);
CREATE TABLE IF NOT EXISTS grid_inputs(
  grid_id TEXT NOT NULL, org_id TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(grid_id, name));
CREATE TABLE IF NOT EXISTS grid_events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, grid_id TEXT NOT NULL, org_id TEXT NOT NULL, type TEXT NOT NULL, data_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS grid_events_grid ON grid_events(grid_id, seq);
CREATE TABLE IF NOT EXISTS grid_citations(
  token TEXT PRIMARY KEY, org_id TEXT NOT NULL, doc_id TEXT NOT NULL, page INTEGER, bbox_json TEXT, quote TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
"""

TYPES = ("text", "number", "date", "yes-no", "list", "percent", "currency", "boolean")
MODELS = [
    {"id": "extractive", "label": "Extractive (offline, verbatim quotes)", "available": True},
    {"id": "claude-sonnet", "label": "Claude Sonnet (live; needs adapter keys)", "available": False},
]
OPS = ("eq", "ne", "contains", "not_contains", "gt", "gte", "lt", "lte", "empty", "not_empty", "yes", "no")
TONES = ("positive", "warning", "negative", "info", "accent")
REF_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NOT_FOUND = "Not found in document"
MAX_COLUMNS = 60
FILL_WORKERS_LOCK: dict[str, threading.Lock] = defaultdict(threading.Lock)
GEN: dict[str, int] = defaultdict(int)
_GLOCK = threading.Lock()


# --------------------------------------------------------------------------- small helpers
def _json(s, default):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


def _nf() -> ApiError:
    return ApiError(404, "not_found", "No such resource.")


def _bad(msg: str, hint: str, code: str = "bad_request") -> ApiError:
    return ApiError(400, code, msg, hint)


def _body(ctx) -> dict:
    return ctx.json if isinstance(ctx.json, dict) else {}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _grid(ctx, grid_id: str):
    r = ctx.conn.execute("SELECT * FROM grids WHERE id=? AND org_id=?", (grid_id, ctx.org_id)).fetchone()
    if r is None:
        raise _nf()
    return r


def _deal_ok(ctx, deal_id: str) -> None:
    try:
        r = ctx.conn.execute("SELECT 1 FROM deals WHERE org_id=? AND deal_id=?", (ctx.org_id, deal_id)).fetchone()
    except Exception:
        r = None
    if r is None:
        raise _nf()


def _doc_row(ctx, doc_id: str):
    r = ctx.conn.execute("SELECT * FROM documents WHERE id=? AND org_id=?", (doc_id, ctx.org_id)).fetchone()
    if r is None:
        raise _nf()
    return r


def _has_col(conn, table: str, col: str) -> bool:
    try:
        return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))
    except Exception:
        return False


def _split_name(name: str) -> tuple[str, str]:
    p = str(name or "").replace("\\", "/").strip("/")
    if "/" in p:
        folder, _, base = p.rpartition("/")
        return folder, base
    return "", p


def _doc_list(ctx, deal_id: str, ids=None) -> list[dict]:
    """Indexed documents of a deal (those with at least one page row)."""
    has_folder = _has_col(ctx.conn, "documents", "folder")
    q = ("SELECT d.id, d.name" + (", d.folder" if has_folder else "") + " FROM documents d WHERE d.org_id=? AND d.deal_id=? "
         "AND EXISTS (SELECT 1 FROM document_pages p WHERE p.org_id=d.org_id AND p.doc_id=d.id) ORDER BY d.name")
    out = []
    for r in ctx.conn.execute(q, (ctx.org_id, deal_id)):
        folder, base = _split_name(r["name"])
        if has_folder and r["folder"]:
            folder = r["folder"]
        if ids is None or r["id"] in ids:
            out.append({"id": r["id"], "name": base or r["name"], "full_name": r["name"], "folder": folder})
    return out


# --------------------------------------------------------------------------- citations
def _mint(conn, org_id: str, doc_id: str, page, bbox, quote: str) -> str:
    """A citation token for (doc, page, bbox, quote): the shared minter when present, else our own deterministic table."""
    try:
        from om.api import citations as _c  # type: ignore
        tok = _c.mint(conn, org_id, doc_id=doc_id, page=page, bbox_norm=list(bbox) if bbox else None, quote=quote)
        if isinstance(tok, dict):
            tok = tok.get("token")
        if isinstance(tok, str) and tok:
            return tok
    except Exception:
        pass
    token = "gc_" + hashlib.sha256(f"{org_id}|{doc_id}|{page}|{quote}".encode("utf-8")).hexdigest()[:20]
    conn.execute("INSERT OR IGNORE INTO grid_citations(token, org_id, doc_id, page, bbox_json, quote, created_at) VALUES(?,?,?,?,?,?,?)",
                 (token, org_id, doc_id, page, json.dumps(list(bbox)) if bbox else None, quote, _db.now()))
    return token


# --------------------------------------------------------------------------- pages and the extractive engine
def _parse_lines(raw, text: str) -> list[dict]:
    data = _json(raw, None)
    if isinstance(data, dict):
        data = data.get("lines")
    out = []
    if isinstance(data, list):
        for ln in data:
            if isinstance(ln, dict):
                t = str(ln.get("text") or "").strip()
                bb = ln.get("bbox_norm") or ln.get("bbox") or ln.get("box")
            elif isinstance(ln, (list, tuple)) and len(ln) >= 2 and isinstance(ln[0], str):
                t, bb = ln[0].strip(), ln[1]
            else:
                continue
            if not t:
                continue
            try:
                bb = [float(v) for v in bb][:4] if bb is not None and len(bb) >= 4 else None
            except (TypeError, ValueError):
                bb = None
            out.append({"text": t, "bbox": bb})
    if not out:
        out = [{"text": t.strip(), "bbox": None} for t in str(text or "").splitlines() if t.strip()]
    return out


def load_pages(conn, org_id: str, doc_ids) -> dict:
    """{doc_id: [{page, text, lines:[{text,bbox}]}]} in page order (one query for all documents)."""
    ids = list(dict.fromkeys(doc_ids))
    out: dict = {d: [] for d in ids}
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        qs = ",".join("?" * len(chunk))
        for r in conn.execute(f"SELECT doc_id, page, text, lines_json FROM document_pages WHERE org_id=? AND doc_id IN ({qs}) "
                              "ORDER BY doc_id, page", (org_id, *chunk)):
            out[r["doc_id"]].append({"page": r["page"], "text": r["text"] or "", "lines": _parse_lines(r["lines_json"], r["text"])})
    return out


def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [round(min(b[0] for b in boxes), 5), round(min(b[1] for b in boxes), 5),
            round(max(b[2] for b in boxes), 5), round(max(b[3] for b in boxes), 5)]


def _phrases(prompt: str) -> list[str]:
    words = re.findall(r"[a-z][a-z\-]+", prompt.lower())
    out = [f"{a} {b}" for a, b in zip(words, words[1:]) if a not in _matrix.STOP and b not in _matrix.STOP]
    out += [f"{a} {j} {b}" for a, j, b in zip(words, words[1:], words[2:])
            if j in ("of", "to", "in", "for", "and", "on") and a not in _matrix.STOP and b not in _matrix.STOP]
    return out


def _candidates(pages: list[dict], prompt: str, typ: str):
    """[(score, page, quote, bbox, nlines)] best-first: windows of 1-3 consecutive lines scored by stemmed term hits."""
    terms = _matrix.key_terms(prompt)
    if not terms:
        return []
    phr = _phrases(prompt)
    out = []
    for pg in pages:
        lines = pg["lines"]
        hits = [_matrix._stem_hits(l["text"], terms) for l in lines]
        for i in range(len(lines)):
            for n in (1, 2, 3):
                if i + n > len(lines):
                    break
                win = lines[i:i + n]
                if hits[i] == 0 and n > 1:
                    continue                                     # windows start on a matching line (tight quotes)
                text = " ".join(l["text"] for l in win)
                h = _matrix._stem_hits(text, terms)
                if h == 0:
                    continue
                low = text.lower()
                ph = sum(2.0 if p.count(" ") == 2 else 1.5 for p in phr if p in low)
                bonus = 0.0
                if typ in ("number", "currency", "percent", "date") and _typed(text, typ) is not None:
                    bonus = 0.5
                score = h + ph + bonus - 0.2 * (n - 1) - len(text) / 4000
                out.append((score, pg["page"], text, _union([l["bbox"] for l in win]), n))
    out.sort(key=lambda c: (-c[0], c[1]))
    return out


def _typed(text: str, typ: str):
    if typ in ("number", "currency"):
        m = _matrix.CURRENCY_RE.search(text) if typ == "currency" else None
        if m:
            return m.group(0).strip()
        m = _matrix.NUMBER_RE.search(text)
        return m.group(0) if m else None
    if typ == "percent":
        m = _matrix.PERCENT_RE.search(text)
        return m.group(0).strip() if m else None
    if typ == "date":
        m = _matrix.DATE_RE.search(text) or ISO_DATE.search(text)
        return m.group(0) if m else None
    return None


def _confidence(score: float, nterms: int) -> str:
    return "high" if score >= nterms + 1.5 else "medium" if score >= max(1.5, nterms * 0.6) else "low"


def answer_cell(pages: list[dict], prompt: str, typ: str) -> dict:
    """Extractive, verified answer: {found, answer, citations:[{page, bbox_norm, quote}], confidence, meta}."""
    typ = typ if typ in TYPES else "text"
    full = {p["page"]: _norm(" ".join(l["text"] for l in p["lines"]) + " " + p["text"]) for p in pages}
    cands = _candidates(pages, prompt, typ)
    terms = _matrix.key_terms(prompt)
    chosen: list = []
    want = 3 if typ == "list" else 1
    for score, page, quote, bbox, _n in cands:
        if score < 0.9:
            break
        if _norm(quote) not in full.get(page, ""):
            continue                                              # traceable or not shown
        if any(page == c[1] and (quote in c[2] or c[2] in quote) for c in chosen):
            continue
        chosen.append((score, page, quote, bbox))
        if len(chosen) >= want:
            break
    if typ == "yes-no":
        if chosen:
            s, page, quote, bbox = chosen[0]
            return {"found": True, "answer": "Yes", "citations": [{"page": page, "bbox_norm": bbox, "quote": quote}],
                    "confidence": _confidence(s, len(terms)), "meta": {}}
        return {"found": True, "answer": "No", "citations": [], "confidence": "low", "meta": {"note": "no matching passage"}}
    if not chosen:
        return {"found": False, "answer": NOT_FOUND, "citations": [], "confidence": None, "meta": {}}
    s0, page0, quote0, _b = chosen[0]
    if typ in ("number", "currency", "percent", "date"):
        val = _typed(quote0, typ)
        answer = val if val is not None else quote0
    elif typ == "list":
        answer = "; ".join(c[2] for c in chosen)
    else:
        answer = quote0
    return {"found": True, "answer": answer, "confidence": _confidence(s0, len(terms)), "meta": {},
            "citations": [{"page": p, "bbox_norm": b, "quote": q} for _s, p, q, b in chosen]}


# --------------------------------------------------------------------------- references, run conditions, formatting
def _refs(text: str) -> list[str]:
    return list(dict.fromkeys(m.strip() for m in REF_RE.findall(text or "")))


def _col_key(cols: list[dict], ref: str):
    for c in cols:
        if c["id"] == ref or _norm(c["name"]) == _norm(ref):
            return c
    return None


def _deps(cols: list[dict], prompt: str, cond, self_id: str | None = None) -> dict:
    cdeps, ideps = [], []
    for r in _refs(prompt):
        c = _col_key(cols, r)
        if c is not None and c["id"] != self_id:
            cdeps.append(c["id"])
        elif c is None:
            ideps.append(r)
    if isinstance(cond, dict) and cond.get("col"):
        c = _col_key(cols, str(cond["col"]))
        if c is not None and c["id"] != self_id:
            cdeps.append(c["id"])
    return {"cols": list(dict.fromkeys(cdeps)), "inputs": list(dict.fromkeys(ideps))}


def _topo(cols: list[dict]) -> list[dict]:
    """Columns in dependency order (stable by position); raises ApiError on a cycle."""
    by = {c["id"]: c for c in cols}
    indeg = {c["id"]: 0 for c in cols}
    nxt: dict = defaultdict(list)
    for c in cols:
        for d in c["depends_on"]["cols"]:
            if d in by:
                indeg[c["id"]] += 1
                nxt[d].append(c["id"])
    ready = sorted((cid for cid, n in indeg.items() if n == 0), key=lambda i: by[i]["position"])
    order = []
    while ready:
        cid = ready.pop(0)
        order.append(by[cid])
        for n in nxt[cid]:
            indeg[n] -= 1
            if indeg[n] == 0:
                ready.append(n)
        ready.sort(key=lambda i: by[i]["position"])
    if len(order) != len(cols):
        raise ApiError(400, "dependency_cycle", "These columns depend on each other in a loop.",
                       "Remove a {{reference}} or run condition so every column can be answered before the ones that use it.")
    return order


def _downstream(cols: list[dict], ids) -> set:
    out, frontier = set(ids), list(ids)
    while frontier:
        cur = frontier.pop()
        for c in cols:
            if cur in c["depends_on"]["cols"] and c["id"] not in out:
                out.add(c["id"])
                frontier.append(c["id"])
    return out


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("%", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _leaf(value, op: str, arg) -> bool:
    v = "" if value is None else str(value)
    a = "" if arg is None else str(arg)
    if op == "empty":
        return v.strip() == "" or v == NOT_FOUND
    if op == "not_empty":
        return v.strip() != "" and v != NOT_FOUND
    if op == "yes":
        return _norm(v) in ("yes", "true", "y")
    if op == "no":
        return _norm(v) in ("no", "false", "n")
    if op == "contains":
        return _norm(a) in _norm(v)
    if op == "not_contains":
        return _norm(a) not in _norm(v)
    if op in ("gt", "gte", "lt", "lte"):
        x, y = _num(v), _num(a)
        if x is None or y is None:
            return False
        return {"gt": x > y, "gte": x >= y, "lt": x < y, "lte": x <= y}[op]
    if op == "eq":
        x, y = _num(v), _num(a)
        return x == y if x is not None and y is not None else _norm(v) == _norm(a)
    if op == "ne":
        return not _leaf(value, "eq", arg)
    return False


def eval_tree(node, lookup, default_col) -> bool:
    """AND/OR rule tree. {"op": "and"|"or", "children": [...]} or a leaf {"col"?, "op", "value"?}. lookup(col) -> value."""
    if not isinstance(node, dict):
        return False
    op = str(node.get("op") or "").lower()
    if op in ("and", "or"):
        kids = [eval_tree(k, lookup, default_col) for k in node.get("children") or []]
        if not kids:
            return False
        return all(kids) if op == "and" else any(kids)
    return _leaf(lookup(node.get("col") or default_col), op, node.get("value"))


def _fmt(col: dict, lookup) -> dict | None:
    for rule in col["format_rules"]:
        tone = rule.get("tone")
        if tone in TONES and eval_tree(rule.get("when"), lookup, col["id"]):
            return {"tone": tone, "rule": rule.get("id") or rule.get("label") or ""}
    return None


def _skip_reason(col: dict, cols: list[dict], lookup) -> str | None:
    cond = col["run_condition"]
    if not isinstance(cond, dict) or not cond.get("col"):
        return None
    dep = _col_key(cols, str(cond["col"]))
    if dep is None:
        return None
    ok = _leaf(lookup(dep["id"]), str(cond.get("op") or "not_empty"), cond.get("value"))
    if ok:
        return None
    op = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "contains": "contains",
          "not_contains": "does not contain", "empty": "is empty", "not_empty": "is not empty", "yes": "is Yes", "no": "is No"}.get(
        str(cond.get("op")), str(cond.get("op")))
    arg = "" if cond.get("op") in ("empty", "not_empty", "yes", "no") else f" {cond.get('value')}"
    return f"{dep['name']} {op}{arg} was not met"


def _render_prompt(col: dict, cols: list[dict], inputs: dict, lookup) -> str:
    def sub(m):
        ref = m.group(1).strip()
        c = _col_key(cols, ref)
        if c is not None:
            return str(lookup(c["id"]) or "")
        return str(inputs.get(ref, ""))
    return REF_RE.sub(sub, col["prompt"])


# --------------------------------------------------------------------------- loading
def _load_cols(conn, grid_id: str, org_id: str) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM grid_columns WHERE grid_id=? AND org_id=? ORDER BY position, id", (grid_id, org_id)):
        out.append({"id": r["id"], "position": r["position"], "name": r["name"], "prompt": r["prompt"], "type": r["type"],
                    "depends_on": _json(r["depends_on_json"], {}) or {"cols": [], "inputs": []},
                    "run_condition": _json(r["run_condition_json"], None), "model": r["model"],
                    "format_rules": _json(r["format_rules_json"], [])})
        out[-1]["depends_on"].setdefault("cols", [])
        out[-1]["depends_on"].setdefault("inputs", [])
    return out


def _load_rows(conn, grid_id: str, org_id: str) -> list[dict]:
    rows = []
    q = ("SELECT r.id, r.doc_id, r.position, r.folder, d.name AS dname FROM grid_rows r LEFT JOIN documents d "
         "ON d.id=r.doc_id AND d.org_id=r.org_id WHERE r.grid_id=? AND r.org_id=? ORDER BY r.position, r.id")
    for r in conn.execute(q, (grid_id, org_id)):
        folder, base = _split_name(r["dname"] or r["doc_id"])
        rows.append({"id": r["id"], "doc_id": r["doc_id"], "position": r["position"], "name": base or r["doc_id"],
                     "folder": r["folder"] or folder})
    return rows


def _load_inputs(conn, grid_id: str, org_id: str) -> dict:
    return {r["name"]: r["value"] for r in conn.execute("SELECT name, value FROM grid_inputs WHERE grid_id=? AND org_id=? ORDER BY name",
                                                        (grid_id, org_id))}


def _cell_out(r, col: dict | None, lookup) -> dict:
    meta = _json(r["meta_json"], {})
    return {"row": r["row_id"], "col": r["col_id"], "state": r["state"], "value": r["value"],
            "citations": _json(r["citations_json"], []), "reason": meta.get("reason"), "confidence": meta.get("confidence"),
            "error": meta.get("error"), "engine": meta.get("engine"),
            "fmt": _fmt(col, lookup) if col is not None and col["format_rules"] and r["state"] == "done" else None,
            "updated_at": r["updated_at"]}


def _grid_payload(ctx, g) -> dict:
    cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
    rows = _load_rows(ctx.conn, g["id"], ctx.org_id)
    cells = list(ctx.conn.execute("SELECT * FROM grid_cells WHERE grid_id=? AND org_id=?", (g["id"], ctx.org_id)))
    vals = {(c["row_id"], c["col_id"]): c["value"] for c in cells if c["state"] == "done"}
    bycol = {c["id"]: c for c in cols}
    out_cells = []
    pending = 0

    def lookup_for(row_id):
        return lambda col_id: vals.get((row_id, col_id))
    for r in cells:
        if r["state"] in ("queued", "running"):
            pending += 1
        out_cells.append(_cell_out(r, bycol.get(r["col_id"]), lookup_for(r["row_id"])))
    cols_out = [{k: v for k, v in c.items()} for c in cols]
    return {"grid": {"id": g["id"], "deal_id": g["deal_id"], "name": g["name"], "created_at": g["created_at"],
                     "source_grid_id": g["source_grid_id"]},
            "columns": cols_out, "rows": rows, "cells": out_cells, "inputs": _load_inputs(ctx.conn, g["id"], ctx.org_id),
            "pending": pending, "models": MODELS, "types": list(TYPES[:5])}


# --------------------------------------------------------------------------- the filler (background thread)
def _worker_conn(conn):
    try:
        path = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    except Exception:
        path = ""
    if path:
        return _db.connect(path), True
    return conn, False


def _emit(conn, grid_id: str, org_id: str, type_: str, data: dict) -> None:
    conn.execute("INSERT INTO grid_events(grid_id, org_id, type, data_json) VALUES(?,?,?,?)",
                 (grid_id, org_id, type_, json.dumps(data, separators=(",", ":"), ensure_ascii=False)))


def _bump(grid_id: str) -> int:
    with _GLOCK:
        GEN[grid_id] += 1
        return GEN[grid_id]


def start_fill(conn, grid_id: str, org_id: str) -> None:
    """Fill every queued cell of the grid on a daemon thread (serialised per grid)."""
    _bump(grid_id)
    wconn, own = _worker_conn(conn)
    t = threading.Thread(target=_fill, args=(wconn, own, grid_id, org_id), name=f"grid-fill-{grid_id}", daemon=True)
    t.start()


def _fill(conn, own: bool, grid_id: str, org_id: str) -> None:
    lock = FILL_WORKERS_LOCK[grid_id]
    with lock:
        try:
            _fill_locked(conn, grid_id, org_id)
        except Exception as e:  # never kill the thread silently: park everything that is still running as failed
            try:
                conn.execute("UPDATE grid_cells SET state='failed', meta_json=?, updated_at=? WHERE grid_id=? AND state='running'",
                             (json.dumps({"error": f"{type(e).__name__}: {e}"[:300]}), _db.now(), grid_id))
            except Exception:
                pass
        finally:
            if own:
                try:
                    conn.close()
                except Exception:
                    pass


def _fill_locked(conn, grid_id: str, org_id: str) -> None:
    seen_gen = -1
    cols: list[dict] = []
    order: dict = {}
    rows_by: dict = {}
    inputs: dict = {}
    pages_cache: dict = {}
    vals: dict = {}
    conn.execute("UPDATE grid_cells SET state='queued' WHERE grid_id=? AND state='running'", (grid_id,))
    guard = 0
    while guard < 10000:
        guard += 1
        if GEN[grid_id] != seen_gen:
            seen_gen = GEN[grid_id]
            cols = _load_cols(conn, grid_id, org_id)
            try:
                order = {c["id"]: i for i, c in enumerate(_topo(cols))}
            except ApiError:
                order = {c["id"]: i for i, c in enumerate(cols)}
            rows_by = {r["id"]: r for r in _load_rows(conn, grid_id, org_id)}
            inputs = _load_inputs(conn, grid_id, org_id)
            vals = {(r["row_id"], r["col_id"]): r["value"] for r in
                    conn.execute("SELECT row_id, col_id, value FROM grid_cells WHERE grid_id=? AND state='done'", (grid_id,))}
        colmap = {c["id"]: c for c in cols}
        queued = [(r["row_id"], r["col_id"]) for r in conn.execute("SELECT row_id, col_id FROM grid_cells WHERE grid_id=? AND state='queued'", (grid_id,))]
        queued = [q for q in queued if q[0] in rows_by and q[1] in colmap]
        if not queued:
            break
        queued.sort(key=lambda q: (order.get(q[1], 1 << 20), rows_by[q[0]]["position"]))
        for row_id, col_id in queued:
            if GEN[grid_id] != seen_gen:
                break                                                        # definitions changed: reload, then continue
            col, row = colmap[col_id], rows_by[row_id]
            cur = conn.execute("UPDATE grid_cells SET state='running', updated_at=? WHERE grid_id=? AND row_id=? AND col_id=? AND state='queued'",
                               (_db.now(), grid_id, row_id, col_id)).rowcount
            if not cur:
                continue
            lookup = (lambda rid: (lambda cid: vals.get((rid, cid))))(row_id)
            _emit(conn, grid_id, org_id, "cell", {"row": row_id, "col": col_id, "state": "running"})
            state, value, cites, meta = "done", "", [], {}
            try:
                reason = _skip_reason(col, cols, lookup)
                if reason:
                    state, meta = "skipped", {"reason": reason}
                else:
                    if row["doc_id"] not in pages_cache:
                        pages_cache[row["doc_id"]] = load_pages(conn, org_id, [row["doc_id"]])[row["doc_id"]]
                    prompt = _render_prompt(col, cols, inputs, lookup)
                    res = answer_cell(pages_cache[row["doc_id"]], prompt, col["type"])
                    value = res["answer"]
                    meta = {"confidence": res["confidence"], "engine": "extractive", **res["meta"]}
                    if col["model"] not in ("extractive", "", None):
                        meta["note"] = f"model {col['model']} unavailable offline; answered extractively"
                    for c in res["citations"]:
                        tok = _mint(conn, org_id, row["doc_id"], c["page"], c["bbox_norm"], c["quote"])
                        cites.append({"token": tok, "doc_id": row["doc_id"], "page": c["page"], "bbox_norm": c["bbox_norm"], "quote": c["quote"]})
                    if not res["found"]:
                        meta["not_found"] = True
            except Exception as e:
                state, value, cites, meta = "failed", "", [], {"error": f"{type(e).__name__}: {e}"[:300]}
            n = conn.execute("UPDATE grid_cells SET state=?, value=?, citations_json=?, meta_json=?, updated_at=? "
                             "WHERE grid_id=? AND row_id=? AND col_id=? AND state='running'",
                             (state, value, json.dumps(cites, separators=(",", ":")), json.dumps(meta), _db.now(),
                              grid_id, row_id, col_id)).rowcount
            if not n:
                continue                                                      # superseded while running; it is queued again
            if state == "done":
                vals[(row_id, col_id)] = value
            else:
                vals.pop((row_id, col_id), None)
            _emit(conn, grid_id, org_id, "cell", {"row": row_id, "col": col_id, "state": state, "value": value, "citations": cites,
                                                   "reason": meta.get("reason"), "confidence": meta.get("confidence"),
                                                   "error": meta.get("error"),
                                                   "fmt": _fmt(col, lookup) if state == "done" and col["format_rules"] else None})
    _emit(conn, grid_id, org_id, "idle", {"pending": 0})


def _queue(ctx, grid_id: str, col_ids=None, row_ids=None) -> int:
    """(Re)queue cells of the given columns/rows (all when None); creates missing cells. Returns how many."""
    conn = ctx.conn
    cols = [c["id"] for c in _load_cols(conn, grid_id, ctx.org_id)]
    rows = [r["id"] for r in _load_rows(conn, grid_id, ctx.org_id)]
    cols = [c for c in cols if col_ids is None or c in col_ids]
    rows = [r for r in rows if row_ids is None or r in row_ids]
    now = _db.now()
    n = 0
    with _db.tx(conn):
        for c in cols:
            for r in rows:
                conn.execute("INSERT INTO grid_cells(grid_id,row_id,col_id,org_id,state,value,citations_json,meta_json,updated_at) "
                             "VALUES(?,?,?,?, 'queued','','[]','{}',?) ON CONFLICT(grid_id,row_id,col_id) DO UPDATE SET "
                             "state='queued', value='', citations_json='[]', meta_json='{}', updated_at=excluded.updated_at",
                             (grid_id, r, c, ctx.org_id, now))
                n += 1
        for c in cols:
            _emit(conn, grid_id, ctx.org_id, "column", {"col": c, "queued": len(rows)})
    if n:
        start_fill(conn, grid_id, ctx.org_id)
    return n


# --------------------------------------------------------------------------- grid CRUD
def _new_grid(ctx, deal_id: str, name: str, docs: list[dict], auto_rows: int = 0, source=None) -> str:
    gid = _db.new_id("grid")
    with _db.tx(ctx.conn):
        ctx.conn.execute("INSERT INTO grids(id, org_id, deal_id, name, created_at, auto_rows, source_grid_id) VALUES(?,?,?,?,?,?,?)",
                         (gid, ctx.org_id, deal_id, name, _db.now(), auto_rows, source))
        for i, d in enumerate(docs):
            ctx.conn.execute("INSERT INTO grid_rows(id, grid_id, org_id, doc_id, position, folder) VALUES(?,?,?,?,?,?)",
                             (_db.new_id("row"), gid, ctx.org_id, d["id"], i, d["folder"]))
    return gid


def _sync_rows(ctx, g) -> None:
    """The default grid follows the deal's indexed documents: new documents become rows and are filled."""
    docs = _doc_list(ctx, g["deal_id"])
    have = {r["doc_id"] for r in ctx.conn.execute("SELECT doc_id FROM grid_rows WHERE grid_id=?", (g["id"],))}
    new = [d for d in docs if d["id"] not in have]
    if not new:
        return
    pos = ctx.conn.execute("SELECT COALESCE(MAX(position)+1,0) FROM grid_rows WHERE grid_id=?", (g["id"],)).fetchone()[0]
    ids = []
    with _db.tx(ctx.conn):
        for i, d in enumerate(new):
            rid = _db.new_id("row")
            ids.append(rid)
            ctx.conn.execute("INSERT INTO grid_rows(id, grid_id, org_id, doc_id, position, folder) VALUES(?,?,?,?,?,?)",
                             (rid, g["id"], ctx.org_id, d["id"], pos + i, d["folder"]))
    if _load_cols(ctx.conn, g["id"], ctx.org_id):
        _queue(ctx, g["id"], None, set(ids))


def deal_grid(ctx):
    deal_id = ctx.params["deal_id"]
    _deal_ok(ctx, deal_id)
    g = ctx.conn.execute("SELECT * FROM grids WHERE org_id=? AND deal_id=? ORDER BY auto_rows DESC, created_at, id LIMIT 1",
                         (ctx.org_id, deal_id)).fetchone()
    if g is None:
        if ctx.role == "viewer":
            return {"grid": None, "columns": [], "rows": [], "cells": [], "inputs": {}, "pending": 0, "models": MODELS,
                    "types": list(TYPES[:5]), "hint": "Ask a member to open the Matrix once to create it."}
        gid = _new_grid(ctx, deal_id, "Matrix", _doc_list(ctx, deal_id), auto_rows=1)
        g = _grid(ctx, gid)
    elif g["auto_rows"] and ctx.role != "viewer":
        _sync_rows(ctx, g)
    return _grid_payload(ctx, g)


def deal_grid_documents(ctx):
    _deal_ok(ctx, ctx.params["deal_id"])
    docs = _doc_list(ctx, ctx.params["deal_id"])
    folders = defaultdict(int)
    for d in docs:
        folders[d["folder"] or ""] += 1
    return {"documents": docs, "folders": [{"name": k, "count": v} for k, v in sorted(folders.items())]}


def list_grids(ctx):
    _deal_ok(ctx, ctx.params["deal_id"])
    rows = ctx.conn.execute("SELECT id, name, created_at, auto_rows FROM grids WHERE org_id=? AND deal_id=? ORDER BY created_at, id",
                            (ctx.org_id, ctx.params["deal_id"])).fetchall()
    return {"items": [dict(r) for r in rows]}


_SPLIT = re.compile(r"(?:\r?\n+|;|\?\s+(?=[A-Z])|\s+\band\b\s+(?=(?:what|which|who|when|where|how|is|are|does|do|list|state)\b))", re.I)


def split_question(text: str) -> list[dict]:
    """A free-text question to one column per sub-question (wizard step 2): newlines, bullets, ';' and '?' boundaries."""
    parts = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", p).strip(" \t?.,") for p in _SPLIT.split(text or "")]
    parts = [p for p in parts if len(p) >= 3]
    out = []
    for p in parts:
        terms = _matrix.key_terms(p)[:3]
        name = (" ".join(terms) or p[:24]).title()
        typ = "text"
        low = p.lower()
        if re.match(r"^(is|are|does|do|has|have|can)\b", low):
            typ = "yes-no"
        elif re.search(r"\b(how much|how many|amount|total|revenue|ebitda|value|price|number of)\b", low):
            typ = "number"
        elif re.search(r"\b(when|date|expiry|expires|maturity)\b", low):
            typ = "date"
        elif re.search(r"\b(list|which|all)\b", low):
            typ = "list"
        out.append({"name": name, "prompt": p + ("?" if not p.endswith("?") else ""), "type": typ})
    seen = set()
    for c in out:
        base, n = c["name"], 2
        while c["name"].lower() in seen:
            c["name"] = f"{base} {n}"
            n += 1
        seen.add(c["name"].lower())
    return out[:MAX_COLUMNS]


def split_route(ctx):
    _deal_ok(ctx, ctx.params["deal_id"])
    q = str(_body(ctx).get("question") or "").strip()
    if not q:
        raise _bad("Write a question first.", "Describe what to extract, e.g. 'What is the change of control clause?'")
    return {"columns": split_question(q)}


def _validated_column(body: dict, existing: list[dict], self_id=None) -> dict:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise _bad("A column needs a prompt.", "Write what to extract, in plain language.")
    typ = str(body.get("type") or "text")
    if typ not in TYPES:
        raise _bad(f"Unknown column type {typ!r}.", f"Use one of: {', '.join(TYPES[:5])}.")
    name = str(body.get("name") or "").strip() or (" ".join(_matrix.key_terms(prompt)[:3]).title() or "Column")
    clash = {c["name"].lower() for c in existing if c["id"] != self_id}
    base, n = name, 2
    while name.lower() in clash:
        name = f"{base} {n}"
        n += 1
    cond = body.get("run_condition")
    if cond is not None and not (isinstance(cond, dict) and cond.get("col") and cond.get("op") in OPS):
        raise _bad("The run condition needs a column and an operator.", f"Use {{col, op, value}} with op in {', '.join(OPS)}.")
    rules = body.get("format_rules") or []
    if not isinstance(rules, list) or any(not isinstance(r, dict) or r.get("tone") not in TONES for r in rules):
        raise _bad("A formatting rule needs a tone and a condition.", f"tone must be one of {', '.join(TONES)}; condition is an AND/OR tree.")
    model = str(body.get("model") or "extractive")
    return {"name": name, "prompt": prompt, "type": typ, "run_condition": cond, "format_rules": rules, "model": model}


def _insert_column(ctx, gid: str, spec: dict, cols: list[dict]) -> dict:
    cid = _db.new_id("col")
    pos = (max((c["position"] for c in cols), default=-1)) + 1
    deps = _deps(cols + [{"id": cid, "name": spec["name"]}], spec["prompt"], spec["run_condition"], cid)
    new = {"id": cid, "position": pos, "depends_on": deps, **spec}
    _topo(cols + [new])                                                      # reject cycles before writing
    with _db.tx(ctx.conn):
        ctx.conn.execute("INSERT INTO grid_columns(id, grid_id, org_id, position, name, prompt, type, depends_on_json, run_condition_json, "
                         "model, format_rules_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (cid, gid, ctx.org_id, pos, spec["name"], spec["prompt"], spec["type"], json.dumps(deps),
                          json.dumps(spec["run_condition"]) if spec["run_condition"] else None, spec["model"], json.dumps(spec["format_rules"])))
        for name in deps["inputs"]:
            ctx.conn.execute("INSERT OR IGNORE INTO grid_inputs(grid_id, org_id, name, value) VALUES(?,?,?,'')", (gid, ctx.org_id, name))
    return new


def create_grid(ctx):
    ctx.require("member")
    deal_id = ctx.params["deal_id"]
    _deal_ok(ctx, deal_id)
    b = _body(ctx)
    docs = _doc_list(ctx, deal_id)
    ids, folders = set(b.get("doc_ids") or []), set(b.get("folders") or [])
    if ids or folders:
        docs = [d for d in docs if d["id"] in ids or d["folder"] in folders]
    if not docs:
        raise _bad("Pick at least one indexed document.", "Upload documents and wait for indexing, or choose a folder that has some.")
    cols_in = b.get("columns")
    if not cols_in and b.get("question"):
        cols_in = split_question(str(b["question"]))
    if not cols_in:
        raise _bad("Add at least one question.", "Write a question; it is split into one column per sub-question.")
    if len(cols_in) > MAX_COLUMNS:
        raise _bad(f"At most {MAX_COLUMNS} columns per Matrix.", "Split the work across two Matrices.")
    name = str(b.get("name") or "").strip() or f"Matrix {time.strftime('%Y-%m-%d')}"
    gid = _new_grid(ctx, deal_id, name, docs)
    cols: list[dict] = []
    for ci in cols_in:
        spec = _validated_column(ci, cols)
        cols.append(_insert_column(ctx, gid, spec, cols))
    _queue(ctx, gid)
    ctx.audit("grid.create", gid, {"deal_id": deal_id, "documents": len(docs), "columns": len(cols)})
    return 201, _grid_payload(ctx, _grid(ctx, gid))


def get_grid(ctx):
    return _grid_payload(ctx, _grid(ctx, ctx.params["grid_id"]))


def patch_grid(ctx):
    ctx.require("member")
    g = _grid(ctx, ctx.params["grid_id"])
    b = _body(ctx)
    if b.get("name"):
        ctx.conn.execute("UPDATE grids SET name=? WHERE id=?", (str(b["name"]).strip()[:120], g["id"]))
    order = b.get("column_order")
    if isinstance(order, list):
        cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
        have = {c["id"] for c in cols}
        seq = [c for c in order if c in have] + [c["id"] for c in cols if c["id"] not in order]
        with _db.tx(ctx.conn):
            for i, cid in enumerate(seq):
                ctx.conn.execute("UPDATE grid_columns SET position=? WHERE id=? AND grid_id=?", (i, cid, g["id"]))
    ctx.audit("grid.update", g["id"], {k: b[k] for k in b if k in ("name", "column_order")})
    return _grid_payload(ctx, _grid(ctx, g["id"]))


def _estimate_for(ctx, g, prompt: str, typ: str, model: str) -> dict:
    n_rows = ctx.conn.execute("SELECT COUNT(*) FROM grid_rows WHERE grid_id=?", (g["id"],)).fetchone()[0]
    chars = ctx.conn.execute("SELECT COALESCE(SUM(LENGTH(p.text)),0) FROM document_pages p JOIN grid_rows r ON r.doc_id=p.doc_id AND "
                             "r.org_id=p.org_id WHERE r.grid_id=?", (g["id"],)).fetchone()[0]
    per_doc_tokens = min(12000, max(400, int(chars / max(n_rows, 1) / 4)))
    tin, tout = per_doc_tokens * n_rows, 160 * n_rows
    cost = 0.0
    if model not in ("extractive", ""):
        try:
            from src.harness.ledger import cost_usd
            cost = float(cost_usd(model, tin, tout))
        except Exception:
            cost = round(tin * 3e-6 + tout * 15e-6, 4)
    seconds = round(0.05 * n_rows + 0.3, 1) if model in ("extractive", "") else round(1.2 * n_rows / 4 + 1, 1)
    return {"cells": n_rows, "est_cost_usd": round(cost, 4), "est_seconds": seconds, "est_input_tokens": tin if model != "extractive" else 0,
            "engine": "extractive" if model in ("extractive", "") else model, "prompt_chars": len(prompt)}


def estimate(ctx):
    g = _grid(ctx, ctx.params["grid_id"])
    return _estimate_for(ctx, g, ctx.query.get("prompt", ""), ctx.query.get("type", "text"), ctx.query.get("model", "extractive"))


def add_column(ctx):
    ctx.require("member")
    g = _grid(ctx, ctx.params["grid_id"])
    cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
    if len(cols) >= MAX_COLUMNS:
        raise _bad(f"At most {MAX_COLUMNS} columns per Matrix.", "Remove a column or start a second Matrix.")
    spec = _validated_column(_body(ctx), cols)
    col = _insert_column(ctx, g["id"], spec, cols)
    n = _queue(ctx, g["id"], {col["id"]})
    ctx.audit("grid.column.add", g["id"], {"column": col["id"], "name": col["name"]})
    return 201, {"column": col, "queued": n, "estimate": _estimate_for(ctx, g, spec["prompt"], spec["type"], spec["model"])}


def patch_column(ctx):
    ctx.require("member")
    g = _grid(ctx, ctx.params["grid_id"])
    cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
    col = next((c for c in cols if c["id"] == ctx.params["col_id"]), None)
    if col is None:
        raise _nf()
    b = _body(ctx)
    merged = {"name": b.get("name", col["name"]), "prompt": b.get("prompt", col["prompt"]), "type": b.get("type", col["type"]),
              "model": b.get("model", col["model"]),
              "run_condition": b["run_condition"] if "run_condition" in b else col["run_condition"],
              "format_rules": b["format_rules"] if "format_rules" in b else col["format_rules"]}
    spec = _validated_column(merged, cols, col["id"])
    old_name = col["name"]
    others = [c for c in cols if c["id"] != col["id"]]
    renamed = spec["name"] != old_name
    # references in other prompts follow a rename
    updates = []
    for c in others:
        p = c["prompt"]
        if renamed:
            p = REF_RE.sub(lambda m: "{{" + spec["name"] + "}}" if _norm(m.group(1)) == _norm(old_name) else m.group(0), p)
        updates.append({**c, "prompt": p})
    all_cols = updates + [{**col, **spec}]
    for c in all_cols:
        c["depends_on"] = _deps(all_cols, c["prompt"], c["run_condition"], c["id"])
    _topo(all_cols)
    changed = spec["prompt"] != col["prompt"] or spec["type"] != col["type"] or spec["model"] != col["model"] or \
        spec["run_condition"] != col["run_condition"] or renamed
    with _db.tx(ctx.conn):
        for c in all_cols:
            ctx.conn.execute("UPDATE grid_columns SET name=?, prompt=?, type=?, depends_on_json=?, run_condition_json=?, model=?, "
                             "format_rules_json=? WHERE id=? AND grid_id=?",
                             (c["name"], c["prompt"], c["type"], json.dumps(c["depends_on"]),
                              json.dumps(c["run_condition"]) if c["run_condition"] else None, c["model"], json.dumps(c["format_rules"]),
                              c["id"], g["id"]))
        if "position" in b and isinstance(b["position"], int):
            seq = [c["id"] for c in sorted(cols, key=lambda c: c["position"]) if c["id"] != col["id"]]
            seq.insert(max(0, min(b["position"], len(seq))), col["id"])
            for i, cid in enumerate(seq):
                ctx.conn.execute("UPDATE grid_columns SET position=? WHERE id=? AND grid_id=?", (i, cid, g["id"]))
        for name in all_cols[-1]["depends_on"]["inputs"]:
            ctx.conn.execute("INSERT OR IGNORE INTO grid_inputs(grid_id, org_id, name, value) VALUES(?,?,?,'')", (g["id"], ctx.org_id, name))
    queued = 0
    if changed:
        affected = _downstream(all_cols, {col["id"]})
        _bump(g["id"])
        queued = _queue(ctx, g["id"], affected)
    ctx.audit("grid.column.update", g["id"], {"column": col["id"], "rerun": bool(changed)})
    fresh = next(c for c in _load_cols(ctx.conn, g["id"], ctx.org_id) if c["id"] == col["id"])
    return {"column": fresh, "queued": queued}


def delete_column(ctx):
    ctx.require("member")
    g = _grid(ctx, ctx.params["grid_id"])
    cid = ctx.params["col_id"]
    cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
    if not any(c["id"] == cid for c in cols):
        raise _nf()
    dependents = [c["name"] for c in cols if cid in c["depends_on"]["cols"]]
    with _db.tx(ctx.conn):
        ctx.conn.execute("DELETE FROM grid_cells WHERE grid_id=? AND col_id=?", (g["id"], cid))
        ctx.conn.execute("DELETE FROM grid_columns WHERE id=? AND grid_id=?", (cid, g["id"]))
        rest = [c for c in cols if c["id"] != cid]
        for i, c in enumerate(sorted(rest, key=lambda c: c["position"])):
            ctx.conn.execute("UPDATE grid_columns SET position=?, depends_on_json=? WHERE id=?",
                             (i, json.dumps(_deps(rest, c["prompt"], c["run_condition"], c["id"])), c["id"]))
        _emit(ctx.conn, g["id"], ctx.org_id, "column_removed", {"col": cid})
    ctx.audit("grid.column.delete", g["id"], {"column": cid})
    return {"deleted": cid, "dependents": dependents,
            "hint": "These columns referenced it and now see an empty value." if dependents else None}


def run_grid(ctx):
    ctx.require("member")
    g = _grid(ctx, ctx.params["grid_id"])
    b = _body(ctx)
    cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
    col_ids = set(b["col_ids"]) if b.get("col_ids") else None
    row_ids = set(b["row_ids"]) if b.get("row_ids") else None
    if col_ids is not None:
        col_ids = _downstream(cols, col_ids & {c["id"] for c in cols})
    n = _queue(ctx, g["id"], col_ids, row_ids)
    ctx.audit("grid.run", g["id"], {"cells": n})
    return 202, {"queued": n}


def put_input(ctx):
    ctx.require("member")
    g = _grid(ctx, ctx.params["grid_id"])
    name = ctx.params["name"]
    b = _body(ctx)
    if "value" not in b:
        raise _bad("Send {\"value\": ...}.", "An input is a named value the column prompts reference as {{name}}.")
    value = "" if b["value"] is None else str(b["value"])
    ctx.conn.execute("INSERT INTO grid_inputs(grid_id, org_id, name, value) VALUES(?,?,?,?) ON CONFLICT(grid_id,name) DO UPDATE SET "
                     "value=excluded.value", (g["id"], ctx.org_id, name, value))
    cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
    direct = {c["id"] for c in cols if name in c["depends_on"]["inputs"]}
    affected = _downstream(cols, direct) if direct else set()
    _bump(g["id"])
    n = _queue(ctx, g["id"], affected) if affected else 0
    ctx.audit("grid.input", g["id"], {"name": name, "rerun": len(affected)})
    return {"name": name, "value": value, "rerun_columns": sorted(affected), "queued": n}


def workflow(ctx):
    g = _grid(ctx, ctx.params["grid_id"])
    cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
    inputs = _load_inputs(ctx.conn, g["id"], ctx.org_id)
    nodes = [{"id": c["id"], "kind": "column", "label": c["name"], "type": c["type"]} for c in cols]
    nodes += [{"id": f"input:{n}", "kind": "input", "label": n, "value": v} for n, v in inputs.items()]
    edges = []
    for c in cols:
        for d in c["depends_on"]["cols"]:
            cond = isinstance(c["run_condition"], dict) and _col_key(cols, str(c["run_condition"].get("col"))) is not None \
                and _col_key(cols, str(c["run_condition"]["col"]))["id"] == d
            ref = any((_col_key(cols, r) or {}).get("id") == d for r in _refs(c["prompt"]))
            edges.append({"from": d, "to": c["id"], "kind": "reference" if ref else "condition" if cond else "reference"})
        for i in c["depends_on"]["inputs"]:
            edges.append({"from": f"input:{i}", "to": c["id"], "kind": "input"})
    try:
        level: dict = {}
        for c in _topo(cols):
            level[c["id"]] = 1 + max([level.get(d, 0) for d in c["depends_on"]["cols"]] + [0])
        for n in nodes:
            n["level"] = 0 if n["kind"] == "input" else level.get(n["id"], 1)
    except ApiError:
        pass
    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------- SSE
def events(ctx):
    g = _grid(ctx, ctx.params["grid_id"])
    last = ctx.headers.get("Last-Event-ID") or ctx.headers.get("last-event-id") or ctx.query.get("after") or "0"
    try:
        after = int(last)
    except ValueError:
        after = 0
    conn, org_id, gid = ctx.conn, ctx.org_id, g["id"]

    def gen():
        nonlocal after
        yield "hello", {"grid": gid, "seq": after}
        deadline = time.time() + 600
        quiet = 0
        while time.time() < deadline:
            got = False
            for r in conn.execute("SELECT seq, type, data_json FROM grid_events WHERE grid_id=? AND org_id=? AND seq>? ORDER BY seq LIMIT 500",
                                  (gid, org_id, after)).fetchall():
                after = r["seq"]
                got = True
                data = _json(r["data_json"], {})
                data["seq"] = r["seq"]
                yield r["type"], data
            pending = conn.execute("SELECT COUNT(*) FROM grid_cells WHERE grid_id=? AND state IN ('queued','running')", (gid,)).fetchone()[0]
            if not pending and not got:
                quiet += 1
                if quiet >= 2:
                    yield "idle", {"pending": 0, "seq": after}
                    return
            else:
                quiet = 0
            time.sleep(0.12 if pending else 0.3)
    return SSE(gen(), last_event_id=last)


# --------------------------------------------------------------------------- transfer, export, chat
def transfer(ctx):
    ctx.require("member")
    g = _grid(ctx, ctx.params["grid_id"])
    b = _body(ctx)
    row_ids = list(dict.fromkeys(b.get("row_ids") or []))
    rows = [r for r in _load_rows(ctx.conn, g["id"], ctx.org_id) if r["id"] in set(row_ids)]
    if not rows:
        raise _bad("Select at least one row to transfer.", "Filter the Matrix, then send the rows you kept.")
    name = str(b.get("name") or "").strip() or f"{g['name']} (transfer)"
    ng = _db.new_id("grid")
    cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
    idmap = {c["id"]: _db.new_id("col") for c in cols}
    rmap = {r["id"]: _db.new_id("row") for r in rows}
    now = _db.now()
    with _db.tx(ctx.conn):
        ctx.conn.execute("INSERT INTO grids(id, org_id, deal_id, name, created_at, auto_rows, source_grid_id) VALUES(?,?,?,?,?,0,?)",
                         (ng, ctx.org_id, g["deal_id"], name, now, g["id"]))
        for r in rows:
            ctx.conn.execute("INSERT INTO grid_rows(id, grid_id, org_id, doc_id, position, folder) VALUES(?,?,?,?,?,?)",
                             (rmap[r["id"]], ng, ctx.org_id, r["doc_id"], r["position"], r["folder"]))
        for c in cols:
            deps = {"cols": [idmap[d] for d in c["depends_on"]["cols"] if d in idmap], "inputs": c["depends_on"]["inputs"]}
            cond = c["run_condition"]
            if isinstance(cond, dict) and cond.get("col") in idmap:
                cond = {**cond, "col": idmap[cond["col"]]}
            ctx.conn.execute("INSERT INTO grid_columns(id, grid_id, org_id, position, name, prompt, type, depends_on_json, run_condition_json, "
                             "model, format_rules_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             (idmap[c["id"]], ng, ctx.org_id, c["position"], c["name"], c["prompt"], c["type"], json.dumps(deps),
                              json.dumps(cond) if cond else None, c["model"], json.dumps(c["format_rules"])))
        for r in ctx.conn.execute("SELECT * FROM grid_cells WHERE grid_id=?", (g["id"],)).fetchall():
            if r["row_id"] in rmap and r["col_id"] in idmap:
                ctx.conn.execute("INSERT INTO grid_cells(grid_id,row_id,col_id,org_id,state,value,citations_json,meta_json,updated_at) "
                                 "VALUES(?,?,?,?,?,?,?,?,?)", (ng, rmap[r["row_id"]], idmap[r["col_id"]], ctx.org_id, r["state"],
                                                               r["value"], r["citations_json"], r["meta_json"], r["updated_at"]))
        for n, v in _load_inputs(ctx.conn, g["id"], ctx.org_id).items():
            ctx.conn.execute("INSERT INTO grid_inputs(grid_id, org_id, name, value) VALUES(?,?,?,?)", (ng, ctx.org_id, n, v))
    pend = ctx.conn.execute("SELECT COUNT(*) FROM grid_cells WHERE grid_id=? AND state IN ('queued','running')", (ng,)).fetchone()[0]
    if pend:
        start_fill(ctx.conn, ng, ctx.org_id)
    ctx.audit("grid.transfer", ng, {"from": g["id"], "rows": len(rows)})
    return 201, _grid_payload(ctx, _grid(ctx, ng))


def export_xlsx(ctx):
    from om import xlsx
    g = _grid(ctx, ctx.params["grid_id"])
    data = _grid_payload(ctx, g)
    logo = ctx.query.get("logo") in ("1", "true", "yes")
    wb = xlsx.Workbook()
    sh = wb.sheet("Matrix")
    top = 1
    if logo:
        sh.set("A1", "ACRETIA", kind="title")
        sh.set("A2", f"{g['name']}  |  exported {time.strftime('%Y-%m-%d')}", kind="note")
        top = 4
    sh.set((top, 1), "Document", kind="header")
    sh.set((top, 2), "Folder", kind="header")
    cols = data["columns"]
    for j, c in enumerate(cols):
        sh.set((top, 3 + j), c["name"], kind="header", wrap=True)
    cell_by = {(c["row"], c["col"]): c for c in data["cells"]}
    src = wb.sheet("Sources")
    for j, h in enumerate(("Document", "Column", "Page", "Quote", "Citation token")):
        src.set((1, 1 + j), h, kind="header")
    srow = 2
    for i, r in enumerate(data["rows"]):
        rr = top + 1 + i
        sh.set((rr, 1), r["name"], kind="text")
        sh.set((rr, 2), r["folder"], kind="text")
        for j, c in enumerate(cols):
            cell = cell_by.get((r["id"], c["id"]))
            if not cell or cell["state"] in ("queued", "running"):
                sh.set((rr, 3 + j), "", kind="text")
                continue
            if cell["state"] == "skipped":
                sh.set((rr, 3 + j), "Skipped", kind="note", comment=cell.get("reason") or "")
                continue
            if cell["state"] == "failed":
                sh.set((rr, 3 + j), "Failed", kind="text", comment=cell.get("error") or "")
                continue
            val = cell["value"]
            note = "\n".join(f"p.{k['page']}: \"{k['quote']}\"" for k in cell["citations"]) or None
            num = _num(val) if c["type"] in ("number", "currency", "percent") else None
            sh.set((rr, 3 + j), num if num is not None else val, kind="text", wrap=True, comment=note)
            for k in cell["citations"]:
                for jj, v in enumerate((r["name"], c["name"], k["page"], k["quote"], k["token"])):
                    src.set((srow, 1 + jj), v, kind="text", wrap=jj == 3)
                srow += 1
    sh.width(1, 34)
    sh.width(2, 18)
    for j in range(len(cols)):
        sh.width(3 + j, 42)
    sh.freeze = (top, 2)
    src.width(1, 30)
    src.width(2, 22)
    src.width(4, 80)
    src.width(5, 28)
    body = wb.to_bytes()
    fn = re.sub(r"[^\w.\- ]", "_", g["name"]) or "matrix"
    return Response(200, body, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    {"Content-Disposition": f'attachment; filename="{fn}.xlsx"'})


def chat(ctx):
    g = _grid(ctx, ctx.params["grid_id"])
    q = str(_body(ctx).get("question") or "").strip()
    if not q:
        raise _bad("Ask a question first.", "For example: 'Which agreements have a change of control clause?'")
    t0 = time.time()
    rows = _load_rows(ctx.conn, g["id"], ctx.org_id)
    cols = _load_cols(ctx.conn, g["id"], ctx.org_id)
    pages = load_pages(ctx.conn, ctx.org_id, [r["doc_id"] for r in rows])
    cells = {(c["row_id"], c["col_id"]): c for c in ctx.conn.execute("SELECT * FROM grid_cells WHERE grid_id=? AND state='done'", (g["id"],))}
    terms = _matrix.key_terms(q)
    col_hit = [c for c in cols if terms and _matrix._stem_hits(c["name"] + " " + c["prompt"], terms) >= max(1, len(terms) // 2)]
    out = []
    for r in rows:
        res = answer_cell(pages.get(r["doc_id"], []), q, "text")
        if not res["found"]:
            continue
        score = _candidates(pages.get(r["doc_id"], []), q, "text")[0][0]
        toks = []
        for c in res["citations"]:
            tok = _mint(ctx.conn, ctx.org_id, r["doc_id"], c["page"], c["bbox_norm"], c["quote"])
            toks.append({"token": tok, "doc_id": r["doc_id"], "page": c["page"], "bbox_norm": c["bbox_norm"], "quote": c["quote"]})
        extra = []
        for c in col_hit:
            cell = cells.get((r["id"], c["id"]))
            if cell and cell["value"] and cell["value"] != NOT_FOUND:
                extra.append({"column": c["name"], "value": cell["value"]})
        out.append({"row_id": r["id"], "name": r["name"], "folder": r["folder"], "score": round(score, 2), "excerpt": res["citations"][0]["quote"],
                    "citations": toks, "columns": extra})
    out.sort(key=lambda x: -x["score"])
    top = out[:12]
    if top:
        lead = f"{len(out)} of {len(rows)} documents address this."
        lines = [f"{i + 1}. {t['name']} (p.{t['citations'][0]['page']}): {t['excerpt']}" for i, t in enumerate(top[:6])]
        answer = lead + "\n" + "\n".join(lines)
    else:
        answer = f"None of the {len(rows)} documents in this Matrix addresses that."
    return {"answer": answer, "rows": top, "matched": len(out), "total": len(rows), "engine": "extractive",
            "seconds": round(time.time() - t0, 3)}


# --------------------------------------------------------------------------- risks and tables
def risks(ctx):
    deal_id = ctx.params["deal_id"]
    _deal_ok(ctx, deal_id)
    from om import vdr_risk
    docs = _doc_list(ctx, deal_id)
    pages = load_pages(ctx.conn, ctx.org_id, [d["id"] for d in docs])
    scan_docs, lines_by = [], {}
    for d in docs:
        items = [(p["page"], "\n".join(l["text"] for l in p["lines"]) if p["lines"] else p["text"]) for p in pages[d["id"]]]
        scan_docs.append({"doc_id": d["id"], "name": d["full_name"], "pages": [t for _p, t in items], "page_items": items, "pdf": None})
        lines_by[d["id"]] = {p["page"]: p["lines"] for p in pages[d["id"]]}
    rep = vdr_risk.scan_documents(scan_docs, locate=lambda *a: None)

    def locate(doc_id, page, quote):
        lines = (lines_by.get(doc_id) or {}).get(page) or []
        qn = _norm(quote)
        if not qn:
            return None
        hit = [l for l in lines if l["bbox"] and _norm(l["text"]) and _norm(l["text"]) in qn]
        if not hit:
            hit = [l for l in lines if l["bbox"] and qn in _norm(l["text"])]
        return _union([l["bbox"] for l in hit])

    out = []
    for f in rep["findings"]:
        f = dict(f)
        bb = locate(f.get("doc_id"), f.get("page"), f.get("quote") or "") if f.get("doc_id") else None
        f["bbox_norm"] = bb
        f["citation_token"] = _mint(ctx.conn, ctx.org_id, f["doc_id"], f.get("page"), bb, f.get("quote") or "") if f.get("doc_id") and f.get("quote") else None
        for rel in f.get("related") or []:
            rb = locate(rel.get("doc_id"), rel.get("page"), rel.get("quote") or "") if rel.get("doc_id") else None
            rel["bbox_norm"] = rb
            rel["citation_token"] = _mint(ctx.conn, ctx.org_id, rel["doc_id"], rel.get("page"), rb, rel.get("quote") or "") if rel.get("doc_id") and rel.get("quote") else None
        out.append(f)
    return {"summary": rep["summary"], "findings": out, "coverage": rep["coverage"]}


def _doc_tables(ctx, doc_id: str) -> list[dict]:
    _doc_row(ctx, doc_id)
    out = []
    for r in ctx.conn.execute("SELECT page, tables_json FROM document_pages WHERE org_id=? AND doc_id=? ORDER BY page", (ctx.org_id, doc_id)):
        data = _json(r["tables_json"], [])
        if isinstance(data, dict):
            data = data.get("tables") or []
        for t in data if isinstance(data, list) else []:
            rows = t.get("rows") if isinstance(t, dict) else t
            if not isinstance(rows, list) or not rows:
                continue
            rows = [[("" if c is None else str(c)) for c in (row if isinstance(row, list) else [row])] for row in rows]
            out.append({"n": len(out) + 1, "page": r["page"], "rows": rows,
                        "bbox_norm": t.get("bbox_norm") if isinstance(t, dict) else None})
    return out


def doc_tables(ctx):
    ts = _doc_tables(ctx, ctx.params["doc_id"])
    return {"tables": [{"n": t["n"], "page": t["page"], "n_rows": len(t["rows"]), "n_cols": max(len(r) for r in t["rows"]),
                        "preview": t["rows"][:4], "csv_url": f"/api/v1/documents/{ctx.params['doc_id']}/tables/{t['n']}.csv"} for t in ts]}


def doc_table_csv(ctx):
    ts = _doc_tables(ctx, ctx.params["doc_id"])
    raw = ctx.params["n"]
    n = int(raw[:-4] if raw.endswith(".csv") else raw) if re.fullmatch(r"\d+(\.csv)?", raw) else 0
    t = next((t for t in ts if t["n"] == n), None)
    if t is None:
        raise _nf()
    buf = io.StringIO()
    csv.writer(buf).writerows(t["rows"])
    return Response(200, buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8",
                    {"Content-Disposition": f'attachment; filename="table-{n}-p{t["page"]}.csv"'})


# --------------------------------------------------------------------------- routes
ROUTES = [
    Route("GET", "/api/v1/deals/{deal_id}/grid", deal_grid, role="viewer"),
    Route("GET", "/api/v1/deals/{deal_id}/grid/documents", deal_grid_documents, role="viewer"),
    Route("GET", "/api/v1/deals/{deal_id}/grids", list_grids, role="viewer"),
    Route("POST", "/api/v1/deals/{deal_id}/grids", create_grid, role="member"),
    Route("POST", "/api/v1/deals/{deal_id}/grids/split", split_route, role="member"),
    Route("GET", "/api/v1/deals/{deal_id}/risks", risks, role="viewer"),
    Route("GET", "/api/v1/grids/{grid_id}", get_grid, role="viewer"),
    Route("PATCH", "/api/v1/grids/{grid_id}", patch_grid, role="member"),
    Route("POST", "/api/v1/grids/{grid_id}/columns", add_column, role="member"),
    Route("PATCH", "/api/v1/grids/{grid_id}/columns/{col_id}", patch_column, role="member"),
    Route("DELETE", "/api/v1/grids/{grid_id}/columns/{col_id}", delete_column, role="member"),
    Route("POST", "/api/v1/grids/{grid_id}/run", run_grid, role="member"),
    Route("GET", "/api/v1/grids/{grid_id}/estimate", estimate, role="viewer"),
    Route("PUT", "/api/v1/grids/{grid_id}/inputs/{name}", put_input, role="member"),
    Route("GET", "/api/v1/grids/{grid_id}/workflow", workflow, role="viewer"),
    Route("GET", "/api/v1/grids/{grid_id}/events", events, role="viewer"),
    Route("POST", "/api/v1/grids/{grid_id}/transfer", transfer, role="member"),
    Route("GET", "/api/v1/grids/{grid_id}/export.xlsx", export_xlsx, role="viewer"),
    Route("POST", "/api/v1/grids/{grid_id}/chat", chat, role="viewer"),
    Route("GET", "/api/v1/documents/{doc_id}/tables", doc_tables, role="viewer"),
    Route("GET", "/api/v1/documents/{doc_id}/tables/{n}", doc_table_csv, role="viewer"),
]
