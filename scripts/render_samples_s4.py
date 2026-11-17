#!/usr/bin/env python3
"""S4.10: build real sample workbooks from SEC data and render every sheet to PNG for review.

Writes docs/samples/s4/<name>.xlsx, png/<name>/page-NN.png, README.md and manifest.json.
Needs SEC_USER_AGENT for live requests (cache under data/raw/sec), LibreOffice and poppler.
Re-running overwrites; the model store is private to the run (temp dir).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("SEC_USER_AGENT", "Acretia hamza@meshpool.ai")

from om import modelapi, statements as stm  # noqa: E402

OUT = ROOT / "docs" / "samples" / "s4"
MAX_PAGES = 12
SAMPLES = [  # name, kind, tickers
    ("aapl_three_statement_dcf", "dcf", ["AAPL"]),
    ("ko_three_statement_dcf", "dcf", ["KO"]),
    ("hd_lbo", "lbo", ["HD"]),
    ("pg_ko_merger", "merger", ["PG", "KO"]),
    ("ko_comps", "comps", ["KO", "PEP", "PG", "MDLZ", "CL"]),
]


def render(xlsx_path: Path, pngdir: Path, work: Path) -> list[dict]:
    profile = work / "lo-profile"
    subprocess.run(["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf",
                    "--outdir", str(work), str(xlsx_path)], check=True, capture_output=True, timeout=300)
    pdf = work / (xlsx_path.stem + ".pdf")
    if pngdir.exists():
        shutil.rmtree(pngdir)
    pngdir.mkdir(parents=True)
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    total = int(next(l.split()[1] for l in info.splitlines() if l.startswith("Pages:")))
    last = min(total, MAX_PAGES)
    subprocess.run(["pdftoppm", "-png", "-r", "110", "-scale-to", "1600", "-f", "1", "-l", str(last), str(pdf), str(pngdir / "page")],
                   check=True, capture_output=True, timeout=300)
    pages = []
    for p in sorted(pngdir.glob("page-*.png")):
        n = int(p.stem.split("-")[1])
        new = pngdir / f"page-{n:02d}.png"
        if new != p:
            p.rename(new)
        txt = subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
        lines = [l.strip() for l in txt.splitlines() if l.strip()]
        pages.append({"png": f"png/{pngdir.name}/page-{n:02d}.png", "n": n, "pdf_pages": total,
                      "shows": " | ".join(" ".join(l.split()) for l in lines[:3])[:160] or "(no text)"})
    return pages


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="s4samples-"))
    os.environ["ACRETIA_MODELS_DIR"] = str(work / "models")
    cache: dict[str, dict] = {}

    def fetch(t):
        cache[t] = modelapi.default_fetch(t)
        return cache[t]

    manifest = []
    for name, kind, tickers in SAMPLES:
        print(f"== {name}", flush=True)
        t0 = time.time()
        r = modelapi.build_model(kind, tickers, fetch=fetch)
        secs = round(time.time() - t0, 1)
        data = modelapi.get_bytes(r["model_id"])
        xp = OUT / f"{name}.xlsx"
        xp.write_bytes(data)
        t = tickers[0]
        fl = stm.build(cache[t], t).filings[-1]
        pages = render(xp, OUT / "png" / name, work)
        manifest.append({
            "name": name, "kind": kind, "tickers": tickers,
            "as_of_filing": {"ticker": t, "form": fl["form"], "fiscal_year_end": fl["end"], "filed": fl["filed"], "accession": fl["accn"]},
            "market": {k: {"source": v.get("source"), "price": v.get("price")} for k, v in (r.get("markets") or {}).items()},
            "modelcheck_score": r["grade"]["score"], "production_ready": r["grade"]["production_ready"],
            "validate_passed": r["validate"]["passed"], "validate_critical": r["validate"]["critical"],
            "three_engine_agree": r["engines"]["agree"], "compared_cells": r["engines"]["compared_cells"],
            "build_seconds": secs, "bytes": len(data), "pdf_pages": pages[0]["pdf_pages"] if pages else 0,
            "pngs": [{k: p[k] for k in ("png", "shows")} for p in pages],
        })
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    md = ["# S4 sample workbooks", "",
          "Built from SEC companyfacts through `om.modelapi.build_model` (market prices: public-float proxy via `om.market.resolve`, cited in each workbook).",
          "Rendered with LibreOffice headless (workbook print setup applies) and `pdftoppm -r 110`; at most 12 pages per model, Cover first.",
          "Regenerate: `python3 scripts/render_samples_s4.py`.", ""]
    for m in manifest:
        f = m["as_of_filing"]
        md += [f"## {m['name']}", "",
               f"- Tickers: {', '.join(m['tickers'])} ({m['kind']})",
               f"- As-of filing: {f['ticker']} {f['form']}, FYE {f['fiscal_year_end']}, filed {f['filed']}, accession {f['accession']}",
               f"- modelcheck score: {m['modelcheck_score']} (production ready: {m['production_ready']})",
               f"- validate pass: {m['validate_passed']} (critical {m['validate_critical']})",
               f"- Three engines agree: {m['three_engine_agree']} ({m['compared_cells']} cells compared)",
               f"- Build seconds: {m['build_seconds']} (includes SEC fetch and all checks); workbook {m['bytes']:,} bytes; {m['pdf_pages']} PDF pages",
               f"- Workbook: [{m['name']}.xlsx]({m['name']}.xlsx)", "", "| PNG | First lines on the page |", "|---|---|"]
        md += [f"| [{p['png'].split('/', 1)[1]}]({p['png']}) | {p['shows'].replace('|', '/')} |" for p in m["pngs"]]
        md.append("")
    (OUT / "README.md").write_text("\n".join(md))
    shutil.rmtree(work, ignore_errors=True)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
