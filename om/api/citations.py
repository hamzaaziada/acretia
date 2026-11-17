"""Citation tokens: one opaque token per sourced figure, resolvable by any viewer (SPEC section 4).

`mint(conn, org_id, **fields)` is called by the agent engines; `GET /api/v1/citations/{token}` resolves a token and
`GET /api/v1/jobs/{job_id}/sources.zip` is the "download all sources" control (parity item 18).
Every query filters on org_id; another org's token or job is a 404.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import secrets
import zipfile

from .db import now
from .http import ApiError, Response, Route

SCHEMA = """
CREATE TABLE IF NOT EXISTS citations(
  org_id TEXT NOT NULL, token TEXT NOT NULL, doc_id TEXT, page INTEGER, bbox_json TEXT, quote TEXT NOT NULL DEFAULT '',
  url TEXT, as_of TEXT, xbrl_concept TEXT, cell_locator TEXT, doc_name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'document',
  fingerprint TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, PRIMARY KEY(org_id, token));
CREATE INDEX IF NOT EXISTS citations_fp ON citations(org_id, fingerprint);
"""

KINDS = ("document", "filing", "xbrl", "cell", "web", "market")
_FIELDS = ("doc_id", "page", "bbox", "quote", "url", "as_of", "xbrl_concept", "cell_locator", "doc_name", "kind", "sha256_span_hash")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")
_XBRL = re.compile(r"[A-Za-z][A-Za-z0-9-]*:[A-Za-z][A-Za-z0-9_]*$")
_LOC = re.compile(r"[^!]+![A-Z]{1,3}\d+(?::[A-Z]{1,3}\d+)?$")


def _check(c: dict) -> None:
    if c.get("url") and not re.match(r"https?://\S+$", c["url"]):
        raise ValueError(f"citation url must be http(s): {c['url']!r}")
    if c.get("as_of") and not _DATE.match(c["as_of"]):
        raise ValueError(f"citation as_of must be YYYY-MM-DD: {c['as_of']!r}")
    if c.get("xbrl_concept") and not _XBRL.match(c["xbrl_concept"]):
        raise ValueError(f"citation xbrl_concept must look like us-gaap:Revenues: {c['xbrl_concept']!r}")
    if c.get("cell_locator") and not _LOC.match(c["cell_locator"]):
        raise ValueError(f"citation cell_locator must look like Sheet!A1: {c['cell_locator']!r}")
    if c.get("page") is not None and (not isinstance(c["page"], int) or c["page"] < 1):
        raise ValueError("citation page must be a positive integer")
    b = c.get("bbox")
    if b is not None and not (len(b) == 4 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in b)):
        raise ValueError("citation bbox must be four normalised numbers in [0, 1]")
    if not any(c.get(k) for k in ("doc_id", "url", "xbrl_concept", "cell_locator")):
        raise ValueError("a citation needs a doc_id, url, xbrl_concept or cell_locator")
    if c.get("doc_id") and c.get("sha256_span_hash"):                      # full contract validation when both are given
        from om.contracts import Citation, ContractError
        try:
            Citation.from_dict({k: v for k, v in {
                "doc_id": c["doc_id"], "sha256_span_hash": c["sha256_span_hash"], "page": c.get("page"),
                "bbox_norm": list(b) if b else None, "quote": c.get("quote", ""), "url": c.get("url"),
                "as_of": c.get("as_of")}.items() if v is not None})
        except ContractError as e:
            raise ValueError(str(e)) from None


def mint(conn, org_id: str, **c) -> str:
    """Store a citation and return its 22-character urlsafe token (the same content in the same org returns the same token)."""
    unknown = set(c) - set(_FIELDS)
    if unknown:
        raise ValueError(f"unknown citation fields: {sorted(unknown)}")
    _check(c)
    kind = c.get("kind") or ("xbrl" if c.get("xbrl_concept") else "cell" if c.get("cell_locator") else
                             "web" if c.get("url") and not c.get("doc_id") else "document")
    if kind not in KINDS:
        raise ValueError(f"citation kind must be one of {KINDS}")
    canon = json.dumps({k: c.get(k) for k in sorted(_FIELDS) if k != "kind"} | {"kind": kind}, sort_keys=True, default=str)
    fp = hashlib.sha256(canon.encode()).hexdigest()
    row = conn.execute("SELECT token FROM citations WHERE org_id=? AND fingerprint=?", (org_id, fp)).fetchone()
    if row:
        return row[0]
    token = secrets.token_urlsafe(16)
    conn.execute(
        "INSERT INTO citations(org_id, token, doc_id, page, bbox_json, quote, url, as_of, xbrl_concept, cell_locator, doc_name, kind, "
        "fingerprint, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (org_id, token, c.get("doc_id"), c.get("page"), json.dumps(list(c["bbox"])) if c.get("bbox") else None, c.get("quote", ""),
         c.get("url"), c.get("as_of"), c.get("xbrl_concept"), c.get("cell_locator"), c.get("doc_name", ""), kind, fp, now()))
    return token


def resolve(conn, org_id: str, token: str) -> dict | None:
    r = conn.execute("SELECT * FROM citations WHERE org_id=? AND token=?", (org_id, token)).fetchone()
    if r is None:
        return None
    return {"token": r["token"], "doc_id": r["doc_id"], "page": r["page"],
            "bbox_norm": json.loads(r["bbox_json"]) if r["bbox_json"] else None, "quote": r["quote"], "as_of": r["as_of"],
            "url": r["url"], "doc_name": r["doc_name"], "kind": r["kind"], "xbrl_concept": r["xbrl_concept"],
            "cell_locator": r["cell_locator"]}


def get_citation(ctx):
    c = resolve(ctx.conn, ctx.org_id, ctx.params["token"])
    if c is None:
        raise ApiError(404, "not_found", "No such citation.")
    return c


def job_sources(conn, org_id: str, job_id: str) -> list[dict] | None:
    """The distinct citations a job emitted as `source` events, or None when the job is not in this org."""
    if conn.execute("SELECT 1 FROM jobs WHERE id=? AND org_id=?", (job_id, org_id)).fetchone() is None:
        return None
    seen, out = set(), []
    for r in conn.execute("SELECT data_json FROM job_events WHERE job_id=? AND type='source' ORDER BY seq", (job_id,)):
        tok = json.loads(r[0]).get("citation_token")
        if tok and tok not in seen:
            seen.add(tok)
            c = resolve(conn, org_id, tok)
            if c:
                out.append(c)
    return out


def sources_zip(ctx):
    """Download all sources of a run: the cited documents that exist in this org plus a sources.csv index."""
    cites = job_sources(ctx.conn, ctx.org_id, ctx.params["job_id"])
    if cites is None:
        raise ApiError(404, "not_found", "No such run.")
    buf = io.BytesIO()
    docs_seen: dict[str, str] = {}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["token", "kind", "doc_name", "page", "quote", "url", "as_of", "xbrl_concept", "cell_locator", "file"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in cites:
            fname = ""
            did = c["doc_id"]
            if did:
                if did not in docs_seen:
                    docs_seen[did] = ""
                    try:
                        d = ctx.conn.execute("SELECT name, sha256 FROM documents WHERE id=? AND org_id=?", (did, ctx.org_id)).fetchone()
                        data = ctx.blobs.get(d["sha256"]) if d and d["sha256"] else None
                        if data is not None:
                            name = re.sub(r"[^\w.\- ]", "_", d["name"]) or did
                            docs_seen[did] = f"documents/{did}_{name}"
                            z.writestr(docs_seen[did], data)
                    except Exception:           # documents table or blob missing: the CSV row still lists the citation
                        pass
                fname = docs_seen[did]
            w.writerow([c["token"], c["kind"], c["doc_name"], c["page"] or "", c["quote"], c["url"] or "", c["as_of"] or "",
                        c["xbrl_concept"] or "", c["cell_locator"] or "", fname])
        z.writestr("sources.csv", out.getvalue())
    ctx.audit("sources.download", ctx.params["job_id"], {"citations": len(cites)})
    return Response(200, buf.getvalue(), "application/zip",
                    {"Content-Disposition": f'attachment; filename="sources-{ctx.params["job_id"]}.zip"'})


ROUTES = [
    Route("GET", "/api/v1/citations/{token}", get_citation, role="viewer"),
    Route("GET", "/api/v1/jobs/{job_id}/sources.zip", sources_zip, role="viewer"),
]
