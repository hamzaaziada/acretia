"""Build minimal but valid DOCX / XLSX / PPTX / PDF files with stdlib only (test fixtures)."""
import io
import zipfile
from xml.sax.saxutils import escape

CT = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def docx(pages: list[list[str]]) -> bytes:
    body = []
    for i, paras in enumerate(pages):
        for p in paras:
            body.append(f'<w:p><w:r><w:t xml:space="preserve">{escape(p)}</w:t></w:r></w:p>')
        if i < len(pages) - 1:
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
    doc = (f'{CT}<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{"".join(body)}</w:body></w:document>')
    return _zip({"[Content_Types].xml": f'{CT}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
                 "word/document.xml": doc})


def xlsx(sheets: dict[str, list[list]]) -> bytes:
    shared, idx = [], {}

    def s(v):
        if v not in idx:
            idx[v] = len(shared)
            shared.append(v)
        return idx[v]
    files = {}
    names = list(sheets)
    for n, (name, rows) in enumerate(sheets.items(), 1):
        xml_rows = []
        for r, row in enumerate(rows, 1):
            cells = []
            for c, v in enumerate(row):
                ref = f"{chr(65 + c)}{r}"
                if isinstance(v, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{v}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="s"><v>{s(str(v))}</v></c>')
            xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
        files[f"xl/worksheets/sheet{n}.xml"] = (f'{CT}<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                                                 f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    files["xl/sharedStrings.xml"] = (f'{CT}<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                                     + "".join(f"<si><t>{escape(x)}</t></si>" for x in shared) + "</sst>")
    files["xl/workbook.xml"] = (f'{CT}<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                                + "".join(f'<sheet name="{escape(nm)}" sheetId="{i}" r:id="rId{i}"/>' for i, nm in enumerate(names, 1))
                                + "</sheets></workbook>")
    files["[Content_Types].xml"] = f'{CT}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>'
    return _zip(files)


def pptx(slides: list[list[str]], notes: dict[int, str] | None = None) -> bytes:
    files = {"[Content_Types].xml": f'{CT}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>'}
    A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    for i, paras in enumerate(slides, 1):
        ps = "".join(f"<a:p><a:r><a:t>{escape(p)}</a:t></a:r></a:p>" for p in paras)
        files[f"ppt/slides/slide{i}.xml"] = f'{CT}<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" {A}><p:txBody>{ps}</p:txBody></p:sld>'
        if notes and i in notes:
            files[f"ppt/notesSlides/notesSlide{i}.xml"] = (f'{CT}<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" {A}>'
                                                           f'<a:p><a:r><a:t>{escape(notes[i])}</a:t></a:r></a:p></p:notes>')
    return _zip(files)


def pdf(pages: list[list[str]]) -> bytes:
    """Tiny valid PDF with a Helvetica text layer, one content stream per page."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        content = "BT /F1 11 Tf 50 750 Td 14 TL " + " ".join(f"({l.replace('(', '[').replace(')', ']')}) '" for l in lines) + " ET"
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objs)} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def sample_vdr_zip() -> bytes:
    """A fake 'Project Falcon' data-room export with an index-numbered folder tree, like Datasite/Intralinks exports."""
    files = {
        "Project Falcon/1. Overview/1.1 CIM.docx": docx([
            ["Project Falcon — Confidential Information Memorandum", "Falcon Software is a vertical SaaS provider for logistics fleets."],
            ["Financial Summary", "FY2025 revenue was $84.2 million, up 31% year over year.",
             "Adjusted EBITDA was $18.5 million, a margin of 22%.", "Net revenue retention was 118% and gross margin was 78%."],
            ["Customers", "The top 10 customers represent 41% of revenue; the largest customer, Northline Freight, is 12% of revenue."],
        ]),
        "Project Falcon/2. Financials/2.1 Model.xlsx": xlsx({
            "P&L": [["Metric", "FY2024", "FY2025", "FY2026E"], ["Revenue ($m)", 64.3, 84.2, 107.5],
                    ["Adjusted EBITDA ($m)", 11.9, 18.5, 26.9], ["Gross margin", "76%", "78%", "79%"]],
            "KPIs": [["ARR ($m)", 88.0], ["Customers", 412], ["NRR", "118%"]]}),
        "Project Falcon/3. Management/3.1 Mgmt Presentation.pptx": pptx(
            [["Falcon at a glance", "412 customers across 9 countries"],
             ["Growth plan", "Target revenue of $107.5 million in FY2026", "Expansion into cold-chain logistics"]],
            notes={2: "Management expects cold-chain to add $6 million ARR in 2026."}),
        "Project Falcon/4. Legal/4.1 Customer Contract Summary.pdf": pdf([
            ["Material Contracts Summary", "Northline Freight master agreement expires on March 31, 2027.",
             "The agreement contains a change of control clause requiring consent."],
            ["Litigation", "There is no material pending litigation against the Company."]]),
        "Project Falcon/__MACOSX/._junk": "x",
        "Project Falcon/4. Legal/notes.bin": "binary",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content if isinstance(content, (bytes, str)) else content)
    return buf.getvalue()
