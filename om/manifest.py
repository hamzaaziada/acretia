"""ModelManifest export: which workbook cell backs which headline number, and which filings source it.

``export(data, meta)`` hashes the workbook bytes, resolves every output cell, and walks each cell's precedents
transitively (om.formula parse/deps over om.xlsx.read) down to sourced leaves: cells carrying a comment or an
external link, which in our models are the Filings sheet figures as reported. One Citation per distinct filing.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque

from . import formula as fx
from . import xlsx
from .contracts import Citation, ManifestOutput, ModelManifest

MAX_CITATIONS = 12
_ACCN = re.compile(r"\d{10}-\d{2}-\d{6}")
_FILED = re.compile(r"filed (\d{4}-\d{2}-\d{2})")
_URL = re.compile(r"https?://\S+")
_M3_KEYS = (("revenue", "IS", "rev", "USD m"), ("ebitda", "IS", "ebitda", "USD m"), ("net_income", "IS", "ni", "USD m"),
            ("eps", "IS", "eps", "USD/share"), ("fcf", "CF", "fcf", "USD m"))


def _sha(x) -> str:
    return hashlib.sha256(x if isinstance(x, bytes) else x.encode("utf-8")).hexdigest()


def _fy_columns(meta: dict):
    """(first_year, n_hist, n_total) for model3-style metas."""
    ys = meta.get("years") or []
    h = len(ys)
    return (int(str(ys[-1])[:4]) - h + 1 if h else 0), h, h + int(meta.get("forecast_years", 0))


def default_outputs(book, meta: dict) -> list[dict]:
    rows = meta.get("rows") or {}
    y0, h, n = _fy_columns(meta)
    out = []
    for key, sheet, rk, units in _M3_KEYS:
        r = (rows.get(sheet) or {}).get(rk)
        if r is None:
            continue
        for p in range(n):
            out.append({"id": f"m3.{key}.{y0 + p}", "sheet": sheet, "ref": f"{xlsx.col_letter(3 + p)}{r}", "units": units,
                        "historical": p < h})
    dcf = book.sheets.get("DCF", {})
    for (r, c), cell in sorted(dcf.items()):
        if c == 1 and isinstance(cell.value, str) and cell.value.strip().lower() == "implied value per share":
            out.append({"id": "m3.dcf.value_per_share", "sheet": "DCF", "ref": f"C{r}", "units": "USD/share", "historical": False})
            break
    return out


def outputs_for(book, meta: dict) -> list[dict]:
    if meta.get("outputs"):
        return [dict(o) for o in meta["outputs"]]
    return default_outputs(book, meta)


def _ref_cell(ref: str) -> tuple[int, int]:
    return xlsx.split_ref(ref.replace("$", "").split(":")[0])


def _sourced(book, sheet, rc) -> bool:
    if book.comments.get(sheet, {}).get(rc):
        return True
    lk = book.links.get(sheet, {}).get(rc)
    return bool(lk and lk.startswith("http"))


class _Walker:
    def __init__(self, book):
        self.book = book
        self.names = {}
        for n, t in book.names.items():
            if n.startswith("_xlnm") or not t:
                continue
            try:
                self.names[n] = fx.parse("=" + t, "")
            except Exception:
                pass
        self._deps = {}

    def precedents(self, key):
        if key not in self._deps:
            sheet, r, c = key
            cell = self.book.sheets.get(sheet, {}).get((r, c))
            d = set()
            if cell is not None and cell.formula:
                try:
                    d = fx.deps(fx.parse(cell.formula, sheet), self.names, set())
                except Exception:
                    d = set()
            self._deps[key] = d
        return self._deps[key]

    def leaves(self, sheet, ref) -> list:
        start = (sheet, *_ref_cell(ref))
        seen, q, found = {start}, deque([start]), []
        while q:
            k = q.popleft()
            if _sourced(self.book, k[0], (k[1], k[2])):
                found.append(k)
                continue
            for d in sorted(self.precedents(k)):
                if d not in seen:
                    seen.add(d)
                    q.append(d)
        return found


def _citations(book, leaves) -> list[Citation]:
    best = {}
    for sheet, r, c in leaves:
        text = book.comments.get(sheet, {}).get((r, c)) or ""
        url = book.links.get(sheet, {}).get((r, c)) or ""
        if not url.startswith("http"):
            m = _URL.search(text)
            url = m.group(0) if m else None
        m = _ACCN.search(text)
        doc = m.group(0) if m else (_sha(url)[:16] if url else _sha(f"{sheet}!{r},{c}")[:16])
        fm = _FILED.search(text)
        filed = fm.group(1) if fm else ""
        cite = Citation(doc_id=doc, sha256_span_hash=_sha(text or f"{sheet}!{xlsx.ref(r, c)}"), quote=text, source_url=url,
                        sheet=sheet, cell=xlsx.ref(r, c))
        cand = ((sheet, r, c), filed, cite)
        old = best.get(doc)
        if old is None or cand[0] < old[0]:      # per filing keep the first leaf, deterministically
            best[doc] = cand
    ordered = sorted(best.values(), key=lambda t: (t[1], t[2].doc_id), reverse=True)   # most recent first
    return [t[2] for t in ordered[:MAX_CITATIONS]]


def export_with_values(data: bytes, meta: dict) -> tuple[ModelManifest, dict]:
    book = xlsx.read(data)
    walker = _Walker(book)
    outs, values = [], {}
    for o in outputs_for(book, meta):
        sheet, ref = o["sheet"], o["ref"]
        cites = _citations(book, walker.leaves(sheet, ref))
        outs.append(ManifestOutput(id=o["id"], sheet=sheet, ref=ref, units=o["units"], citations=cites))
        cell = book.sheets.get(sheet, {}).get(_ref_cell(ref))
        values[o["id"]] = cell.value if cell else None
    man = ModelManifest(workbook_sha256=_sha(data), outputs=outs)
    return ModelManifest.from_dict(man.to_dict()), values


def export(data: bytes, meta: dict) -> ModelManifest:
    return export_with_values(data, meta)[0]


def to_json(manifest: ModelManifest) -> str:
    return json.dumps(manifest.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)


def historical_ids(data: bytes, meta: dict) -> set:
    """Output ids that derive from reported figures and so must carry at least one citation."""
    book = xlsx.read(data)
    return {o["id"] for o in outputs_for(book, meta) if o.get("historical")}
