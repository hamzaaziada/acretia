"""Ingest SEC filings into the search index: list filings, fetch documents and exhibits, split into
sections and passages.

- Filing list: data.sec.gov submissions (recent ~1,000 filings per company).
- Documents: the primary document of each filing, plus EX-99 exhibits for 8-K / 6-K
  (earnings releases, investor presentations, deal announcements).
- Sections: 10-K/10-Q "Item 1A. Risk Factors"-style headings and 8-K "Item 2.02" headings.
- Passages: paragraphs merged to ~1,500 characters; each keeps its section and its character offset.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .htmltables import parse

DEFAULT_FORMS = ["10-K", "10-Q", "8-K", "20-F", "40-F", "6-K", "DEF 14A", "DEFM14A", "PREM14A", "S-1", "S-4", "424B4"]
ARCHIVE_DIR = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"

ITEM_RE = re.compile(r"(?i)^\s*(item\s+\d{1,2}[a-c]?(?:\.\d{2})?)\s*[.:\-—–]?\s*(.{0,90})$")
PART_RE = re.compile(r"(?i)^\s*part\s+(i{1,3}|iv)\b")
NOISE_RE = re.compile(r"(?i)^\s*(table of contents|\d{1,3}|page \d+|index to (consolidated )?financial statements)\s*$")
PAGE_BREAK = "@@PAGE_BREAK@@"
EXHIBIT_RE = re.compile(r"(?i)(ex[-_]?99|exhibit[-_]?99|dex99)[^/]*\.html?$")


@dataclass
class DocRef:
    cik: int
    ticker: str | None
    company: str
    form: str
    filed: str
    report_date: str | None
    accession: str
    file: str
    url: str
    title: str
    items: str | None


@dataclass
class Passage:
    ord: int
    section: str | None
    text: str
    offset: int


def list_filings(sub: dict, forms: list[str], since: str | None = None, until: str | None = None,
                 max_per_company: int | None = None) -> list[DocRef]:
    r = sub.get("filings", {}).get("recent", {})
    cik = int(sub["cik"])
    ticker = (sub.get("tickers") or [None])[0]
    out = []
    for i, form in enumerate(r.get("form", [])):
        if form not in forms:
            continue
        filed = r["filingDate"][i]
        if (since and filed < since) or (until and filed > until):
            continue
        acc = r["accessionNumber"][i]
        doc = r["primaryDocument"][i]
        if not doc:
            continue
        out.append(DocRef(cik, ticker, sub.get("name", ""), form, filed, r.get("reportDate", [None] * (i + 1))[i] or None,
                          acc, doc, ARCHIVE_DIR.format(cik=cik, acc=acc.replace("-", "")) + doc,
                          r.get("primaryDocDescription", [""] * (i + 1))[i] or form,
                          (r.get("items") or [""] * (i + 1))[i] or None))
        if max_per_company and len(out) >= max_per_company:
            break
    return out


def exhibits(sec, ref: DocRef) -> list[DocRef]:
    """EX-99.x documents of an 8-K / 6-K (earnings releases, presentations)."""
    if ref.form not in ("8-K", "8-K/A", "6-K"):
        return []
    base = ARCHIVE_DIR.format(cik=ref.cik, acc=ref.accession.replace("-", ""))
    try:
        idx = sec.get_json(base + "index.json", f"index/{ref.accession}", max_age=10 ** 9)
    except Exception:
        return []
    out = []
    for item in idx.get("directory", {}).get("item", []):
        name = item.get("name", "")
        if EXHIBIT_RE.search(name):
            m = re.search(r"(?i)99[._-]?(\d+)?", name)
            label = f"Exhibit 99.{m.group(1)}" if m and m.group(1) else "Exhibit 99"
            out.append(DocRef(ref.cik, ref.ticker, ref.company, ref.form, ref.filed, ref.report_date, ref.accession,
                              name, base + name, f"{label} to {ref.form}", ref.items))
    return out


def passages(raw: str, target: int = 1500, minimum: int = 300, paged: bool = False) -> tuple[list[Passage], int]:
    """paged=True: `raw` is plain text with \\f between pages; passages never span pages and their
    section label carries the page ("Item 7 · p.12" or "p.12")."""
    if paged:
        text = raw
    elif raw.lstrip()[:200].lower().find("<html") >= 0 or "<div" in raw[:5000].lower() or "<p" in raw[:5000].lower():
        text = parse(raw).text
    else:
        text = raw
    if paged:
        text = text.replace("\f", f"\n{PAGE_BREAK}\n")
    lines = [ln.strip() for ln in text.split("\n")]
    # running page headers/footers: short lines (page numbers stripped) that repeat throughout the document
    key = lambda s: re.sub(r"\s*\|?\s*\d{1,3}\s*$", "", s)  # noqa: E731
    counts: dict[str, int] = {}
    for ln in lines:
        if 0 < len(ln) < 120:
            counts[key(ln)] = counts.get(key(ln), 0) + 1
    repeated = {k for k, n in counts.items() if n >= 5 and k and k != PAGE_BREAK and not ITEM_RE.match(k)}
    lines = [ln for ln in lines if not (0 < len(ln) < 120 and key(ln) in repeated)]
    out: list[Passage] = []
    section = None
    page = 1
    buf: list[str] = []
    buf_offset = 0
    pos = 0
    ordn = 0

    def label():
        if not paged:
            return section
        return f"{section} · p.{page}" if section else f"p.{page}"

    def flush():
        nonlocal buf, ordn
        if buf:
            t = re.sub(r"[ \t]+", " ", " ".join(buf)).strip()
            if len(t) >= (10 if paged else 40):  # uploads keep short files (a 3-line CSV); filings drop crumbs
                out.append(Passage(ordn, label(), t, buf_offset))
                ordn += 1
        buf = []

    for ln in lines:
        start = pos
        pos += len(ln) + 1
        if ln == PAGE_BREAK:
            flush()
            page += 1
            continue
        if not ln or NOISE_RE.match(ln):
            continue
        m = ITEM_RE.match(ln)
        if m and len(ln) < 120 and not re.search(r"\.{3,}|\s\d{1,3}$", ln):  # skip table-of-contents lines
            flush()
            title = m.group(2).strip(" .")
            section = (m.group(1).title() + (f". {title}" if title else ""))[:100]
            continue
        if not buf:
            buf_offset = start
        buf.append(ln)
        size = sum(len(b) for b in buf)
        if size >= target or (size >= minimum and ln.endswith((".", ":", ";")) and size >= target * 0.6):
            flush()
    flush()
    return out, len(text)
