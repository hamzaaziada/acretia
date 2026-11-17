"""The stable annual-report call (S8.3b): `read_report` and friends. See docs/interfaces.md "Annual-report reading".

PDF -> extract -> tie-out check (with the prior year's extract when given) -> strict release -> review queue.
No model call is made: `tokens` and `cost_usd` are 0. Telemetry (docs/product/SPEC.md "Telemetry") is appended to
`evals/intl/telemetry.jsonl` (override the path with `ACRETIA_TELEMETRY_PATH`, or the `telemetry_path` argument;
`ACRETIA_TELEMETRY_PATH=off` disables it).
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import extract as _extract_mod
from . import review as _review
from . import tieout
from .types import ExtractedStatements, Figure

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TELEMETRY = ROOT / "evals" / "intl" / "telemetry.jsonl"
MINUTES_CSV = ROOT / "evals" / "intl" / "review_minutes.csv"
STEPS = ("parse", "ocr", "extract", "tieout", "review")


class ModelBlocked(RuntimeError):
    """The release gate refused the report; the message lists why (failed ties, figures in review)."""


@dataclass
class ReportResult:
    statements: object                 # IntlStatements | None
    extracted: ExtractedStatements
    tie_report: object
    review: list
    blocked: bool
    telemetry: dict
    block_reason: str = ""

    def to_json(self, crop_dir: str | None = None) -> dict:
        ex = self.extracted
        figs = []
        for f in ex.figures:
            figs.append({"key": f.key, "label": f.label, "value": f.value, "raw": f.raw, "scale": f.scale,
                         "period_end": f.period_end.isoformat(),
                         "period_start": f.period_start.isoformat() if f.period_start else None,
                         "statement": f.statement, "page": f.page, "bbox_norm": list(f.bbox_norm),
                         "label_bbox": list(f.label_bbox) if f.label_bbox else None, "confidence": f.confidence,
                         "ocr_conf": f.ocr_conf, "source": f.source, "status": f.status, "reasons": list(f.reasons),
                         "sha256_span_hash": f.sha256_span_hash, "is_total": f.is_total, "row": f.row,
                         "components": f.components})
        rev = []
        for n, it in enumerate(self.review):
            rec = {"key": it.figure.key, "label": it.figure.label, "raw": it.figure.raw, "page": it.page,
                   "bbox_norm": list(it.bbox_norm), "reasons": list(it.reasons),
                   "period_end": it.figure.period_end.isoformat()}
            if it.crop_png:
                if crop_dir:
                    os.makedirs(crop_dir, exist_ok=True)
                    path = os.path.join(crop_dir, f"{ex.doc_id[:12]}_p{it.page}_{n}.png")
                    with open(path, "wb") as fh:
                        fh.write(it.crop_png)
                    rec["crop_path"] = path
                else:
                    rec["crop_png_b64"] = base64.b64encode(it.crop_png).decode("ascii")
            rev.append(rec)
        tr = self.tie_report
        ties = [{"name": t.name, "period": str(t.period), "lhs": t.lhs, "rhs": t.rhs, "diff": t.diff, "passed": t.passed,
                 "hard": t.hard, "restated": t.restated, "figures": list(t.figures)} for t in tr.ties]
        return {"v": 1, "doc_sha256": ex.doc_id, "company": ex.company, "currency": ex.currency,
                "unit_scale": ex.unit_scale, "standard": ex.standard, "language": ex.language,
                "fiscal_year_end_month": ex.fiscal_year_end_month, "periods": [p.isoformat() for p in ex.periods],
                "blocked": self.blocked, "block_reason": self.block_reason, "released": self.statements is not None,
                "tie_passed": bool(tr.passed), "ties": ties, "warnings": list(tr.warnings) + list(ex.warnings),
                "figures": figs, "review": rev, "telemetry": self.telemetry}


# ------------------------------------------------------------------------------------------------ telemetry
def minutes_table(path=MINUTES_CSV) -> dict:
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["reason_class"].strip()] = float(r["minutes_per_flag"])
    return out


def classify(reasons) -> str | None:
    """One review-reason class per flagged figure (the first that applies)."""
    rs = [str(r) for r in reasons]
    if any(r.startswith("ocr-disagreement") for r in rs):
        return "ocr_disagreement"
    if any(r.startswith("tie-failed:prior:") for r in rs):
        return "comparative_mismatch"
    if any(r.startswith("tie-failed") for r in rs):
        return "tie_fail"
    if any(r.startswith("low-confidence") for r in rs):
        return "low_ocr_conf"
    if any(r in ("unmapped_label",) or r.startswith("label-conflict") for r in rs):
        return "unmapped_label"
    return None


def flag_counts(ex: ExtractedStatements) -> dict:
    counts: dict = {}
    for f in ex.figures:
        cls = None
        if f.status == "review":
            cls = classify(f.reasons) or "low_ocr_conf"
        elif f.key is None and "unmapped_label" in f.reasons:
            cls = "unmapped_label"
        if cls:
            counts[cls] = counts.get(cls, 0) + 1
    if any("unit not printed" in w for w in ex.warnings):
        counts["unit_ambiguous"] = counts.get("unit_ambiguous", 0) + 1
    return counts


def review_minutes(flags: dict) -> float:
    table = minutes_table()
    return round(sum(c * table.get(k, 0.0) for k, c in flags.items()), 6)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def build_telemetry(ex, info, steps, wall, flags) -> dict:
    return {"v": 1, "doc_sha256": ex.doc_id, "wall_seconds": round(wall, 4), "steps": steps,
            "pages": info.get("pages", 0), "scanned": bool(info.get("scanned")), "language": ex.language,
            "tokens": 0, "cost_usd": 0.0, "engine": info.get("engine", ""), "flags": flags,
            "review_minutes": review_minutes(flags)}


def _steps(info, t0, extra=None):
    """Step records in the order parse, ocr, extract, tieout, review (times from the extractor's own clock)."""
    engine_parse = (info.get("engine") or "").split("+")[0] or "pdfplumber"
    out, cur = [], t0
    plan = [("parse", info.get("parse_s", 0.0), engine_parse), ("ocr", info.get("ocr_s", 0.0), "tesseract"),
            ("extract", info.get("extract_s", 0.0), "om.intl.tables")]
    for name, secs, eng in plan + list(extra or []):
        out.append({"name": name, "started_at": datetime.fromtimestamp(cur, timezone.utc).isoformat(timespec="milliseconds"),
                    "finished_at": datetime.fromtimestamp(cur + secs, timezone.utc).isoformat(timespec="milliseconds"),
                    "seconds": round(secs, 4), "tokens": 0, "cost_usd": 0.0, "engine": eng})
        cur += secs
    return out


def write_telemetry(record: dict, path=None) -> str | None:
    p = path or os.environ.get("ACRETIA_TELEMETRY_PATH") or str(DEFAULT_TELEMETRY)
    if str(p).lower() in ("", "off", "none"):
        return None
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return str(p)


def extract_with_telemetry(pdf, *, company=None, hints=None, telemetry_path=None) -> ExtractedStatements:
    """`om.intl.extract.extract` plus its telemetry record (tieout and review steps recorded as 0 s: not run)."""
    t0 = time.time()
    ex, info = _extract_mod._extract(pdf, company=company, hints=hints)
    steps = _steps(info, t0, [("tieout", 0.0, "om.intl.tieout"), ("review", 0.0, "om.intl.review")])
    write_telemetry(build_telemetry(ex, info, steps, time.time() - t0, flag_counts(ex)), telemetry_path)
    return ex


# ------------------------------------------------------------------------------------------------ read_report
def _as_extract(prior, hints=None):
    if prior is None:
        return None
    if isinstance(prior, ReportResult):
        return prior.extracted
    if isinstance(prior, ExtractedStatements):
        return prior
    return _extract_mod._extract(prior, hints=None)[0]


def read_report(pdf, *, company=None, hints=None, prior=None, strict=True, telemetry_path=None) -> ReportResult:
    t0 = time.time()
    ex, info = _extract_mod._extract(pdf, company=company, hints=hints)
    pex = _as_extract(prior)
    t1 = time.time()
    report = tieout.check(ex, prior=pex)
    statements, blocked, reason = None, False, ""
    try:
        statements = tieout.release(ex, report, strict=strict)
    except tieout.ReleaseBlocked as e:
        blocked, reason = True, str(e)
    t2 = time.time()
    data = pdf if isinstance(pdf, (bytes, bytearray)) else None
    if data is None:
        with open(pdf, "rb") as fh:
            data = fh.read()
    items = _review.queue(ex, report, pdf=bytes(data))
    t3 = time.time()
    # comparative failures are a separate review class: re-classify through the reasons already on the figures
    steps = _steps(info, t0, [("tieout", t2 - t1, "om.intl.tieout"), ("review", t3 - t2, "om.intl.review")])
    flags = flag_counts(ex)
    tel = build_telemetry(ex, info, steps, t3 - t0, flags)
    write_telemetry(tel, telemetry_path)
    return ReportResult(statements, ex, report, items, blocked, tel, reason)


# ------------------------------------------------------------------------------------------------ locate
def locate(figure_or_citation, pdf=None) -> dict:
    """Highlighted page crop for a figure, an `IntlItem`, a `Citation` or a dict with doc/page/bbox. `pdf` (path or
    bytes) may be omitted when the document was extracted in this process (looked up by doc_id)."""
    obj = figure_or_citation
    if hasattr(obj, "figure") and getattr(obj, "figure") is not None:
        obj = obj.figure
    if isinstance(obj, dict):
        doc = obj.get("doc_sha256") or obj.get("doc_id")
        page, bb = int(obj["page"]), obj.get("bbox_norm")
    else:
        doc = getattr(obj, "doc_id", None)
        page, bb = int(obj.page), getattr(obj, "bbox_norm", None)
    if bb is None:
        raise ValueError("no bbox to locate")
    if pdf is None:
        pdf = _extract_mod.SOURCES.get(doc)
        if pdf is None:
            raise ValueError("pdf not given and the document was not extracted in this process")
    if doc is None:
        raw = bytes(pdf) if isinstance(pdf, (bytes, bytearray)) else open(pdf, "rb").read()
        doc = hashlib.sha256(raw).hexdigest()
    png = _review.crop(pdf if isinstance(pdf, (bytes, bytearray)) else str(pdf), page, tuple(bb))
    return {"doc_sha256": doc, "page": page, "bbox_norm": tuple(float(v) for v in bb), "png": png}


# ------------------------------------------------------------------------------------------------ model
def review_summary(res: ReportResult, limit=12) -> str:
    lines = [res.block_reason or "release blocked"]
    for f in [f for f in res.extracted.figures if f.status == "review"][:limit]:
        lines.append(f"  p.{f.page} {f.key or f.label} {f.period_end}: {f.raw} ({', '.join(f.reasons)})")
    return "\n".join(lines)


def ensure_share_count(st) -> bool:
    """om.model3 divides equity value by diluted shares; annual-report statements rarely carry a share count in the
    figures we read. When it is missing, set a clearly labelled placeholder of 1.0 million shares (value per share is
    then per 1m shares) cited to the share-capital line, and warn. Returns True when a placeholder was set."""
    from .types import IntlItem
    rows = st.data.get("diluted_shares")
    if rows is None or any(getattr(i, "value", None) is not None for i in rows):
        return False
    anchor = None
    for k in ("x.share_capital", "equity_total", "assets"):
        for it in st.data.get(k, []):
            if getattr(it, "figure", None) is not None and it.value is not None:
                anchor = it.figure
        if anchor is not None:
            break
    for n, it in enumerate(rows):
        if anchor is None:
            continue
        fig = Figure(key="diluted_shares", label="Share count not in the statements (placeholder 1.0m)", value=1.0,
                     raw="1.0 (placeholder)", scale=1e6, period_end=anchor.period_end, period_start=None, statement="BS",
                     page=anchor.page, bbox_norm=anchor.bbox_norm, label_bbox=None, confidence=0.0, ocr_conf=None,
                     source="derived", doc_id=anchor.doc_id, sha256_span_hash=anchor.sha256_span_hash, status="ok",
                     reasons=["placeholder:no-share-count"])
        rows[n] = IntlItem(1.0, [], it.citation if it.citation is not None else None, 0.0, fig)
    st.warnings.append("no share count in the statements: diluted shares set to a 1.0m placeholder; value per share is "
                       "per 1m shares until the real count is supplied")
    return True


def model_from_report(pdf, out_xlsx, **kw) -> dict:
    """read_report -> om.model3.build -> `out_xlsx`. Raises ModelBlocked (with the review summary) when blocked."""
    from .. import model3
    res = read_report(pdf, **kw)
    if res.blocked or res.statements is None:
        raise ModelBlocked(review_summary(res))
    ensure_share_count(res.statements)
    blob, meta = model3.build(res.statements)
    os.makedirs(os.path.dirname(os.path.abspath(out_xlsx)), exist_ok=True)
    with open(out_xlsx, "wb") as fh:
        fh.write(blob)
    return {"path": str(out_xlsx), "meta": meta, "result": res}


# ------------------------------------------------------------------------------------------------ CLI
def cmd_intl_model(args) -> int:
    kw = {"company": args.company}
    if args.prior:
        kw["prior"] = args.prior
    try:
        res = read_report(args.pdf, **kw)
    except _extract_mod.ExtractError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    ex, tr = res.extracted, res.tie_report
    if args.json:
        print(json.dumps(res.to_json(), ensure_ascii=False, indent=1))
    else:
        t = res.telemetry
        print(f"{ex.company} | {ex.currency} x{ex.unit_scale:g} | {ex.language} | {ex.standard} | "
              f"periods {', '.join(p.isoformat() for p in ex.periods)}")
        ties = tr.ties
        print(f"ties: {sum(1 for x in ties if x.passed)}/{len(ties)} passed"
              + ("" if tr.passed else "  FAILED: " + ", ".join(f"{x.name}@{x.period}" for x in tr.failed if x.hard)[:300]))
        print(f"figures: {len(ex.figures)}  in review: {len(res.review)}  flags: {t['flags']}")
        for it in res.review[:20]:
            print(f"  review p.{it.page} {it.figure.key or it.figure.label} {it.figure.period_end} {it.figure.raw}: "
                  f"{', '.join(it.reasons)}")
        print(f"review time est.: {t['review_minutes']:.1f} min | wall {t['wall_seconds']:.1f}s "
              f"({t['pages']} pages, {'scanned' if t['scanned'] else 'native'})")
    if res.blocked:
        print("BLOCKED: " + review_summary(res), file=sys.stderr)
        return 1
    from .. import model3
    ensure_share_count(res.statements)
    blob, meta = model3.build(res.statements)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(blob)
    if not args.json:
        print(f"wrote {args.out}")
    return 0
