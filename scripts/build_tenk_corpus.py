#!/usr/bin/env python3
"""Build the 10-K QA gold-set corpus (S5.4a): 10 real SEC 10-K filings -> trimmed PDFs.

Fetch (SEC EDGAR, public records) -> cache raw HTML in data/raw/tenk/ (gitignored)
-> strip inline-XBRL hidden header/scripts -> LibreOffice HTML->PDF -> trim to the
pages that carry the gold answers -> evals/tenk/pdfs/<TICKER>.pdf + manifest.json.

Usage:
  python3 scripts/build_tenk_corpus.py            # build (re-runnable; uses cache)
  python3 scripts/build_tenk_corpus.py --verify   # check PDFs vs manifest sha256, print them
"""
import argparse, hashlib, json, os, re, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "evals" / "tenk"
PDFS = OUT / "pdfs"
RAW = ROOT / "data" / "raw" / "tenk"
UA = "Acretia hamza@meshpool.ai"
FILERS = {"AAPL": 320193, "MSFT": 789019, "KO": 21344, "JNJ": 200406, "PG": 80424,
          "WMT": 104169, "COST": 909832, "HD": 354950, "MCD": 63908, "LOW": 60667}
# LibreOffice can hang on some filings' HTML (NKE did); the next candidate replaces a filer whose conversion times out.
# NKE and PEP were dropped for exactly that reason (soffice > 240 s), replaced by MCD and LOW.
FALLBACKS = {"TGT": 27419, "MMM": 66740}
MAX_PAGES = 25
_last = [0.0]


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def get(url, dest):
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return dest.read_bytes()
    wait = 0.25 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)  # <= 4 req/s
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    _last[0] = time.time()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data


def latest_10k(cik):
    d = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", RAW / f"CIK{cik:010d}.submissions.json"))
    r = d["filings"]["recent"]
    for i, f in enumerate(r["form"]):
        if f == "10-K":
            return {"accession": r["accessionNumber"][i], "primary": r["primaryDocument"][i],
                    "report_date": r["reportDate"][i], "filing_date": r["filingDate"][i]}
    raise RuntimeError(f"no 10-K for {cik}")


def clean_html(raw):
    s = raw.decode("utf-8", "replace")
    s = re.sub(r"(?is)<ix:header>.*?</ix:header>", "", s)
    s = re.sub(r"(?is)<script.*?</script>", "", s)
    s = re.sub(r'(?is)<div[^>]*display:\s*none[^>]*>.*?</div>', "", s)
    return s


def soffice_version():
    try:
        return subprocess.run(["soffice", "--version"], capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def convert(htm, outdir):
    subprocess.run(["soffice", "--headless", "-env:UserInstallation=file:///tmp/lo_profile_tenk",
                    "--convert-to", "pdf", "--outdir", str(outdir), str(htm)],
                   check=True, capture_output=True, timeout=240)
    return Path(outdir) / (Path(htm).stem + ".pdf")


def page_texts(pdf_path):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf_path))
    out = []
    for i in range(len(doc)):
        tp = doc[i].get_textpage()
        out.append(tp.get_text_range())
        tp.close()
    doc.close()
    return out


