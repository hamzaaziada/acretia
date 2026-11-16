"""Sheets (Shortcut-style): spreadsheets wired to our data, with one-click model templates.

Formulas run in the browser (om/static/sheets.html). Two data functions resolve on the server:
  =OM(ticker, field)                public-comps field from SEC filings, e.g. =OM("AAPL","ev_ebitda_ltm")
  =MATRIX(matrix, document, column) a Matrix cell value (or its text answer)
Every resolved value carries its source (filing accession / matrix cell) so the UI can show provenance.

Templates: trading comps, precedent transactions (from the M&A pipeline), DCF.
Export: .xlsx with ordinary formulas kept as formulas (Excel recalculates them) and OM()/MATRIX()
replaced by their values, plus .csv.
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

SCHEMA = """
CREATE TABLE IF NOT EXISTS sheets(id INTEGER PRIMARY KEY, name TEXT UNIQUE, cells TEXT, meta TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS comps_cache(key TEXT PRIMARY KEY, row TEXT, prov TEXT, computed_at REAL);
"""

COMPS_FIELDS = [("revenue_ltm", "Revenue LTM ($m)"), ("revenue_growth_ltm_yoy", "Rev growth YoY %"),
                ("margin_gross_ltm", "Gross margin %"), ("margin_ebitda_ltm", "EBITDA margin %"),
                ("ebitda_ltm", "EBITDA LTM ($m)"), ("net_income_ltm", "Net income LTM ($m)"),
                ("rule_of_40_ltm_hist", "Rule of 40"), ("enterprise_value", "EV ($m)"),
                ("ev_revenue_ltm", "EV / Revenue LTM"), ("ev_ebitda_ltm", "EV / EBITDA LTM"), ("price_earnings_ltm", "P / E LTM")]


# --------------------------------------------------------------------------- storage
class Sheets:
    def __init__(self, db):
        self.db = db
        self.db.executescript(SCHEMA)

    def list(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT id, name, created_at, updated_at, meta FROM sheets ORDER BY updated_at DESC")]

    def get(self, sid: int) -> dict:
        r = self.db.execute("SELECT * FROM sheets WHERE id=?", (sid,)).fetchone()
        if not r:
            raise KeyError(f"no sheet {sid}")
        d = dict(r)
        d["cells"], d["meta"] = json.loads(d["cells"] or "{}"), json.loads(d["meta"] or "{}")
        return d

    def create(self, name: str, cells: dict | None = None, meta: dict | None = None) -> int:
        base, n = name, 2
        while self.db.execute("SELECT 1 FROM sheets WHERE name=?", (name,)).fetchone():
            name, n = f"{base} ({n})", n + 1
        cur = self.db.execute("INSERT INTO sheets(name, cells, meta, created_at, updated_at) VALUES(?,?,?,?,?)",
                              (name, json.dumps(cells or {}), json.dumps(meta or {}), time.time(), time.time()))
        self.db.commit()
        return cur.lastrowid

    def save(self, sid: int, cells: dict, meta: dict | None = None, name: str | None = None) -> None:
        cells = {k: v for k, v in cells.items() if re.fullmatch(r"[A-Z]{1,2}\d{1,4}", k) and v not in ("", None)}
        self.db.execute("UPDATE sheets SET cells=?, meta=COALESCE(?, meta), name=COALESCE(?, name), updated_at=? WHERE id=?",
                        (json.dumps(cells), json.dumps(meta) if meta is not None else None, name, time.time(), sid))
        self.db.commit()

    def delete(self, sid: int) -> None:
        self.db.execute("DELETE FROM sheets WHERE id=?", (sid,))
        self.db.commit()


# --------------------------------------------------------------------------- data functions
class DataService:
    """Resolves OM() and MATRIX() calls. Comps rows are computed from SEC company facts and cached."""

    def __init__(self, index, data_dir: Path, ttl: float = 24 * 3600):
        self.index = index
        self.db = index.db
        self.data_dir = Path(data_dir)
        self.ttl = ttl
        self._lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def _cik(self, ticker: str) -> int | None:
        if ticker.isdigit():
            return int(ticker)
        uni = self.data_dir / "universe.csv"
        if uni.exists():
            with open(uni, newline="") as fh:
                for r in csv.DictReader(fh):
                    if r["ticker"].upper() == ticker.upper():
                        return int(r["cik"])
        return None

    def comps_row(self, ticker: str) -> tuple[dict, dict]:
        key = ticker.upper()
        r = self.db.execute("SELECT row, prov, computed_at FROM comps_cache WHERE key=?", (key,)).fetchone()
        if r and time.time() - r["computed_at"] < self.ttl:
            return json.loads(r["row"]), json.loads(r["prov"])
        cik = self._cik(ticker)
        if cik is None:
            raise KeyError(f"unknown ticker {ticker} (run `python3 open_multiples.py universe` to load the SEC ticker list)")
        import os

        from .fx import FX
        from .metrics import compute
        from .prices import CsvPrices
        from .sec import SecClient
        sec = SecClient(os.environ.get("SEC_USER_AGENT", ""), self.data_dir / "raw" / "sec")
        prices = CsvPrices(Path(os.environ["PRICES_CSV"])) if os.environ.get("PRICES_CSV") else None
        sub = sec.submissions(cik)
        quote = None
        if prices:
            for t in sub.get("tickers") or [ticker]:
                quote = prices.get(t)
                if quote:
                    break
        row, prov = compute(sec.companyfacts(cik), sub, quote, FX(self.data_dir / "raw" / "fx"))
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO comps_cache VALUES(?,?,?,?)", (key, json.dumps(row), json.dumps(prov), time.time()))
            self.db.commit()
        return row, prov

    def statements(self, ticker: str, years: int = 5):
        """Full annual statements (om.statements) for the integrated model."""
        import os

        from . import statements as stm
        from .sec import SecClient
        cik = self._cik(ticker)
        if cik is None:
            raise KeyError(f"unknown ticker {ticker} (run `python3 open_multiples.py universe` to load the SEC ticker list)")
        sec = SecClient(os.environ.get("SEC_USER_AGENT", ""), self.data_dir / "raw" / "sec")
        sub = sec.submissions(cik)
        try:
            sic = int(sub.get("sic") or 0) or None
        except ValueError:
            sic = None
        return stm.build(sec.companyfacts(cik), ticker.upper(), years=years, sic=sic)

    def om(self, ticker: str, field: str) -> dict:
        row, prov = self.comps_row(ticker)
        if field not in row:
            return {"error": "#FIELD?", "detail": f"unknown field {field}"}
        val = row[field]
        p = prov.get(field) or prov.get(f"{field}_lcu") or {}
        src = None
        if p.get("facts"):
            f0 = p["facts"][0]
            src = {"basis": p.get("basis"), "concept": f0["concept"], "form": f0["form"], "filed": f0["filed"],
                   "url": f"https://www.sec.gov/Archives/edgar/data/{row['cik']}/{f0['accn'].replace('-', '')}/"}
        elif field in ("market_cap", "enterprise_value", "ev_revenue_ltm", "ev_ebitda_ltm", "price_earnings_ltm") and val is None:
            return {"error": "#NOPRICE", "detail": "needs a licensed price (set PRICES_CSV in .env)"}
        if val is None:
            return {"error": "#N/A", "detail": "not available in the filings" + (f" (non-meaningful)" if field in (row.get("nm_fields") or "") else "")}
        return {"value": val, "source": src, "company": row.get("name")}

    def matrix(self, matrix: str, document: str, column: str) -> dict:
        r = self.db.execute("""SELECT c.value, c.answer, c.status, c.citations, d.title, d.url FROM matrix_cells c
                               JOIN matrices m ON m.id=c.matrix_id JOIN documents d ON d.doc_id=c.doc_id
                               WHERE (m.name=? OR m.id=?) AND c.column_name=? AND (d.title=? OR d.path=? OR d.ticker=?)""",
                            (matrix, matrix, column, document, document, document)).fetchone()
        if not r:
            return {"error": "#N/A", "detail": "no such matrix cell"}
        v = json.loads(r["value"]) if r["value"] else None
        cites = json.loads(r["citations"] or "[]")
        src = {"matrix": matrix, "status": r["status"], "document": r["title"],
               "quote": cites[0]["quote"] if cites else None, "section": cites[0].get("section") if cites else None}
        return {"value": v if v is not None else r["answer"], "source": src}

    def resolve(self, calls: list) -> list[dict]:
        out = []
        for call in calls[:500]:
            try:
                fn, args = call[0].upper(), [str(a) for a in call[1:]]
                if fn == "OM" and len(args) == 2:
                    out.append(self.om(*args))
                elif fn == "OMNAME" and len(args) == 1:
                    row, _ = self.comps_row(args[0])
                    out.append({"value": row.get("name"), "source": {"basis": "SEC company name", "cik": row.get("cik")}})
                elif fn == "MATRIX" and len(args) == 3:
                    out.append(self.matrix(*args))
                else:
                    out.append({"error": "#NAME?", "detail": f"unknown data function {fn}/{len(args)}"})
            except KeyError as e:
                out.append({"error": "#REF!", "detail": str(e).strip("'\"")})
            except Exception as e:
                out.append({"error": "#ERROR", "detail": repr(e)[:200]})
        return out


# --------------------------------------------------------------------------- export
DATA_FN = re.compile(r"\b(OM|OMNAME|MATRIX)\s*\(", re.I)


def _ref(k: str) -> tuple[int, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", k)
    c = 0
    for ch in m.group(1):
        c = c * 26 + ord(ch) - 64
    return int(m.group(2)), c


def to_xlsx(name: str, cells: dict, values: dict) -> bytes:
    """cells: raw inputs ("=SUM(A1:A3)", "12", "text"); values: computed values from the browser.
    Ordinary formulas are written as formulas with cached values; data-function formulas as values."""
    rows: dict[int, list] = {}
    for k in cells:
        r, c = _ref(k)
        rows.setdefault(r, []).append((c, k))
    out_rows = []
    for r in sorted(rows):
        xs = []
        for c, k in sorted(rows[r]):
            raw, val = str(cells[k]), values.get(k)
            if raw.startswith("=") and not DATA_FN.search(raw):
                f = escape(raw[1:].replace("QUARTILE(", "QUARTILE.INC("))
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    xs.append(f'<c r="{k}"><f>{f}</f><v>{val}</v></c>')
                else:
                    xs.append(f'<c r="{k}" t="str"><f>{f}</f><v>{escape(str(val or ""))}</v></c>')
                continue
            v = val if raw.startswith("=") else _num(raw)
            if isinstance(v, bool):
                xs.append(f'<c r="{k}" t="b"><v>{int(v)}</v></c>')
            elif isinstance(v, (int, float)):
                xs.append(f'<c r="{k}"><v>{v}</v></c>')
            elif v not in (None, ""):
                xs.append(f'<c r="{k}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>')
        out_rows.append(f'<row r="{r}">{"".join(xs)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    sheet = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet {ns}><sheetData>{"".join(out_rows)}</sheetData></worksheet>'
    safe = re.sub(r"[\[\]:*?/\\]", "-", name)[:31] or "Sheet1"
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook {ns} {rel}><sheets><sheet name="{escape(safe)}" sheetId="1" r:id="rId1"/></sheets>'
        '<calcPr fullCalcOnLoad="1"/></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, content in files.items():
            z.writestr(n, content)
    return buf.getvalue()


def _num(s: str):
    try:
        return float(s.replace(",", "")) if re.fullmatch(r"-?[\d,]*\.?\d+(e-?\d+)?", s.strip()) else s
    except ValueError:
        return s
