"""Text extraction for data-room documents. Pages are separated by form feeds (\\f) so citations can
point to a page.

PDF   pdftotext (poppler, preferred: fast, keeps layout) -> pypdf if installed -> error with install hint
DOCX  stdlib (zip + XML), page breaks from explicit <w:br w:type="page"/>
PPTX  stdlib, one "page" per slide (speaker notes included)
XLSX  stdlib, one "page" per sheet, cells as tab-separated rows (shared strings resolved)
HTML  om.htmltables
EML   stdlib email; attachments are reported, not parsed (import them as files)
TXT / MD / CSV / JSON  read as text
Scanned PDFs with no text layer come back empty and are flagged `needs_ocr`.
"""
from __future__ import annotations

import email
import email.policy
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from .htmltables import parse as parse_html

SUPPORTED = {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".htm", ".html", ".txt", ".md", ".csv", ".json", ".eml", ".xml"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


@dataclass
class Extracted:
    text: str                 # pages joined by \f
    pages: int
    kind: str
    warnings: list = field(default_factory=list)


def extract(path: Path) -> Extracted:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _pdf(path)
    if ext == ".docx":
        return _docx(path)
    if ext == ".pptx":
        return _pptx(path)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx(path)
    if ext in (".htm", ".html", ".xml"):
        raw = path.read_text(errors="ignore")
        return Extracted(parse_html(raw).text, 1, "html")
    if ext == ".eml":
        return _eml(path)
    if ext in (".txt", ".md", ".csv", ".json"):
        return Extracted(path.read_text(errors="ignore"), 1, ext.lstrip("."))
    raise ValueError(f"unsupported file type {ext}")


def _pdf(path: Path) -> Extracted:
    exe = shutil.which("pdftotext") or next((p for p in ("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext",
                                                          "/usr/bin/pdftotext") if Path(p).exists()), None)
    if exe:
        r = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=300)
        if r.returncode != 0:
            raise ValueError(f"pdftotext failed: {r.stderr.decode(errors='ignore')[:200]}")
        text = r.stdout.decode("utf-8", "ignore")
    else:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("PDF support needs poppler (brew install poppler / apt install poppler-utils) or pip install pypdf")
        text = "\f".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
    text = re.sub(r"[ \t]{3,}", "  ", text)  # layout mode pads columns with spaces
    pages = text.count("\f") + 1
    ex = Extracted(text, pages, "pdf")
    if len(re.sub(r"\s", "", text)) < 20 * pages:
        ex.warnings.append("needs_ocr: little or no text layer (scanned PDF)")
    return ex


def _docx(path: Path) -> Extracted:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    pages, cur = [], []
    for p in root.iter(f"{W}p"):
        line = []
        for node in p.iter():
            if node.tag == f"{W}t" and node.text:
                line.append(node.text)
            elif node.tag == f"{W}tab":
                line.append("\t")
            elif node.tag == f"{W}br" and node.get(f"{W}type") == "page":
                cur.append("".join(line))
                pages.append("\n".join(cur))
                cur, line = [], []
        cur.append("".join(line))
    pages.append("\n".join(cur))
    return Extracted("\f".join(pages), len(pages), "docx")


def _pptx(path: Path) -> Extracted:
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                       key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        slides = []
        for n in names:
            root = ET.fromstring(z.read(n))
            paras = ["".join(t.text or "" for t in p.iter(f"{A}t")) for p in root.iter(f"{A}p")]
            notes_name = n.replace("slides/slide", "notesSlides/notesSlide")
            if notes_name in z.namelist():
                nroot = ET.fromstring(z.read(notes_name))
                notes = [" ".join(t.text or "" for t in p.iter(f"{A}t")) for p in nroot.iter(f"{A}p")]
                notes = [x for x in notes if x.strip() and not x.strip().isdigit()]
                if notes:
                    paras += ["Speaker notes:"] + notes
            slides.append("\n".join(x for x in paras if x.strip()))
    return Extracted("\f".join(slides), len(slides), "pptx")


def _xlsx(path: Path) -> Extracted:
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{S}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheet_names = [s.get("name") for s in wb.iter(f"{S}sheet")]
        files = sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                       key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        pages = []
        for i, n in enumerate(files):
            root = ET.fromstring(z.read(n))
            rows = []
            for row in root.iter(f"{S}row"):
                vals = []
                for c in row.iter(f"{S}c"):
                    v = c.find(f"{S}v")
                    t = c.get("t")
                    if t == "s" and v is not None:
                        vals.append(shared[int(v.text)])
                    elif t == "inlineStr":
                        vals.append("".join(x.text or "" for x in c.iter(f"{S}t")))
                    elif v is not None:
                        vals.append(v.text or "")
                if any(x.strip() for x in vals):
                    rows.append("\t".join(vals))
                if len(rows) >= 5000:
                    break
            title = sheet_names[i] if i < len(sheet_names) else f"Sheet {i + 1}"
            pages.append(f"Sheet: {title}\n" + "\n".join(rows))
    return Extracted("\f".join(pages), len(pages), "xlsx")


def _eml(path: Path) -> Extracted:
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    head = "\n".join(f"{h}: {msg.get(h, '')}" for h in ("From", "To", "Date", "Subject"))
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body and body.get_content_type() == "text/html":
        text = parse_html(text).text
    atts = [a.get_filename() for a in msg.iter_attachments() if a.get_filename()]
    ex = Extracted(head + "\n\n" + text + (f"\n\nAttachments: {', '.join(atts)}" if atts else ""), 1, "eml")
    if atts:
        ex.warnings.append(f"{len(atts)} attachment(s) not parsed: import them as files")
    return ex
