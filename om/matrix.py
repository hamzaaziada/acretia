"""Matrix: documents × questions, every cell answered by Claude with verified citations (Hebbia-style).

Flow per document (one row):
  1. Retrieval: for each column, full-text search inside that document for the question's key terms;
     union the top passages (small documents are sent whole).
  2. One Claude call answers every column of the row. The document passages go first with
     cache_control, so adding a column later re-uses the cached document.
  3. Structured output (JSON schema) returns, per column: answer, normalized value, cited passage ids
     and the exact quote supporting it.
  4. Grounding check: each quote must appear in the cited passage, or the citation is marked
     unverified and the cell is flagged for review. Nothing un-cited is presented as fact.

Requires `pip install anthropic` and ANTHROPIC_API_KEY (or an `ant auth login` profile).
"""
from __future__ import annotations

import csv
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

MAX_DOC_CHARS = 60_000      # send small documents whole
MAX_CONTEXT_CHARS = 48_000  # budget for retrieved passages per row
PER_COLUMN_PASSAGES = 6
COLUMN_TYPES = ("text", "number", "percent", "currency", "date", "boolean", "list")
STOP = set("""a an and are as at be by can could did do does for from has have how in is it its of on or
that the their there these this to was were what when where which who will with would company companies
document filing please describe list give provide state any all say says said about tell mention mentioned
disclose disclosed discuss discussed most more main key major significant period year fiscal recent latest
our we they them his her than into over under per each other such also only""".split())

SYSTEM = """You are a meticulous financial analyst filling in a research matrix.
For each question you are given passages from ONE document, each labelled [P<id>].
Rules:
- Answer only from the passages. If they do not contain the answer, set not_found=true and answer "Not found in document".
- Every factual answer must cite at least one passage id and copy a short exact quote (verbatim, 5-40 words) from that passage that supports it.
- Keep answers concise (one to three sentences, or a short list). Use the document's own units and say them (e.g. "$ millions").
- value: the single normalized value when the column type is number/percent/currency/date/boolean, else null.
  number/currency: a plain number in the units you state in `unit`; percent: e.g. 12.5 for 12.5%; date: YYYY-MM-DD;
  boolean: true/false.
- confidence: high when the passage states it directly, medium when it needs light inference, low otherwise."""


@dataclass
class Column:
    name: str
    question: str
    type: str = "text"
    instructions: str = ""


@dataclass
class Cell:
    doc_id: int
    column: str
    answer: str = ""
    value: object = None
    unit: str | None = None
    confidence: str | None = None
    not_found: bool = False
    citations: list = field(default_factory=list)   # [{passage_id, quote, verified, section}]
    status: str = "pending"                          # ok | unverified | not_found | refused | error
    error: str | None = None


