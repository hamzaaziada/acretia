"""Full-text search over ingested filings (SQLite FTS5: BM25 ranking, Porter stemming, phrases, NEAR, prefix*).

Query syntax (FTS5):  pricing pressure        both words (stemmed: "pressures" matches)
                      "supply chain"          exact phrase
                      tariff OR tariffs       either
                      china NOT taiwan        exclude
                      NEAR(price increase, 10) within 10 tokens
                      semicond*               prefix
Malformed queries fall back to an AND of quoted terms.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  doc_id INTEGER PRIMARY KEY, url TEXT UNIQUE, accession TEXT, file TEXT, cik INTEGER, ticker TEXT, company TEXT,
  form TEXT, filed TEXT, report_date TEXT, title TEXT, items TEXT, n_chars INTEGER, ingested_at REAL);
CREATE INDEX IF NOT EXISTS ix_doc_cik ON documents(cik);
CREATE INDEX IF NOT EXISTS ix_doc_filed ON documents(filed);
CREATE TABLE IF NOT EXISTS chunks(
  chunk_id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES documents(doc_id), ord INTEGER, section TEXT,
  offset INTEGER, text TEXT);
CREATE INDEX IF NOT EXISTS ix_chunk_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, section, content='chunks', content_rowid='chunk_id', tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS saved_searches(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, query TEXT, filters TEXT, created_at REAL, last_run_at REAL);
"""