def pick_pages(texts):
    """Pick <= MAX_PAGES pages: cover, employees, MD&A numbers, income stmt, balance sheet, auditor, debt."""
    n = len(texts)
    low = [t.lower() for t in texts]
    def toc(i):
        return len(re.findall(r"\bitem\s+\d", low[i])) > 12
    def best(fn, k=1, lo=0):
        sc = [(fn(i), i) for i in range(lo, n) if not toc(i)]
        sc = [x for x in sc if x[0] > 0]
        sc.sort(key=lambda x: (-x[0], x[1]))
        return sorted(i for _, i in sc[:k])
    sel = {0}
    sel.update(best(lambda i: ("total assets" in low[i]) * 2 + ("total liabilities" in low[i]) * 2
                    + ("cash and cash equivalents" in low[i]) + ("total shareholders" in low[i] or "total stockholders" in low[i])
                    + (("long-term debt" in low[i]) or ("long term debt" in low[i])) * 2
                    + 3 * ("consolidated balance sheet" in low[i][:600]), 2))
    sel.update(best(lambda i: 4 * ("report of independent registered public accounting firm" in low[i])
                    + 2 * ("/s/" in low[i] and "llp" in low[i]) + 2 * ("critical audit matter" in low[i]), 2))
    sel.update(best(lambda i: 3 * bool(re.search(r"\b\d{1,3}(,\d{3})+\s+(full-time|employees|team members|associates|people)|(approximately|had|employed)\s+[\d,]{5,}|approximately [\d.]+ million (associates|employees|people)", low[i]))
                    + 2 * ("employees" in low[i]) + 2 * ("human capital" in low[i]), 2))
    sel.update(best(lambda i: 3 * ("selected" in low[i] and "results of operations" in low[i]) + 2 * ("total net sales" in low[i] or "total revenue" in low[i])
                    + 2 * ("net sales" in low[i]) + ("diluted" in low[i]) + 3 * ("executive overview" in low[i] or "overview" in low[i][:500]), 3, lo=min(5, n)))
    sel.update(best(lambda i: 3 * ("long-term debt" in low[i]) + 2 * ("notes payable" in low[i] or "senior notes" in low[i]) + ("maturit" in low[i]), 2))
    sel.update(best(lambda i: 3 * ("state or other jurisdiction" in low[i]) + ("incorporat" in low[i]), 1))
    sel.update(best(lambda i: 3 * ("fiscal year ended" in low[i] or "fiscal year end" in low[i]) + 2 * ("incorporated in" in low[i] or "incorporated under" in low[i]), 1))
    # anchored picks: first real financial statement pages (+-1 for spill-over) and the auditor's signed report
    def first(rx, need=None, head=None, lo=8):
        for i in range(lo, n):
            if toc(i):
                continue
            if re.search(rx, texts[i], re.I | re.M) and (need is None or re.search(need, low[i])) and (head is None or re.search(head, low[i][:1500])):
                return i
        return None
    stm = r"statements? of (income|earnings|operations|comprehensive)|income statements?|balance sheets?"
    for rx, need, head in [(r"diluted|per (common )?share", r"net (income|earnings)|net loss", stm), (r"^total assets", r"total liabilities", stm),
                           (r"^total assets", r"total liabilities", None), (r"/s/[^\n]*(LLP|Deloitte|KPMG|Ernst|Pricewaterhouse)", None, None)]:
        i = first(rx, need, head)
        if i is not None:
            sel.update(set(range(i - 2, i + 3)) & set(range(n)))
    i = first(r"^(consolidated )?net (income|earnings)\b[^\n]*\d{1,3},\d{3}", r"provision for (income )?taxes|income taxes", None, lo=12)
    if i is not None:
        sel.update(set(range(i - 2, i + 2)) & set(range(n)))
    # any page opening with a primary-statement title (income statement / balance sheet), plus its successor
    hdr = re.compile(r"consolidated\s+(statements?\s+of\s+(income|earnings|operations)|balance\s+sheets?)", re.I)
    cnt = 0
    for i in range(8, n):
        if cnt < 4 and not toc(i) and hdr.search(texts[i][:400]) and len(re.findall(r"\d{1,3},\d{3}", texts[i])) >= 15:
            sel.update({i, i + 1} & set(range(n))); cnt += 1
    sel = sorted(sel)
    if len(sel) > MAX_PAGES:
        sel = sel[:MAX_PAGES]
    return sel


def trim(full_pdf, idxs, dest):
    import pypdfium2 as pdfium
    src = pdfium.PdfDocument(str(full_pdf))
    dst = pdfium.PdfDocument.new()
    dst.import_pages(src, idxs)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dst.save(str(dest))
    dst.close(); src.close()


def build():
    RAW.mkdir(parents=True, exist_ok=True); PDFS.mkdir(parents=True, exist_ok=True)
    man = {"soffice_version": soffice_version(), "user_agent_note": "SEC fair-access UA used for fetches", "filings": []}
    todo = list(FILERS.items()); spare = list(FALLBACKS.items()); done = 0
    while todo:
        tkr, cik = todo.pop(0)
        try:
            entry = build_one(tkr, cik, man)
        except subprocess.TimeoutExpired:
            print(f"{tkr}: soffice timed out (>240s); replacing with {spare[0][0]}", flush=True)
            subprocess.run(["pkill", "soffice"])
            todo.append(spare.pop(0))
    (OUT / "manifest.json").write_text(json.dumps(man, indent=1))
    print("manifest written")


def build_one(tkr, cik, man):
    if True:
        f = latest_10k(cik)
        nodash = f["accession"].replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{f['primary']}"
        raw = get(url, RAW / f"{tkr}_{f['primary']}")
        get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", RAW / f"CIK{cik:010d}.facts.json")
        full = RAW / "full" / f"{tkr}.pdf"
        if not full.exists():
            full.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as td:
                htm = Path(td) / f"{tkr}.htm"
                htm.write_text(clean_html(raw), encoding="utf-8")
                full.write_bytes(convert(htm, td).read_bytes())
        texts = page_texts(full)
        idxs = pick_pages(texts)
        dest = PDFS / f"{tkr}.pdf"
        trim(full, idxs, dest)
        size = dest.stat().st_size
        print(f"{tkr}: {len(texts)} pages -> {len(idxs)} kept, {size/1e6:.2f} MB, sha256 {sha256(dest)}", flush=True)
        man["filings"].append({
            "ticker": tkr, "cik": cik, "accession": f["accession"], "primary_document": url,
            "fiscal_year_end": f["report_date"], "filing_date": f["filing_date"], "pdf": f"pdfs/{tkr}.pdf",
            "sha256": sha256(dest), "bytes": size,
            "page_map": [{"page": k + 1, "orig_page": i + 1} for k, i in enumerate(idxs)],
            "orig_page_count": len(texts), "soffice_version": man["soffice_version"]})


def verify():
    man = json.loads((OUT / "manifest.json").read_text())
    bad = 0; total = 0
    for f in man["filings"]:
        p = OUT / f["pdf"]
        h = sha256(p) if p.exists() else None
        ok = h == f["sha256"]; bad += not ok
        total += p.stat().st_size if p.exists() else 0
        print(f"{'OK ' if ok else 'BAD'} {f['ticker']:5s} {f['pdf']} {h}")
    print(f"{len(man['filings'])} PDFs, {total/1e6:.2f} MB total")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    sys.exit(verify() if a.verify else (build() or 0))