# --------------------------------------------------------------------------- schema / prompt
def output_schema(columns: list[Column]) -> dict:
    nullable = lambda t: {"anyOf": [{"type": t}, {"type": "null"}]}  # noqa: E731
    return {
        "type": "object",
        "properties": {
            "answers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "column": {"type": "string", "enum": [c.name for c in columns]},
                        "answer": {"type": "string"},
                        "value": {"anyOf": [{"type": "number"}, {"type": "string"}, {"type": "boolean"}, {"type": "null"}]},
                        "unit": nullable("string"),
                        "not_found": {"type": "boolean"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "citations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"passage_id": {"type": "integer"}, "quote": {"type": "string"}},
                                "required": ["passage_id", "quote"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["column", "answer", "value", "unit", "not_found", "confidence", "citations"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["answers"],
        "additionalProperties": False,
    }


def build_prompt(doc: dict, passages: list[dict], columns: list[Column]):
    """Provider-neutral prompt: (system, parts, schema). The document is the first, cacheable part so
    later columns on the same row reuse it (explicit caching on Claude, automatic prefix caching on
    DeepSeek/OpenAI)."""
    from .llm import Part
    header = (f"Document: {doc['company']} ({doc.get('ticker') or 'n/a'}) — {doc['form']} filed {doc['filed']}\n"
              f"Title: {doc.get('title') or ''}\nSource: {doc['url']}\n\nPassages:\n")
    body = "\n\n".join(f"[P{p['chunk_id']}] ({p.get('section') or 'no section'})\n{p['text']}" for p in passages)
    qs = "\n".join(f"- column \"{c.name}\" (type: {c.type}): {c.question}" + (f" Instructions: {c.instructions}" if c.instructions else "")
                   for c in columns)
    parts = [Part(header + body, cache=True),
             Part(f"Answer every one of these columns for this document (one entry per column, in this order):\n{qs}")]
    return SYSTEM, parts, output_schema(columns)


# --------------------------------------------------------------------------- retrieval
def key_terms(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", question.lower())
    return [w for w in dict.fromkeys(words) if w not in STOP][:8]


def retrieve(index, doc_id: int, columns: list[Column]) -> list[dict]:
    db = index.db
    total = db.execute("SELECT COALESCE(SUM(LENGTH(text)),0) FROM chunks WHERE doc_id=?", (doc_id,)).fetchone()[0]
    if total <= MAX_DOC_CHARS:
        rows = db.execute("SELECT chunk_id, ord, section, text FROM chunks WHERE doc_id=? ORDER BY ord", (doc_id,)).fetchall()
        return [dict(r) for r in rows]
    picked: dict[int, dict] = {}
    for c in columns:
        terms = key_terms(c.question + " " + c.name)
        if not terms:
            continue
        q = " OR ".join(f'"{t}"*' for t in terms)
        rows = db.execute(
            "SELECT c.chunk_id, c.ord, c.section, c.text FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.rowid "
            "WHERE chunks_fts MATCH ? AND c.doc_id=? ORDER BY bm25(chunks_fts) LIMIT ?",
            (q, doc_id, PER_COLUMN_PASSAGES)).fetchall()
        for r in rows:
            picked.setdefault(r["chunk_id"], dict(r))
    out, size = [], 0
    for p in sorted(picked.values(), key=lambda p: p["ord"]):
        if size + len(p["text"]) > MAX_CONTEXT_CHARS:
            break
        out.append(p)
        size += len(p["text"])
    if not out:  # nothing matched: fall back to the start of the document
        rows = db.execute("SELECT chunk_id, ord, section, text FROM chunks WHERE doc_id=? ORDER BY ord LIMIT 25", (doc_id,)).fetchall()
        out = [dict(r) for r in rows]
    return out


# --------------------------------------------------------------------------- grounding
def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    return re.sub(r"[^a-z0-9$%.,'\-]+", " ", s).strip()


def verify(cells: list[Cell], passages: list[dict]) -> None:
    by_id = {p["chunk_id"]: p for p in passages}
    for cell in cells:
        if cell.status in ("refused", "error"):
            continue
        for c in cell.citations:
            p = by_id.get(c.get("passage_id"))
            c["verified"] = bool(p) and bool(c.get("quote")) and _norm(c["quote"]) in _norm(p["text"])
            c["section"] = p.get("section") if p else None
        if cell.not_found:
            cell.status = "not_found"
        elif cell.citations and all(c["verified"] for c in cell.citations):
            cell.status = "ok"
        else:
            cell.status = "unverified"


# --------------------------------------------------------------------------- model call
def answer_row(router, index, doc: dict, columns: list[Column], effort: str = "medium") -> tuple[list[Cell], dict]:
    """One LLM call for the row via the model-agnostic router (stage "matrix")."""
    from .llm import LLMRefusal
    passages = retrieve(index, doc["doc_id"], columns)
    system, parts, schema = build_prompt(doc, passages, columns)
    cells = {c.name: Cell(doc["doc_id"], c.name) for c in columns}
    try:
        res = router.complete_json("matrix", system, parts, schema, effort=effort)
    except LLMRefusal as e:
        for cell in cells.values():
            cell.status, cell.error = "refused", str(e)
        return list(cells.values()), {}
    except Exception as e:  # provider errors (rate limits after retries, auth, bad JSON) mark the row, don't stop the matrix
        for cell in cells.values():
            cell.status, cell.error = "error", repr(e)[:300]
        return list(cells.values()), {}
    data, usage = res.data, {**res.usage, "model": res.model, "repaired": res.repaired}
    for a in data.get("answers", []):
        cell = cells.get(a.get("column"))
        if not cell:
            continue
        cell.answer, cell.value, cell.unit = a.get("answer", ""), a.get("value"), a.get("unit")
        cell.confidence, cell.not_found = a.get("confidence"), bool(a.get("not_found"))
        cell.citations = [{"passage_id": c.get("passage_id"), "quote": c.get("quote", "")} for c in a.get("citations", [])]
    for cell in cells.values():
        if not cell.answer and cell.status == "pending":
            cell.status, cell.error = "error", "model returned no answer for this column"
    verify([c for c in cells.values() if c.status == "pending"], passages)
    return list(cells.values()), usage


# --------------------------------------------------------------------------- extractive engine (no API key)
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(“\"$])")
CURRENCY_RE = re.compile(r"\$\s?\(?[\d,]+(?:\.\d+)?\)?(?:\s*(?:million|billion|thousand|trillion))?", re.I)
PERCENT_RE = re.compile(r"-?\d+(?:\.\d+)?\s?%")
NUMBER_RE = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?(?![\w%])")
DATE_RE = re.compile(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}")
SCALE = {"thousand": 1e-3, "million": 1.0, "billion": 1e3, "trillion": 1e6}


_SUFFIXES = ("ations", "ation", "ings", "ing", "ions", "ion", "ies", "es", "ed", "s", "al", "ly")


def _stem(w: str) -> str:
    """Light suffix stripping (contracts->contract, provisions->provis); unlike truncation it
    never turns 'control' into a prefix of 'contracts'."""
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _stem_hits(text: str, terms: list[str]) -> int:
    t = text.lower()
    return sum(1 for w in terms if re.search(r"\b" + re.escape(_stem(w)), t))


def _windows(text: str, terms: list[str], width: int = 320) -> list[str]:
    """Sentences; long table-like runs are cut to a window around the first matching term."""
    out = []
    for s in SENT_RE.split(text):
        s = s.strip()
        if len(s) <= 450:
            out.append(s)
            continue
        low = s.lower()
        pos = [low.find(_stem(w)) for w in terms]
        pos = [p for p in pos if p >= 0]
        if pos:
            start = max(0, min(pos) - 60)
            out.append(s[start:start + width].strip())
    return [s for s in out if len(s) >= 25]


def _value(sentence: str, typ: str):
    if typ == "currency":
        m = CURRENCY_RE.search(sentence)
        if m:
            raw = m.group(0)
            num = float(re.sub(r"[^\d.]", "", raw.split()[0] if " " in raw.strip("$ ") else raw) or "nan")
            scale = next((v for k, v in SCALE.items() if k in raw.lower()), None)
            return (num * scale, "$ millions") if scale else (num, "$ (as printed; tables are usually in millions)")
    if typ == "percent":
        m = PERCENT_RE.search(sentence)
        if m:
            return float(m.group(0).replace("%", "").strip()), "%"
    if typ == "number":
        m = NUMBER_RE.search(sentence)
        if m:
            return float(m.group(0).replace(",", "")), None
    if typ == "date":
        m = DATE_RE.search(sentence)
        if m:
            from datetime import datetime
            return datetime.strptime(m.group(0).replace("  ", " "), "%B %d, %Y").date().isoformat(), None
    return None, None


def answer_row_extractive(index, doc: dict, columns: list[Column]) -> tuple[list[Cell], dict]:
    """No-LLM answers: the best-matching sentence(s) quoted verbatim, plus a regex-parsed value."""
    passages = retrieve(index, doc["doc_id"], columns)
    cells = []
    for col in columns:
        terms = key_terms(col.question + " " + col.name)
        # adjacent word pairs from the question ("total revenue", "gross margin") score extra when found together
        words = [w for w in re.findall(r"[a-z][a-z\-]+", col.question.lower())]
        pairs = [f"{a} {b}" for a, b in zip(words, words[1:]) if a not in STOP and b not in STOP]
        # "change of control", "rights of first refusal": content word + joining word + content word
        pairs += [f"{a} {j} {b}" for a, j, b in zip(words, words[1:], words[2:])
                  if j in ("of", "to", "in", "for", "and", "on") and a not in STOP and b not in STOP]
        cands = []
        for p in passages:
            for s in _windows(p["text"], terms):
                hits = _stem_hits(s, terms)
                if hits == 0:
                    continue
                low = s.lower()
                phrase = sum(2.0 if ph.count(" ") == 2 else 1.5 for ph in pairs if ph in low) + \
                    (1.0 if "total" in col.question.lower() and "total" in low else 0)
                bonus = 0.5 if col.type in ("currency", "percent", "number", "date") and _value(s, col.type)[0] is not None else 0
                cands.append((hits + phrase + bonus - len(s) / 4000, p, s))
        cands.sort(key=lambda x: -x[0])
        cell = Cell(doc["doc_id"], col.name)
        if not cands or cands[0][0] < 0.9:  # needs at least one real term match; answers are labelled low-confidence quotes
            cell.not_found, cell.answer, cell.status = True, "No matching passage found", "not_found"
            cells.append(cell)
            continue
        take = 3 if col.type == "list" else 1
        chosen, seen = [], set()
        for score, p, s in cands:
            if p["chunk_id"] in seen and col.type == "list":
                continue
            chosen.append((p, s))
            seen.add(p["chunk_id"])
            if len(chosen) >= take:
                break
        cell.answer = " … ".join(s for _, s in chosen)
        cell.value, cell.unit = _value(chosen[0][1], col.type) if col.type != "text" else (None, None)
        cell.confidence = "low"
        cell.citations = [{"passage_id": p["chunk_id"], "quote": s} for p, s in chosen]
        cells.append(cell)
    verify(cells, passages)
    for c in cells:
        if c.status == "ok":
            c.status = "extracted"   # a quoted passage, not an AI-written answer
    return cells, {}


# --------------------------------------------------------------------------- storage
SCHEMA = """
CREATE TABLE IF NOT EXISTS matrices(id INTEGER PRIMARY KEY, name TEXT UNIQUE, created_at REAL, columns TEXT);
CREATE TABLE IF NOT EXISTS matrix_rows(matrix_id INTEGER, doc_id INTEGER, ord INTEGER, PRIMARY KEY(matrix_id, doc_id));
CREATE TABLE IF NOT EXISTS matrix_cells(
  matrix_id INTEGER, doc_id INTEGER, column_name TEXT, answer TEXT, value TEXT, unit TEXT, confidence TEXT,
  status TEXT, citations TEXT, error TEXT, model TEXT, usage TEXT, updated_at REAL,
  PRIMARY KEY(matrix_id, doc_id, column_name));
"""


class MatrixStore:
    def __init__(self, index):
        self.index = index
        self.db = index.db
        self.db.executescript(SCHEMA)

    def create(self, name: str, doc_ids: list[int], columns: list[Column]) -> int:
        cur = self.db.execute("INSERT INTO matrices(name, created_at, columns) VALUES(?,?,?)",
                              (name, time.time(), json.dumps([c.__dict__ for c in columns])))
        mid = cur.lastrowid
        self.db.executemany("INSERT OR IGNORE INTO matrix_rows VALUES(?,?,?)", [(mid, d, i) for i, d in enumerate(doc_ids)])
        self.db.commit()
        return mid

    def get_id(self, name_or_id) -> int:
        r = self.db.execute("SELECT id FROM matrices WHERE name=? OR id=?", (str(name_or_id), name_or_id)).fetchone()
        if not r:
            raise KeyError(f"no matrix {name_or_id!r}")
        return r["id"]

    def columns(self, mid: int) -> list[Column]:
        return [Column(**c) for c in json.loads(self.db.execute("SELECT columns FROM matrices WHERE id=?", (mid,)).fetchone()[0])]

    def add_column(self, mid: int, col: Column) -> None:
        cols = [c for c in self.columns(mid) if c.name != col.name] + [col]
        self.db.execute("UPDATE matrices SET columns=? WHERE id=?", (json.dumps([c.__dict__ for c in cols]), mid))
        self.db.commit()

    def add_rows(self, mid: int, doc_ids: list[int]) -> None:
        n = self.db.execute("SELECT COUNT(*) FROM matrix_rows WHERE matrix_id=?", (mid,)).fetchone()[0]
        self.db.executemany("INSERT OR IGNORE INTO matrix_rows VALUES(?,?,?)", [(mid, d, n + i) for i, d in enumerate(doc_ids)])
        self.db.commit()

    def docs(self, mid: int) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT d.* FROM matrix_rows r JOIN documents d ON d.doc_id=r.doc_id WHERE r.matrix_id=? ORDER BY r.ord", (mid,))]

    def save_cells(self, mid: int, cells: list[Cell], usage: dict, engine: str = "llm") -> None:
        for c in cells:
            self.db.execute("INSERT OR REPLACE INTO matrix_cells VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (mid, c.doc_id, c.column, c.answer, json.dumps(c.value), c.unit, c.confidence, c.status,
                             json.dumps(c.citations), c.error, engine, json.dumps(usage), time.time()))
        self.db.commit()

    def cells(self, mid: int) -> dict:
        out: dict = {}
        for r in self.db.execute("SELECT * FROM matrix_cells WHERE matrix_id=?", (mid,)):
            d = dict(r)
            d["value"] = json.loads(d["value"]) if d["value"] else None
            d["citations"] = json.loads(d["citations"] or "[]")
            out.setdefault(d["doc_id"], {})[d["column_name"]] = d
        return out

    def list(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT m.id, m.name, m.created_at, (SELECT COUNT(*) FROM matrix_rows WHERE matrix_id=m.id) AS rows, m.columns "
            "FROM matrices m ORDER BY m.created_at DESC")]

    def view(self, mid: int) -> dict:
        cols = self.columns(mid)
        cells = self.cells(mid)
        return {"id": mid, "columns": [c.__dict__ for c in cols],
                "rows": [{"doc": d, "cells": cells.get(d["doc_id"], {})} for d in self.docs(mid)]}

    # ------------------------------------------------------------------ run
    def run(self, mid: int, client, only_missing: bool = True, columns: list[str] | None = None,
            workers: int = 4, effort: str = "medium", progress=None) -> dict:
        """client=None runs the extractive (no API key) engine. With a Claude client, cells previously
        filled by the extractive engine count as missing, so adding a key upgrades them."""
        engine = client.describe("matrix") if client is not None else "extractive"
        cols = [c for c in self.columns(mid) if not columns or c.name in columns]
        existing = self.cells(mid)
        done_states = ("ok", "not_found", "unverified", "extracted")

        def filled(cell) -> bool:
            if not cell or cell.get("status") not in done_states:
                return False
            return not (engine != "extractive" and cell.get("model") == "extractive")

        jobs = []
        for d in self.docs(mid):
            todo = [c for c in cols if not (only_missing and filled(existing.get(d["doc_id"], {}).get(c.name)))]
            if todo:
                jobs.append((d, todo))
        stats = {"engine": engine, "rows": len(jobs), "cells": 0, "ok": 0, "extracted": 0, "unverified": 0, "not_found": 0,
                 "refused": 0, "error": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        if engine == "extractive":
            workers = 1  # reads share one SQLite connection; this engine is fast anyway
        with ThreadPoolExecutor(max_workers=workers) as ex:
            if engine == "extractive":
                futs = {ex.submit(answer_row_extractive, self.index, d, todo): d for d, todo in jobs}
            else:
                futs = {ex.submit(answer_row, client, self.index, d, todo, effort): d for d, todo in jobs}
            for i, f in enumerate(as_completed(futs), 1):
                cells, usage = f.result()
                self.save_cells(mid, cells, usage, engine)  # sqlite writes on this thread only
                for c in cells:
                    stats["cells"] += 1
                    stats[c.status] = stats.get(c.status, 0) + 1
                for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
                    stats[k] += usage.get(k) or 0
                if progress:
                    progress(i, len(jobs))
        return stats

    def export_csv(self, mid: int, path) -> None:
        v = self.view(mid)
        names = [c["name"] for c in v["columns"]]
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["company", "ticker", "form", "filed", "url"] + names + [f"{n} [source]" for n in names])
            for r in v["rows"]:
                d, cells = r["doc"], r["cells"]
                answers = [cells.get(n, {}).get("answer", "") for n in names]
                sources = ["; ".join(f"[{c.get('section') or ''}] \"{c['quote']}\"{'' if c.get('verified') else ' (UNVERIFIED)'}"
                                     for c in cells.get(n, {}).get("citations", [])) for n in names]
                w.writerow([d["company"], d["ticker"], d["form"], d["filed"], d["url"]] + answers + sources)


def make_client(engine: str = "auto"):
    """Model router for the Matrix, or None for the extractive (no-key) engine.

    engine: "auto"       -> configured model for stage "matrix" (OM_MODEL_MATRIX / OM_MODEL_DEFAULT / first key found), else extractive
            "extractive" -> no LLM
            "<provider>[:<model>]" e.g. "deepseek", "deepseek:deepseek-reasoner", "anthropic:claude-opus-5-5", "ollama:qwen2.5:14b"
    """
    from .llm import LLMError, Router, make_provider
    if engine == "extractive":
        return None
    if engine in ("auto", "llm"):
        r = Router()
        return r if r.available("matrix") else None
    try:
        return Router({"matrix": make_provider("anthropic" if engine == "claude" else engine)})
    except LLMError as e:
        raise SystemExit(str(e))