class Index:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")  # readers don't block the background writers
        self.db.executescript(SCHEMA)
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(documents)")}
        for col, typ in (("room_id", "INTEGER"), ("source", "TEXT"), ("path", "TEXT"), ("pages", "INTEGER"),
                         ("sha256", "TEXT"), ("warnings", "TEXT")):
            if col not in have:
                self.db.execute(f"ALTER TABLE documents ADD COLUMN {col} {typ}")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_doc_room ON documents(room_id)")
        self.db.commit()

    # ------------------------------------------------------------------ writes
    def has(self, url: str) -> bool:
        return self.db.execute("SELECT 1 FROM documents WHERE url=?", (url,)).fetchone() is not None

    def add(self, ref, passages, n_chars: int) -> int:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO documents(url,accession,file,cik,ticker,company,form,filed,report_date,title,items,n_chars,ingested_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ref.url, ref.accession, ref.file, ref.cik, ref.ticker, ref.company, ref.form, ref.filed, ref.report_date,
             ref.title, ref.items, n_chars, time.time()))
        if not cur.lastrowid or cur.rowcount == 0:
            return 0
        doc_id = cur.lastrowid
        for p in passages:
            c = self.db.execute("INSERT INTO chunks(doc_id,ord,section,offset,text) VALUES(?,?,?,?,?)",
                                (doc_id, p.ord, p.section, p.offset, p.text))
            self.db.execute("INSERT INTO chunks_fts(rowid,text,section) VALUES(?,?,?)", (c.lastrowid, p.text, p.section or ""))
        self.db.commit()
        return len(passages)

    # ------------------------------------------------------------------ query helpers
    @staticmethod
    def fts_query(q: str) -> str:
        return q.strip()

    @staticmethod
    def safe_query(q: str) -> str:
        terms = re.findall(r'"[^"]+"|[\w.\-]+\*?', q)
        out = []
        for t in terms:
            if t.upper() in ("AND", "OR", "NOT"):
                continue
            if t.startswith('"'):
                out.append(t)
            elif t.endswith("*"):
                out.append('"' + t[:-1].replace('"', "") + '"*')
            else:
                out.append('"' + t.replace('"', "") + '"')
        return " AND ".join(out) or '""'

    def _where(self, f: dict) -> tuple[str, list]:
        clauses, args = [], []
        if f.get("room"):
            clauses.append("d.room_id = ?")
            args.append(int(f["room"]))
        elif f.get("public_only"):
            clauses.append("d.room_id IS NULL")
        if f.get("tickers"):
            ts = [t.upper() for t in f["tickers"]]
            clauses.append(f"d.ticker IN ({','.join('?' * len(ts))})")
            args += ts
        if f.get("forms"):
            clauses.append(f"d.form IN ({','.join('?' * len(f['forms']))})")
            args += f["forms"]
        if f.get("date_from"):
            clauses.append("d.filed >= ?")
            args.append(f["date_from"])
        if f.get("date_to"):
            clauses.append("d.filed <= ?")
            args.append(f["date_to"])
        if f.get("section"):
            clauses.append("c.section LIKE ?")
            args.append(f"%{f['section']}%")
        if f.get("since_ingest"):
            clauses.append("d.ingested_at > ?")
            args.append(f["since_ingest"])
        return (" AND " + " AND ".join(clauses)) if clauses else "", args

    def _run(self, sql: str, q: str, args: list):
        try:
            return self.db.execute(sql, [self.fts_query(q)] + args).fetchall(), q
        except sqlite3.OperationalError:
            sq = self.safe_query(q)
            return self.db.execute(sql, [sq] + args).fetchall(), sq

    # ------------------------------------------------------------------ search
    def search(self, q: str, filters: dict | None = None, limit: int = 20, offset: int = 0, per_doc: int = 2) -> dict:
        f = filters or {}
        where, args = self._where(f)
        sql = f"""
          SELECT c.chunk_id, c.doc_id, c.section, c.offset, bm25(chunks_fts, 1.0, 0.4) AS score,
                 snippet(chunks_fts, 0, '<mark>', '</mark>', '…', 40) AS snip,
                 d.ticker, d.company, d.form, d.filed, d.title, d.url, d.accession, d.cik
          FROM chunks_fts JOIN chunks c ON c.chunk_id = chunks_fts.rowid JOIN documents d ON d.doc_id = c.doc_id
          WHERE chunks_fts MATCH ? {where}
          ORDER BY score LIMIT 2000"""
        rows, used = self._run(sql, q, args)
        by_doc: dict[int, dict] = {}
        for r in rows:
            d = by_doc.get(r["doc_id"])
            if d is None:
                d = by_doc[r["doc_id"]] = {k: r[k] for k in ("doc_id", "ticker", "company", "form", "filed", "title",
                                                               "url", "accession", "cik")}
                d.update(score=r["score"], hits=0, passages=[])
            d["hits"] += 1
            if len(d["passages"]) < per_doc:
                d["passages"].append({"chunk_id": r["chunk_id"], "section": r["section"], "snippet": r["snip"]})
        docs = sorted(by_doc.values(), key=lambda d: d["score"])
        if f.get("sort") == "date":
            docs.sort(key=lambda d: d["filed"], reverse=True)
        return {"query": q, "fts": used, "total_passages": len(rows), "total_documents": len(docs),
                "results": docs[offset:offset + limit]}

    def facets(self, q: str, filters: dict | None = None) -> dict:
        where, args = self._where(filters or {})
        base = f"FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.rowid JOIN documents d ON d.doc_id=c.doc_id WHERE chunks_fts MATCH ? {where}"
        out = {}
        for name, col in (("company", "d.ticker"), ("form", "d.form"), ("year", "substr(d.filed,1,4)"), ("section", "c.section")):
            rows, _ = self._run(f"SELECT {col} AS k, COUNT(DISTINCT d.doc_id) AS n {base} GROUP BY k ORDER BY n DESC LIMIT 15", q, args)
            out[name] = [{"key": r["k"], "documents": r["n"]} for r in rows if r["k"]]
        return out

    def trend(self, q: str, filters: dict | None = None) -> list[dict]:
        """Mentions per quarter: documents mentioning the query and total passages, by filing quarter."""
        where, args = self._where(filters or {})
        sql = f"""SELECT substr(d.filed,1,4) || '-Q' || ((CAST(substr(d.filed,6,2) AS INTEGER)+2)/3) AS qtr,
                         COUNT(DISTINCT d.doc_id) AS docs, COUNT(*) AS passages
                  FROM chunks_fts JOIN chunks c ON c.chunk_id=chunks_fts.rowid JOIN documents d ON d.doc_id=c.doc_id
                  WHERE chunks_fts MATCH ? {where} GROUP BY qtr ORDER BY qtr"""
        rows, _ = self._run(sql, q, args)
        totals = {r["qtr"]: r["n"] for r in self.db.execute(
            "SELECT substr(filed,1,4) || '-Q' || ((CAST(substr(filed,6,2) AS INTEGER)+2)/3) AS qtr, COUNT(*) AS n FROM documents GROUP BY qtr")}
        return [{"quarter": r["qtr"], "documents": r["docs"], "passages": r["passages"],
                 "share_of_filings": round(r["docs"] / totals[r["qtr"]], 4) if totals.get(r["qtr"]) else None} for r in rows]

    def passage(self, chunk_id: int, context: int = 1) -> dict:
        c = self.db.execute("SELECT * FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
        if not c:
            return {}
        d = self.db.execute("SELECT * FROM documents WHERE doc_id=?", (c["doc_id"],)).fetchone()
        around = self.db.execute("SELECT ord, section, text FROM chunks WHERE doc_id=? AND ord BETWEEN ? AND ? ORDER BY ord",
                                 (c["doc_id"], c["ord"] - context, c["ord"] + context)).fetchall()
        return {"document": dict(d), "chunk_id": chunk_id, "ord": c["ord"], "section": c["section"],
                "passages": [dict(a) for a in around]}

    def stats(self) -> dict:
        r = self.db.execute("SELECT COUNT(*) n, COUNT(DISTINCT cik) c, MIN(filed) a, MAX(filed) b FROM documents").fetchone()
        return {"documents": r["n"], "companies": r["c"], "from": r["a"], "to": r["b"],
                "passages": self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "forms": [dict(x) for x in self.db.execute("SELECT form, COUNT(*) n FROM documents GROUP BY form ORDER BY n DESC")]}

    # ------------------------------------------------------------------ saved searches & alerts
    def save(self, name: str, q: str, filters: dict | None = None) -> None:
        self.db.execute("INSERT INTO saved_searches(name,query,filters,created_at,last_run_at) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(name) DO UPDATE SET query=excluded.query, filters=excluded.filters",
                        (name, q, json.dumps(filters or {}), time.time(), time.time()))
        self.db.commit()

    def saved(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM saved_searches ORDER BY name")]

    def delete_saved(self, name: str) -> None:
        self.db.execute("DELETE FROM saved_searches WHERE name=?", (name,))
        self.db.commit()

    def alerts(self, mark: bool = True) -> list[dict]:
        """New matches for each saved search among documents ingested since it last ran."""
        out = []
        for s in self.saved():
            f = json.loads(s["filters"] or "{}")
            f["since_ingest"] = s["last_run_at"] or 0
            res = self.search(s["query"], f, limit=50)
            out.append({"name": s["name"], "query": s["query"], "new_documents": res["total_documents"],
                        "results": res["results"]})
            if mark:
                self.db.execute("UPDATE saved_searches SET last_run_at=? WHERE id=?", (time.time(), s["id"]))
        self.db.commit()
        return out
