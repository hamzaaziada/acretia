#!/usr/bin/env python3
"""S5.4b evals: 10-K QA scoring, 50-document VDR first pass, reliability, risk detector, opendataloader-bench.

  python3 scripts/eval_s5.py [--fresh] [--docling] [--no-odl]      # full run (timed first pass when the cache DB is absent / --fresh)
  python3 scripts/eval_s5.py --offline                              # reuse evals/out/vdr50.duckdb; no ingest, no network; same extractive numbers

Engine under test: grid.ExtractiveEngine (deterministic, offline). The LLM engine needs a live endpoint (D-021): its scorecard rows are
written as `not run live` with no value; no numbers are ever invented. Gold files are read, never tuned: evals/tenk/gold.jsonl
(10-K room) and evals/vdr50/gold.jsonl (English VDR room + Arabic/scanned room).
"""
from __future__ import annotations

import argparse
import os
import csv
import io
import json
import re
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("OMP_THREAD_LIMIT", "1")   # tesseract: one thread per page; the ingest pool already runs 4 pages in parallel
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from om import docparse, vdr_risk  # noqa: E402
from om.grid import ENGINE_VERSION, ExtractiveEngine, GridStore  # noqa: E402

OUT = ROOT / "evals" / "out"
TENK = ROOT / "evals" / "tenk"
VDR = ROOT / "evals" / "vdr50"
ODL = ROOT / "evals" / "odl_bench"
ODL_RAW = ROOT / "data" / "raw" / "odl_bench"
ODL_COMMIT = "7af1d8f4d0c09f51ea1a5c6ba5f66e993286d109"
DB = OUT / "vdr50.duckdb"
SCORECARD = ROOT / "scorecard.csv"
SHOWN = ("ok", "extracted")
TOL = 0.005

# ------------------------------------------------------------------------------------------------ scoring
UNIT_SCALE = {"usd_millions": 1e6, "usd_thousands": 1e3, "usd_billions": 1e9}
SUFFIX = {"million": 1e6, "mm": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "thousand": 1e3, "k": 1e3}
NUM_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*(million|billion|thousand|mm|bn|m|k)\b)?", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                                          "november", "december"))}
MON_ALT = "|".join(MONTHS)
DATE_RES = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(rf"\b({MON_ALT})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I), lambda m: (int(m[3]), MONTHS[m[1].lower()], int(m[2]))),
    (re.compile(rf"\b(\d{{1,2}})\s+({MON_ALT})\s+(\d{{4}})\b", re.I), lambda m: (int(m[3]), MONTHS[m[2].lower()], int(m[1]))),
]


def parse_numbers(text) -> list[float]:
    """Numbers in `text` in order, scaled by a trailing million / billion / thousand word when present."""
    out = []
    for m in NUM_RE.finditer(str(text or "")):
        v = float(m.group(1).replace(",", ""))
        if m.group(2):
            v *= SUFFIX[m.group(2).lower()]
        out.append(v)
    return out


def first_number_candidates(cell: dict) -> list[float]:
    """The cell's own value when numeric, else the first number printed in its answer. Unit words in `unit` rescale."""
    v = cell.get("value")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        base = float(v)
    else:
        nums = parse_numbers(cell.get("answer"))
        if not nums:
            return []
        base = nums[0]
    cands = [base]
    u = str(cell.get("unit") or "").lower()
    if "million" in u:
        cands.append(base * 1e6)
    if "thousand" in u:
        cands.append(base * 1e3)
    if "billion" in u:
        cands.append(base * 1e9)
    return cands


def num_match(cands, gold, unit=None, tol=TOL) -> bool:
    g = float(gold)
    golds = [g] + ([g * UNIT_SCALE[unit]] if unit in UNIT_SCALE else [])
    for c in cands:
        for gg in golds:
            if abs(c - gg) <= max(tol * abs(gg), 0.0051 if abs(gg) < 100 else 0):
                return True
    return False


def parse_dates(text) -> list[tuple]:
    hits = []
    for rx, fn in DATE_RES:
        for m in rx.finditer(str(text or "")):
            try:
                y, mo, d = fn(m)
                date(y, mo, d)
                hits.append((m.start(), (y, mo, d)))
            except ValueError:
                pass
    return [d for _, d in sorted(hits)]


def norm_text(s) -> str:
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    s = re.sub(r"[^\w&$%.]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip(" .")


def value_matches(gold: dict, cell: dict) -> bool:
    typ, ans = gold["type"], gold["gold_answer"]
    if typ in ("currency", "number", "percent"):
        return num_match(first_number_candidates(cell), ans, gold.get("unit"))
    if typ == "date":
        cands = [cell.get("value"), cell.get("answer")]
        for c in cands:
            ds = parse_dates(c)
            if ds:
                return ds[0] == (parse_dates(ans) or [None])[0]
        return False
    g = norm_text(ans)
    return bool(g) and g in norm_text(cell.get("answer"))


def quote_on_page(doc, cell) -> bool:
    q, pg = cell.get("exact_quote"), cell.get("page")
    if not q or pg is None:
        return False
    try:
        return docparse.locate(doc, int(pg), q) is not None
    except (KeyError, ValueError):
        return False


def score_cell(gold: dict, cell: dict | None, doc) -> dict:
    """One gold cell vs one grid cell. expect = found | not_found. Outcome: success | wrong_but_confident | missed;
    `silent` (an answer shown with no located quote) is an independent flag that must stay 0."""
    status = (cell or {}).get("status", "absent")
    shown = status in SHOWN
    r = {"cell_id": gold["cell_id"], "room": gold["room"], "expect": gold["expect"], "status": status, "shown": shown,
         "value_ok": None, "quote_ok": None, "page_ok": None, "silent": False, "outcome": None, "reason": ""}
    if gold["expect"] == "not_found":
        if status == "not_found":
            r["outcome"] = "success"
        elif shown:
            r.update(outcome="wrong_but_confident", reason=f"answer shown for a not-found cell: {str(cell.get('answer'))[:80]!r}")
        else:
            r.update(outcome="missed", reason=f"status {status}")
    else:
        if shown:
            r["value_ok"] = value_matches(gold, cell)
            r["quote_ok"] = quote_on_page(doc, cell)
            r["page_ok"] = cell.get("page") == gold["gold_page"]
            r["silent"] = not r["quote_ok"]
            if r["value_ok"] and r["quote_ok"]:
                r["outcome"] = "success"
            elif not r["value_ok"]:
                r.update(outcome="wrong_but_confident",
                         reason=f"gold {gold['gold_answer']!r} vs answer {str(cell.get('answer'))[:90]!r} (value {cell.get('value')!r}) p.{cell.get('page')}")
            else:
                r.update(outcome="missed", reason="value right but quote not located on the cited page")
        else:
            r.update(outcome="missed", reason=f"status {status} (gold p.{gold['gold_page']})")
    return r


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    c = lambda f: sum(1 for r in rows if f(r))  # noqa: E731
    found = [r for r in rows if r["expect"] == "found"]
    return {"n": n, "success": c(lambda r: r["outcome"] == "success"), "wrong_but_confident": c(lambda r: r["outcome"] == "wrong_but_confident"),
            "missed": c(lambda r: r["outcome"] == "missed"), "silent": c(lambda r: r["silent"]),
            "success_rate": round(c(lambda r: r["outcome"] == "success") / n, 4) if n else None,
            "n_found": len(found), "n_not_found": n - len(found),
            "value_accuracy": round(sum(1 for r in found if r["value_ok"]) / len(found), 4) if found else None,
            "quote_on_page": round(sum(1 for r in found if r["quote_ok"]) / len(found), 4) if found else None,
            "page_match": round(sum(1 for r in found if r["page_ok"]) / len(found), 4) if found else None}


# ------------------------------------------------------------------------------------------------ helpers
def say(*a):
    print(*a, flush=True)


def read_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


def tenk_questions():
    return [{"id": q["id"], "text": q["question"], "type": q["type"]} for q in json.loads((TENK / "questions.json").read_text())["questions"]]


def room_items():
    """(source_path, bytes, abs path) for the 50 documents; 10-Ks are read from evals/tenk/pdfs (referenced, sha256-checked)."""
    man = json.loads((VDR / "manifest.json").read_text())
    items = []
    for e in man["files"]:
        p = ROOT / e["ref"]
        data = p.read_bytes()
        import hashlib
        if hashlib.sha256(data).hexdigest() != e["sha256"]:
            raise SystemExit(f"sha256 mismatch for {e['path']}; rerun scripts/build_vdr50.py")
        items.append((e["path"], data, p, e))
    return man, items


def telemetry_docs(store, files):
    ocr_pages = arabic_pages = pages = 0
    for f in files:
        if f.get("doc_id") is None or f["status"] == "failed":
            continue
        d = store.document(f["doc_id"])
        for p in d.pages:
            pages += 1
            if any(getattr(w, "ocr", False) for ln in p.lines for w in ln.words):
                ocr_pages += 1
            if re.search(r"[؀-ۿ]", p.raw_text or ""):
                arabic_pages += 1
    return pages, ocr_pages, arabic_pages


def new_store(parser="pdfdoc", path=DB):
    return GridStore(str(path), parser_backend=parser)


def ensure_grid(store, name, doc_ids, questions):
    for g in store.grid_names():
        if g["name"] == name:
            return g["grid_id"]
    return store.create_grid(name, doc_ids, questions)


# ------------------------------------------------------------------------------------------------ the run
def run_grid(store, gid, label, tel):
    est_ev, done = None, None
    t0 = time.perf_counter()
    for ev in store.run_stream(gid, ExtractiveEngine(), workers=8):
        if ev["type"] == "estimate":
            est_ev = ev
            say(f"  [{label}] ESTIMATE: {ev['pending_cells']} cells, {ev['est_input_tokens']} tokens in, "
                f"${ev['est_cost_usd']:.4f} (extractive engine: no model calls)")
        elif ev["type"] == "done":
            done = ev
    wall = time.perf_counter() - t0
    tel[label] = {"estimate": {k: v for k, v in (est_ev or {}).items() if k != "type"}, "wall_clock_s": round(wall, 3),
                  "elapsed_s": done["elapsed_s"], "first_cell_s": done["first_cell_s"], "tokens_in": done["tokens_in"],
                  "tokens_out": done["tokens_out"], "cost_usd": done["actual_cost_usd"], "stats": done["stats"], "skipped_unchanged": done["skipped"]}
    return done


def llm_estimate(store, gid):
    """What a live LLM first pass would cost, by the engine's own estimator. An ESTIMATE, never a measurement."""
    try:
        from om.grid import LLMEngine
        from src.harness.adapter import Adapter
        eng = LLMEngine(Adapter("https://llm.invalid/v1", None, "auto", mode="replay"))
        e = store.estimate(gid, engine=eng)
        return {k: v for k, v in e.items() if k != "type"}
    except Exception as ex:      # never block the eval on the estimator
        return {"error": f"{type(ex).__name__}: {str(ex)[:120]}"}


def score_room(store, grid_id, golds, doc_by_sha, label):
    cells = {(c["doc_id"], c["question_id"]): c for c in store.cells(grid_id)}
    rows = []
    for g in golds:
        did = doc_by_sha[g["doc_sha256"]]
        rows.append(score_cell(g, cells.get((did, g["question_id"])), store.document(did)))
    return rows


def fp_classes(fps):
    """Why each unmatched in-scope finding is wrong (checked by hand against the room: the synthetic room has no other real gaps/clauses)."""
    out = {"spurious_period (year < 2000 parsed from 10-K text)": 0, "conflicting_figure on the real 10-Ks (mis-paired metrics)": 0,
           "clause finding on a synthetic doc without that clause": 0, "missing_document for a category the room holds": 0, "other": 0}
    for f in fps:
        t = f["type"]
        if t == "missing_period" and re.search(r"FY(1\d{3})", f["title"]):
            out["spurious_period (year < 2000 parsed from 10-K text)"] += 1
        elif t == "conflicting_figure" and "10-K" in str(f.get("doc_name")):
            out["conflicting_figure on the real 10-Ks (mis-paired metrics)"] += 1
        elif t in ("change_of_control", "covenant", "mfn", "exclusivity"):
            out["clause finding on a synthetic doc without that clause"] += 1
        elif t == "missing_document":
            out["missing_document for a category the room holds"] += 1
        else:
            out["other"] += 1
    return out


def risk_eval(store, files, items, tel):
    docs = []
    for (sp, _data, p, e), f in zip(items, files):
        d = store.document(f["doc_id"])
        pages = ["\n".join(ln.text for ln in pg.lines) for pg in d.pages]
        docs.append({"doc_id": f["doc_id"], "name": sp, "pages": pages, "pdf": str(p)})
    t0 = time.perf_counter()
    rep = vdr_risk.scan_documents(docs)
    tel["risk_s"] = round(time.perf_counter() - t0, 3)
    gold = json.loads((VDR / "risk_gold.json").read_text())
    synth = {d["name"] for d in docs if not d["name"].startswith("01 Financials/10-K/")}
    CL = ("change_of_control", "covenant", "mfn", "exclusivity")
    label_of = {"ip_schedule": "IP schedule", "litigation": "Litigation"}
    fnd = []
    for f in rep["findings"]:
        t = f["type"]
        inscope = (t in CL and f.get("doc_name") in synth) or t in ("missing_period", "missing_document", "conflicting_figure")
        if inscope:
            fnd.append(f)

    def matches(g, f):
        if g.get("decoy"):
            return False
        if g["type"] != f["type"]:
            return False
        t = g["type"]
        if t == "missing_period":
            return g["label"] in f["title"]
        if t == "missing_document":
            return label_of.get(g["label"], g["label"]).lower() in f["title"].lower()
        if t == "conflicting_figure":
            docs_f = {f.get("doc_name")} | {r.get("doc_name") for r in f.get("related", [])}
            return g["doc"] in docs_f
        return f.get("doc_name") == g["doc"]

    recs = [g for g in gold if not g.get("decoy")]
    hit = lambda g: any(matches(g, f) for f in fnd)  # noqa: E731
    # one conflict gold per metric pair (base + conflict docs): count the pair once
    pair = [g for g in recs if g["type"] != "conflicting_figure"] + [g for g in recs if g["type"] == "conflicting_figure" and g.get("role") == "conflict"]
    detail, tp_g = [], 0
    for g in pair:
        ok = hit(g)
        tp_g += ok
        detail.append({"type": g["type"], "doc": g.get("doc"), "label": g.get("label"), "lang": g.get("language"), "scanned": g.get("scanned"),
                       "found": ok})
    tp_f = [f for f in fnd if any(matches(g, f) for g in recs)]
    fps = [f for f in fnd if f not in tp_f]
    decoy_hits = [f for f in fnd if any(g.get("decoy") and g["doc"] == f.get("doc_name") and g["type"] == f["type"] for g in gold)]

    def sub(pred):
        d = [x for x in detail if pred(x)]
        return {"gold": len(d), "found": sum(x["found"] for x in d)}
    res = {"recall": round(tp_g / len(pair), 4), "precision": round(len(tp_f) / len(fnd), 4) if fnd else None, "gold": len(pair), "gold_found": tp_g,
           "findings_in_scope": len(fnd), "findings_matching_gold": len(tp_f), "false_positives": [
               {"type": f["type"], "doc": f.get("doc_name"), "page": f.get("page"), "title": f["title"], "quote": (f.get("quote") or "")[:100]} for f in fps],
           "decoy_flagged": len(decoy_hits),
           "false_positive_classes": fp_classes(fps), "legit_extra_findings": 0,
           "false_positive_counts": {t: sum(1 for f in fps if f["type"] == t) for t in sorted({f["type"] for f in fps})}, "by_type": {t: sub(lambda x, t=t: x["type"] == t) for t in sorted({x["type"] for x in detail})},
           "arabic": sub(lambda x: x["lang"] == "ar"), "scanned": sub(lambda x: bool(x["scanned"])), "missed": [x for x in detail if not x["found"]],
           "findings_total_all_docs": len(rep["findings"]), "summary": rep["summary"]}
    return res


# ------------------------------------------------------------------------------------------------ opendataloader-bench
def pages_to_md(parsed) -> str:
    out = []
    for pg in parsed.pages:
        for b in pg.blocks:
            if b.kind in ("header", "footer") or not b.text.strip():
                continue
            if b.kind == "heading":
                out.append("## " + " ".join(b.text.split()))
            elif b.kind == "table":
                rows = [re.split(r"\s{2,}|\t|\|", ln.strip().strip("|")) for ln in b.text.split("\n") if ln.strip()]
                w = max(len(r) for r in rows) if rows else 0
                if w >= 2:
                    rows = [[c.strip() for c in r] + [""] * (w - len(r)) for r in rows]
                    out.append("| " + " | ".join(rows[0]) + " |\n|" + "---|" * w + "\n" + "\n".join("| " + " | ".join(r) + " |" for r in rows[1:]))
                else:
                    out.append(b.text)
            else:
                out.append(b.text)
    return "\n\n".join(out)


def odl_bench(offline, docling_n, budget_s=900):
    res_path = ODL / "results.json"
    if offline:
        return json.loads(res_path.read_text()) if res_path.exists() else {"status": "not run: --offline and no cached evals/odl_bench/results.json"}
    ODL.mkdir(parents=True, exist_ok=True)
    if not (ODL_RAW / "pdfs").is_dir():
        try:
            ODL_RAW.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["git", "clone", "--depth", "1", "https://github.com/opendataloader-project/opendataloader-bench", str(ODL_RAW)],
                               capture_output=True, text=True, timeout=240)
            if r.returncode != 0:
                return {"status": "not run: clone failed (" + (r.stderr.strip().splitlines() or ["?"])[-1][:120] + ")"}
        except Exception as e:
            return {"status": f"not run: clone failed ({type(e).__name__})"}
    head = subprocess.run(["git", "-C", str(ODL_RAW), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != ODL_COMMIT:
        subprocess.run(["git", "-C", str(ODL_RAW), "fetch", "--depth", "1", "origin", ODL_COMMIT], capture_output=True, text=True, timeout=240)
        r = subprocess.run(["git", "-C", str(ODL_RAW), "checkout", "-q", ODL_COMMIT], capture_output=True, text=True)
        head = subprocess.run(["git", "-C", str(ODL_RAW), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if head != ODL_COMMIT:
            return {"status": f"not run: could not pin commit {ODL_COMMIT[:12]} (got {head[:12]})"}
    try:
        import apted, rapidfuzz, bs4, lxml  # noqa: F401, E401
    except ImportError as e:
        return {"status": f"not run: evaluator dependency missing ({e.name}); pip install apted rapidfuzz beautifulsoup4 lxml"}
    pdfs = sorted((ODL_RAW / "pdfs").glob("*.pdf"))
    gt = ODL_RAW / "ground-truth" / "markdown"
    pred_root = ODL_RAW / "pred_acretia"
    shutil.rmtree(pred_root, ignore_errors=True)
    res = {"status": "run", "commit": ODL_COMMIT, "docs_total": len(pdfs), "engines": {}}

    def run_engine(name, backend, subset, ocr):
        md_dir = pred_root / name / "markdown"
        md_dir.mkdir(parents=True, exist_ok=True)
        sub_gt = ODL_RAW / f"subset_gt_{name}"
        shutil.rmtree(sub_gt, ignore_errors=True)
        sub_gt.mkdir()
        t0, pages, done, fails = time.perf_counter(), 0, 0, 0
        for p in subset:
            if time.perf_counter() - t0 > budget_s:
                break
            try:
                parsed = docparse.parse(p.read_bytes(), backend=backend, ocr=ocr)
                pages += len(parsed.pages)
                (md_dir / (p.stem + ".md")).write_text(pages_to_md(parsed), encoding="utf-8")
            except Exception:
                fails += 1
                (md_dir / (p.stem + ".md")).write_text("", encoding="utf-8")
            done += 1
            (sub_gt / (p.stem + ".md")).symlink_to(gt / (p.stem + ".md"))
        el = time.perf_counter() - t0
        cmd = ["python3", "src/evaluator.py", "--ground-truth-dir", sub_gt.name, "--prediction-root", pred_root.name, "--engine", name, "--log-level", "WARNING"]
        r = subprocess.run(cmd, cwd=ODL_RAW, capture_output=True, text=True, timeout=1800)
        ev = pred_root / name / "evaluation.json"
        if not ev.exists():
            return {"status": "evaluator failed: " + r.stderr[-200:]}
        sc = json.loads(ev.read_text()).get("metrics", json.loads(ev.read_text())).get("score", json.loads(ev.read_text()).get("score"))
        return {"docs": done, "pages": pages, "parse_failures": fails, "seconds": round(el, 2), "s_per_page": round(el / pages, 4) if pages else None,
                "score": {k: (round(v, 4) if v is not None else None) for k, v in sc.items()}, "backend": backend, "ocr": ocr,
                "command": "cd data/raw/odl_bench && " + " ".join(cmd)}
    res["engines"]["acretia-pdfdoc"] = run_engine("acretia-pdfdoc", "pdfdoc", pdfs, "off")
    if docling_n and docparse.docling_available():
        sub = pdfs[:docling_n]
        res["engines"][f"acretia-docling-first{docling_n}"] = run_engine(f"acretia-docling-first{docling_n}", "docling", sub, "off")
        res["engines"][f"acretia-pdfdoc-first{docling_n}"] = run_engine(f"acretia-pdfdoc-first{docling_n}", "pdfdoc", sub, "off")
    res_path.write_text(json.dumps(res, indent=1) + "\n")
    return res


# ------------------------------------------------------------------------------------------------ outputs
def update_scorecard(rows):
    """Replace only the rows whose stage is S5. Works on bytes: other sessions' rows (the file mixes CRLF/LF) stay byte-identical;
    new rows are appended with a plain LF."""
    head = b"stage,eval,n,score,notes\n"
    raw = SCORECARD.read_bytes() if SCORECARD.exists() else head
    lines = raw.splitlines(keepends=True)
    keep = [l for l in lines if not l.startswith(b"S5,")]
    if keep and not keep[-1].endswith(b"\n"):
        keep[-1] += b"\r\n" if keep[-1].endswith(b"\r") else b"\n"
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in rows:
        w.writerow(r)
    SCORECARD.write_bytes(b"".join(keep) + buf.getvalue().encode("utf-8"))


def pct(x):
    return "" if x is None else f"{x:.3f}"


def write_report(path, data):
    L = ["# S5.4b eval report", "", f"Generated {data['generated']} (mode: {data['mode']}). Engine: `ExtractiveEngine` {ENGINE_VERSION} (deterministic, offline; no model calls).",
         "LLM engine: not run live (D-021: no endpoint/keys in this session); no replay fixtures exist for these rooms.", ""]
    t = data["tenk"]
    L += ["## 10-K QA (10 real filings x 10 questions)", "", "| metric | value |", "|---|---|",
          f"| cells | {t['n']} |", f"| value accuracy (target >= 0.70) | {pct(t['value_accuracy'])} |", f"| quote located on cited page | {pct(t['quote_on_page'])} |",
          f"| cited page == gold page | {pct(t['page_match'])} |", f"| success (value right and quote on page) | {pct(t['success_rate'])} |",
          f"| wrong_but_confident / missed / silent | {t['wrong_but_confident']} / {t['missed']} / {t['silent']} |", ""]
    L += ["By question:", "", "| question | n | value ok | quote on page | page match |", "|---|---|---|---|---|"]
    for q, s in data["tenk_by_q"].items():
        L.append(f"| {q} | {s['n']} | {s['value_ok']} | {s['quote_ok']} | {s['page_ok']} |")
    L += ["", "## Reliability (D-032): all gold cells", "", "| room | n | found/not_found | success | success % | wrong_but_confident | missed | silent |", "|---|---|---|---|---|---|---|---|"]
    for room, s in data["reliability"].items():
        L.append(f"| {room} | {s['n']} | {s['n_found']}/{s['n_not_found']} | {s['success']} | {100 * s['success_rate']:.1f} | {s['wrong_but_confident']} | {s['missed']} | {s['silent']} |")
    L += ["", "## VDR first pass (50 documents, pdfdoc parser)", ""]
    tel = data["telemetry"]
    if tel:
        L += ["| item | value |", "|---|---|"]
        for k in ("docs", "pages", "ocr_pages", "arabic_pages", "ingest_ok", "ingest_failed", "ingest_s", "grid_s", "risk_s", "total_s", "first_cell_s", "cells",
                  "tokens_in", "tokens_out", "cost_usd", "completeness_min", "completeness_median"):
            L.append(f"| {k} | {tel.get(k)} |")
        L.append(f"| cost estimate before run | {json.dumps(tel.get('estimate'))} |")
        L.append(f"| live-LLM first pass ESTIMATE (not measured) | {json.dumps(tel.get('llm_estimate'))} |")
    r = data["risk"]
    L += ["", "## Risk detector (vdr_risk.scan_documents)", "", f"recall {r['recall']} ({r['gold_found']}/{r['gold']}); precision {r['precision']} "
          f"({r['findings_matching_gold']}/{r['findings_in_scope']} in-scope findings; legitimate extra findings: {r['legit_extra_findings']}); false-positive classes {json.dumps(r['false_positive_classes'])}; decoys flagged: {r['decoy_flagged']}; Arabic recall {r['arabic']}; scanned recall {r['scanned']}", "",
          "| type | gold | found |", "|---|---|---|"]
    for k, v in r["by_type"].items():
        L.append(f"| {k} | {v['gold']} | {v['found']} |")
    L += ["", "Missed:"] + [f"- {m['type']} {m.get('doc') or m.get('label')}" for m in r["missed"]]
    L += ["", f"False positives (in scope, no matching gold) by type: {json.dumps(r['false_positive_counts'])}; first 40 non-period ones:"] + [f"- {f['type']} | {f['doc']} p.{f['page']} | {f['title']} | {f['quote']}" for f in [x for x in r["false_positives"] if x["type"] != "missing_period"][:40]]
    L += ["", "Spurious missing_period titles: " + ", ".join(sorted({f["title"] for f in r["false_positives"] if f["type"] == "missing_period"})[:12]) + " ..."]
    o = data["odl"]
    L += ["", "## opendataloader-bench", "", json.dumps(o, indent=1)[:3000]]
    if data.get("docling_tenk"):
        L += ["", "## docling on the 10 10-Ks", "", json.dumps(data["docling_tenk"], indent=1)[:2500]]
    L += ["", "## Failures by cell id", ""]
    for room, fl in data["failures"].items():
        L += [f"### {room} ({len(fl)})", ""] + [f"- `{x['cell_id']}` [{x['outcome']}] {x['reason']}" for x in fl] + [""]
    Path(path).write_text("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="reuse the cached DB; no ingest, no network, no docling")
    ap.add_argument("--fresh", action="store_true", help="delete the cache DB first (timed first pass)")
    ap.add_argument("--docling", action="store_true", help="also ingest + score the 10 10-Ks with docling (slow, ~6 s/page)")
    ap.add_argument("--no-odl", action="store_true")
    ap.add_argument("--odl-docling", type=int, default=6)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    man, items = room_items()
    if a.offline and not DB.exists():
        raise SystemExit("--offline needs evals/out/vdr50.duckdb from a previous run")
    if a.fresh and not a.offline:
        for p in OUT.glob("vdr50.duckdb*"):
            p.unlink()
    cached = DB.exists()
    store = new_store()
    tel_path = VDR / "telemetry.json"
    tel = {}
    T0 = time.perf_counter()
    # ---- ingest
    say(f"ingesting {len(items)} documents (parser pdfdoc){' [cached DB]' if cached else ''} ...")
    t0 = time.perf_counter()
    ing = store.add_documents([(sp, data) for sp, data, _p, _e in items], workers=4)
    ingest_s = time.perf_counter() - t0
    files = ing["files"]
    for f in files:
        say(f"  {f['status']:9s} {f['pages']:3d}p  {f['source_path']}")
    if ing["failed"]:
        say("ALERTS:\n  " + "\n  ".join(ing["alerts"]))
    doc_by_sha = {e["sha256"]: f["doc_id"] for (_sp, _d, _p, e), f in zip(items, files)}
    doc_ids = [f["doc_id"] for f in files]
    # ---- grids
    gv = ensure_grid(store, "vdr50-first-pass", doc_ids, vdr_questions(man))
    tenk_man = json.loads((TENK / "manifest.json").read_text())
    tenk_sha = {f["ticker"]: f["sha256"] for f in tenk_man["filings"]}
    tenk_ids = [doc_by_sha[tenk_sha[f["ticker"]]] for f in tenk_man["filings"]]
    gt = ensure_grid(store, "tenk-qa", tenk_ids, tenk_questions())
    say("VDR first pass:")
    t0 = time.perf_counter()
    run_grid(store, gv, "vdr_grid", tel)
    grid_s = time.perf_counter() - t0
    say("10-K QA:")
    run_grid(store, gt, "tenk_grid", tel)
    say("extended diligence question set (100 questions x 50 documents; ungraded breadth/telemetry grid):")
    ge = ensure_grid(store, "vdr50-extended-100q", doc_ids, extended_questions())
    run_grid(store, ge, "extended_grid", tel)
    # ---- score
    golds_t = read_jsonl(TENK / "gold.jsonl")
    for g in golds_t:
        g.update(room="tenk", expect="found", doc_sha256=tenk_sha[g["ticker"]])
    golds_v = read_jsonl(VDR / "gold.jsonl")
    rows_t = score_room(store, gt, golds_t, doc_by_sha, "tenk")
    rows_v = score_room(store, gv, golds_v, doc_by_sha, "vdr")
    allrows = rows_t + rows_v
    by_room = {}
    for room in ("tenk", "vdr_en", "vdr_scanned_arabic"):
        by_room[room] = summarise([r for r in allrows if r["room"] == room])
    by_room["ALL"] = summarise(allrows)
    by_q = {}
    for g, r in zip(golds_t, rows_t):
        d = by_q.setdefault(g["question_id"], {"n": 0, "value_ok": 0, "quote_ok": 0, "page_ok": 0})
        d["n"] += 1
        d["value_ok"] += bool(r["value_ok"])
        d["quote_ok"] += bool(r["quote_ok"])
        d["page_ok"] += bool(r["page_ok"])
    failures = {room: [r for r in allrows if r["room"] == room and (r["outcome"] != "success" or r["silent"])] for room in ("tenk", "vdr_en", "vdr_scanned_arabic")}
    # ---- risk
    say("risk scan ...")
    risk = risk_eval(store, files, items, tel)
    total_s = time.perf_counter() - T0
    pages, ocr_pages, arabic_pages = telemetry_docs(store, files)
    comp = [f["completeness_min"] for f in files if f.get("completeness_min") is not None]
    ok_files = [f for f in files if f["status"] in ("ok", "duplicate")]
    first = {"docs": len(items), "pages": pages, "ocr_pages": ocr_pages, "arabic_pages": arabic_pages, "ingest_ok": ing["ok"] + ing["duplicates"], "ingest_failed": ing["failed"],
             "cells": tel["vdr_grid"]["stats"] and sum(tel["vdr_grid"]["stats"].values()), "first_cell_s": tel["vdr_grid"]["first_cell_s"],
             "tokens_in": tel["vdr_grid"]["tokens_in"], "tokens_out": tel["vdr_grid"]["tokens_out"], "cost_usd": tel["vdr_grid"]["cost_usd"],
             "estimate": tel["vdr_grid"]["estimate"], "llm_estimate": llm_estimate(store, gv), "completeness_min": round(min(comp), 4) if comp else None,
             "completeness_median": round(statistics.median(comp), 4) if comp else None, "risk_s": tel["risk_s"],
             "per_file": [{k: f[k] for k in ("source_path", "status", "pages", "completeness_min", "seconds")} for f in files]}
    if not cached or a.fresh:
        first.update(parser="pdfdoc", engine_version=ENGINE_VERSION, ingest_s=round(ingest_s, 3), grid_s=round(grid_s, 3), total_s=round(total_s, 3),
                     run_mode="extractive, pdfdoc parser, cold cache", cpu_note="4 vCPU cloud container; timings are this run only")
        tel_path.write_text(json.dumps(first, indent=1, ensure_ascii=False) + "\n")
    else:
        first = json.loads(tel_path.read_text()) if tel_path.exists() else first
    # ---- docling on 10-Ks (optional)
    dtk = None
    if a.docling and not a.offline:
        dtk = docling_tenk(items, tenk_sha, golds_t)
        (VDR / "telemetry_docling_tenk.json").write_text(json.dumps(dtk, indent=1) + "\n")
    elif (VDR / "telemetry_docling_tenk.json").exists():
        dtk = json.loads((VDR / "telemetry_docling_tenk.json").read_text())
    # ---- opendataloader-bench
    odl = {"status": "not run: --no-odl"} if a.no_odl else odl_bench(a.offline, a.odl_docling)
    # ---- outputs
    t = by_room["tenk"]
    mode = "offline (cached DB)" if a.offline else ("fresh" if (a.fresh or not cached) else "incremental")
    data = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "mode": mode, "tenk": t, "tenk_by_q": by_q, "reliability": by_room, "telemetry": first,
            "risk": risk, "odl": odl, "docling_tenk": dtk, "failures": failures}
    write_report(OUT / "s5_report.md", data)
    (OUT / "s5_results.json").write_text(json.dumps({k: data[k] for k in ("tenk", "tenk_by_q", "reliability", "risk")} | {"cells": [
        {k: r[k] for k in ("cell_id", "room", "expect", "status", "value_ok", "quote_ok", "page_ok", "silent", "outcome")} for r in allrows]},
        indent=1, sort_keys=True, default=str) + "\n")
    scorecard_rows(by_room, first, risk, odl, dtk, t)
    say("\n=== S5 results ===")
    say(f"10-K QA: value accuracy {pct(t['value_accuracy'])} (target 0.70), quote on page {pct(t['quote_on_page'])}, page match {pct(t['page_match'])}")
    for room, s in by_room.items():
        say(f"reliability {room:20s} n={s['n']:3d} success {100 * s['success_rate']:.1f}% wrong_but_confident={s['wrong_but_confident']} missed={s['missed']} silent={s['silent']}")
    say(f"risk: recall {risk['recall']} precision {risk['precision']} (decoys flagged {risk['decoy_flagged']}; arabic {risk['arabic']}; scanned {risk['scanned']})")
    say(f"VDR50 telemetry: ingest {first.get('ingest_s')}s grid {first.get('grid_s')}s risk {first.get('risk_s')}s total {first.get('total_s')}s first_cell {first.get('first_cell_s')}s")
    say(f"odl-bench: {odl.get('status')}")
    store.close()
    return 0


def extended_questions():
    """100 distinct diligence questions (30 topics x phrasings). No gold: they exercise the engine at breadth and feed the telemetry."""
    topics = ["change of control", "assignment", "exclusivity", "non-compete", "most favoured nation pricing", "governing law", "termination for convenience",
              "notice period", "term and renewal", "liability cap", "indemnity", "confidentiality", "payment terms", "interest rate", "leverage ratio",
              "interest coverage ratio", "security and collateral", "events of default", "auditor", "revenue", "net income", "total assets", "cash balance",
              "employee headcount", "annual rent", "insurance cover", "data protection", "force majeure", "dispute resolution", "key person"]
    phr = ["What does the document say about {t}?", "What is the amount or level of {t}?", "Which party benefits from {t}?", "Is there any restriction relating to {t}?"]
    qs = [{"id": f"e{i + 1:03d}", "text": phr[i // len(topics)].format(t=topics[i % len(topics)]), "type": "text"} for i in range(len(topics) * len(phr))]
    return qs[:100]


def vdr_questions(man):
    return [{"id": q["id"], "text": q["text"], "type": q["type"]} for q in man["questions"]]


def docling_tenk(items, tenk_sha, golds_t):
    """Separate store, docling parser, the 10 10-Ks only. Everything recorded is measured in this run."""
    p = OUT / "tenk_docling.duckdb"
    prev_path = VDR / "telemetry_docling_tenk.json"
    prev = json.loads(prev_path.read_text()) if (p.exists() and prev_path.exists()) else None   # keep the measured parse timing; rescore only
    if prev is None:
        for x in OUT.glob("tenk_docling.duckdb*"):
            x.unlink()
    st = new_store("docling", p)
    sel = [(sp, d) for sp, d, _p, e in items if e["room"] == "tenk"]
    t0 = time.perf_counter()
    ing = st.add_documents(sel, workers=2)
    ing_s = time.perf_counter() - t0
    by_sha = {e["sha256"]: f["doc_id"] for (_sp, _d, _p, e), f in zip([i for i in items if i[3]["room"] == "tenk"], ing["files"])}
    man = json.loads((TENK / "manifest.json").read_text())
    gid = ensure_grid(st, "tenk-qa-docling", [by_sha[f["sha256"]] for f in man["filings"]], tenk_questions())
    tel = {}
    run_grid(st, gid, "g", tel)
    rows = score_room(st, gid, golds_t, by_sha, "tenk")
    s = summarise(rows)
    pages = sum(f["pages"] for f in ing["files"])
    out = {"parser": "docling", "docs": len(sel), "ingest_ok": ing["ok"] + ing["duplicates"], "ingest_failed": ing["failed"], "pages": pages, "ingest_s": round(ing_s, 1),
           "s_per_page": round(ing_s / pages, 2) if pages else None, "workers": 2, "engine_version": ENGINE_VERSION, "grid_first_cell_s": tel["g"]["first_cell_s"], "score": s,
           "backends": sorted({st.document(f["doc_id"]).backend for f in ing["files"] if f["doc_id"]})}
    st.close()
    if prev:
        out.update({k: prev[k] for k in ("ingest_s", "s_per_page", "workers")}, ingest_timing_from="first docling ingest (parse cached since)")
    return out


def scorecard_rows(by_room, first, risk, odl, dtk, t):
    def row(ev, n, score, notes):
        return ["S5", ev, "" if n is None else n, "" if score is None else score, notes]
    rm = f"run_mode=extractive offline; engine {ENGINE_VERSION}"
    rows = [row("tenk_qa_accuracy", t["n"], f"{t['value_accuracy']:.3f}", f"{rm}; value within 0.5% / date equal / text contained; target >= 0.70; 10 real 10-Ks x 10 q"),
            row("tenk_qa_quote_on_page", t["n"], f"{t['quote_on_page']:.3f}", f"{rm}; exact quote relocated by om.pdfdoc on the cited page"),
            row("tenk_qa_page_match", t["n"], f"{t['page_match']:.3f}", f"{rm}; cited page == gold page"),
            row("tenk_qa_llm", t["n"], None, "run_mode=not run live (no endpoint, D-021); no replay fixtures for this room")]
    for room, s in by_room.items():
        rows.append(row(f"reliability_success_{room}", s["n"], f"{s['success_rate']:.3f}",
                        f"{rm}; wrong_but_confident={s['wrong_but_confident']} missed={s['missed']} silent={s['silent']}; D-032 target >= 0.97"))
    rows.append(row("reliability_wrong_but_confident", by_room["ALL"]["n"], by_room["ALL"]["wrong_but_confident"], f"{rm}; count over all gold cells"))
    rows.append(row("reliability_silent", by_room["ALL"]["n"], by_room["ALL"]["silent"], f"{rm}; answer shown without a located quote; must be 0"))
    rows.append(row("reliability_llm", by_room["ALL"]["n"], None, "run_mode=not run live (no endpoint, D-021)"))
    rows += [row("vdr50_total_s", first.get("docs"), first.get("total_s"), f"run_mode=extractive; pdfdoc parser; cold cache; ingest {first.get('ingest_s')}s grid {first.get('grid_s')}s risk {first.get('risk_s')}s"),
             row("vdr50_first_cell_s", first.get("cells"), first.get("first_cell_s"), "run_mode=extractive; seconds to the first completed cell of the 650-cell grid"),
             row("vdr50_cost_usd", first.get("cells"), first.get("cost_usd"), "run_mode=extractive; no model calls; live-LLM cost is an estimate in evals/vdr50/telemetry.json"),
             row("vdr50_completeness_min", first.get("docs"), first.get("completeness_min"), f"pdfdoc; median {first.get('completeness_median')}; OCR pages {first.get('ocr_pages')}; Arabic pages {first.get('arabic_pages')}"),
             row("risk_recall", risk["gold"], f"{risk['recall']:.3f}", f"run_mode=deterministic om.vdr_risk; planted gaps/clauses; Arabic {risk['arabic']['found']}/{risk['arabic']['gold']}; scanned {risk['scanned']['found']}/{risk['scanned']['gold']}"),
             row("risk_precision", risk["findings_in_scope"], None if risk["precision"] is None else f"{risk['precision']:.3f}", f"run_mode=deterministic; decoys flagged={risk['decoy_flagged']}; clause findings on synthetic docs only")]
    if dtk:
        rows.append(row("tenk_qa_accuracy_docling", dtk["score"]["n"], f"{dtk['score']['value_accuracy']:.3f}", f"run_mode=extractive over docling parse; {dtk['s_per_page']} s/page ingest measured on this CPU"))
    if odl.get("status") == "run":
        for name, e in odl["engines"].items():
            if "score" not in e:
                rows.append(row(f"odl_bench_{name}", None, None, "not run: " + str(e.get("status"))))
                continue
            s = e["score"]
            rows.append(row(f"odl_bench_{name}", e["docs"], s.get("overall_mean") and f"{s['overall_mean']:.3f}",
                            f"opendataloader-bench @{ODL_COMMIT[:7]} evaluator run in place; nid {s.get('nid_mean')} teds {s.get('teds_mean')} mhs {s.get('mhs_mean')}; {e['s_per_page']} s/page; ocr={e['ocr']}"))
    else:
        rows.append(row("odl_bench", None, None, odl.get("status", "not run")))
    update_scorecard(rows)


if __name__ == "__main__":
    sys.exit(main())
