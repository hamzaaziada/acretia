"""Stdlib inline-XBRL and xBRL-JSON reader (S8.5). Used for ESEF filings and Companies House accounts.

`parse_ixbrl(xhtml)` reads `ix:nonFraction` / `ix:nonNumeric` facts with their contexts and units; `parse_xbrl_json(json)`
reads the OIM xBRL-JSON that filings.xbrl.org publishes. Both return an `IxbrlDoc` of `Fact`s, and `to_statements`
maps the dimensionless numeric facts to `om.statements` keys through `om.intl.concepts.concept_to_key`.

Numbers: displayed text is parsed by the `format` attribute (ixt / ixt2 / ixt3 / ixt4 local names), multiplied by
10**scale, then negated when sign="-". Parsing is deterministic and uses Decimal; a value that cannot be parsed
becomes `value=None` with a warning, never a guess. Period ends are inclusive dates: an xBRL-JSON duration end is
exclusive (2026-07-01T00:00:00 means 30 June) and so is a date-only instant (the same string means a 30 June balance). Input is untrusted data, never instructions.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from datetime import date, timedelta

from . import concepts

_STD_DIMS = {"concept", "entity", "period", "unit", "language", "decimals", "note"}


class IxbrlError(ValueError):
    pass


@dataclass(frozen=True)
class Fact:
    concept: str                    # qualified name as written, e.g. "ifrs-full:Revenue"
    key: str | None                 # om.statements / om.intl key, or None when unmapped
    value: float | None             # numeric facts only (scaled, signed)
    text: str | None                # non-numeric facts (truncated), and the raw display text of numeric ones
    unit: str | None
    decimals: str | None
    period_start: str | None
    period_end: str | None          # inclusive end date, or the instant
    entity: str | None
    dims: tuple = ()                # ((dimension, member), ...) sorted; empty = consolidated / default
    context: str | None = None
    fact_id: str | None = None

    @property
    def numeric(self) -> bool:
        return self.unit is not None


@dataclass
class IxbrlDoc:
    facts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    kind: str = "ixbrl"

    def numeric(self, dimensionless: bool = True):
        return [f for f in self.facts if f.numeric and f.value is not None and (not dimensionless or not f.dims)]

    def by_concept(self, qname: str):
        return [f for f in self.facts if f.concept == qname]


# ------------------------------------------------------------------------------------------ number formats
def _norm_fmt(fmt: str | None) -> str:
    return re.sub(r"[^a-z]", "", (fmt or "").split(":")[-1].lower())


def parse_number(text: str, fmt: str | None = None) -> Decimal:
    """Displayed text -> Decimal (unscaled, unsigned). Raises IxbrlError for an unknown format or unreadable text."""
    f = _norm_fmt(fmt)
    s = (text or "").replace(" ", " ").replace(" ", " ").strip()
    if f in ("zerodash", "fixedzero"):
        return Decimal(0)
    if f in ("", "numdotdecimal", "numdotdecimalin"):
        s = s.replace(",", "").replace(" ", "")
    elif f in ("numcommadecimal", "numspacecomma", "numunitdecimal"):
        s = s.replace(".", "").replace(" ", "").replace(",", ".")
    elif f == "numspacedot":
        s = s.replace(" ", "").replace(",", "")
    else:
        raise IxbrlError(f"unsupported number format {fmt!r}")
    if s in ("", "."):
        raise IxbrlError(f"empty number {text!r}")
    try:
        return Decimal(s)
    except InvalidOperation as e:
        raise IxbrlError(f"unreadable number {text!r} ({fmt})") from e


def _scaled(text, fmt, scale, sign) -> float:
    d = parse_number(text, fmt)
    if scale:
        d = d.scaleb(int(scale))
    return float(-d if sign == "-" else d)


# ------------------------------------------------------------------------------------------ inline XBRL
def _local(tag: str) -> str:
    return tag.split(":")[-1].lower()


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contexts: dict[str, dict] = {}
        self.units: dict[str, str] = {}
        self.raw: list[dict] = []
        self._open: list[dict] = []
        self._ctx = None
        self._unit = None
        self._dest = None            # which context/unit text node is being read

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_starttag(self, tag, attrs):
        t, a = _local(tag), {k: (v or "") for k, v in attrs}
        if t in ("nonfraction", "nonnumeric"):
            self._open.append({"t": t, "a": a, "buf": []})
        elif t == "context":
            self._ctx = {"id": a.get("id"), "entity": "", "start": None, "end": None, "instant": None, "dims": []}
        elif t == "unit":
            self._unit = {"id": a.get("id"), "num": [], "den": [], "in_den": False}
        elif self._ctx is not None and t in ("identifier", "startdate", "enddate", "instant"):
            self._dest = t
        elif self._ctx is not None and t in ("explicitmember", "typedmember"):
            self._ctx["dims"].append([a.get("dimension", ""), ""])
            self._dest = "member"
        elif self._unit is not None:
            if t == "unitdenominator":
                self._unit["in_den"] = True
            elif t == "measure":
                self._dest = "measure"

    def handle_endtag(self, tag):
        t = _local(tag)
        if t in ("nonfraction", "nonnumeric") and self._open:
            for i in range(len(self._open) - 1, -1, -1):
                if self._open[i]["t"] == t:
                    el = self._open.pop(i)
                    el["text"] = " ".join("".join(el["buf"]).split())
                    self.raw.append(el)
                    break
        elif t == "context" and self._ctx is not None:
            if self._ctx["id"]:
                self.contexts[self._ctx["id"]] = self._ctx
            self._ctx = None
        elif t == "unit" and self._unit is not None:
            u = self._unit
            num = "*".join(u["num"]) or ""
            self.units[u["id"]] = f"{num}/{'*'.join(u['den'])}" if u["den"] else num
            self._unit = None
        elif t == "unitdenominator" and self._unit is not None:
            self._unit["in_den"] = False
        if t in ("identifier", "startdate", "enddate", "instant", "explicitmember", "typedmember", "measure"):
            self._dest = None

    def handle_data(self, data):
        for el in self._open:
            el["buf"].append(data)
        d = self._dest
        if d is None:
            return
        if d == "member" and self._ctx is not None:
            self._ctx["dims"][-1][1] += data
        elif d == "measure" and self._unit is not None:
            (self._unit["den"] if self._unit["in_den"] else self._unit["num"]).append(data.strip())
        elif self._ctx is not None:
            c = self._ctx
            if d == "identifier":
                c["entity"] += data.strip()
            else:
                slot = {"startdate": "start", "enddate": "end", "instant": "instant"}[d]
                c[slot] = (c[slot] or "") + data.strip()


def _is_true(v) -> bool:
    return str(v).strip().lower() in ("true", "1")


def parse_ixbrl(data: bytes | str, labels: dict | None = None) -> IxbrlDoc:
    """Inline XBRL (.xhtml/.html) -> IxbrlDoc. `labels` optionally maps an extension qname to its English label."""
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else data
    p = _Parser()
    p.feed(text)
    p.close()
    doc = IxbrlDoc(kind="ixbrl")
    for el in p.raw:
        a, name = el["a"], el["a"].get("name", "")
        ctx = p.contexts.get(a.get("contextref", ""))
        if not name or ctx is None:
            doc.warnings.append(f"fact {name or '?'} has no usable context ({a.get('contextref')})")
            continue
        end = ctx["instant"] or ctx["end"]
        dims = tuple(sorted((d.strip(), m.strip()) for d, m in ctx["dims"]))
        key = concepts.concept_to_key(name, label=(labels or {}).get(name))
        unit, value, txt = None, None, el["text"]
        if el["t"] == "nonfraction":
            unit = p.units.get(a.get("unitref", ""), a.get("unitref") or "")
            if _is_true(a.get("xsi:nil", "")):
                pass
            else:
                try:
                    value = _scaled(el["text"], a.get("format"), a.get("scale", "0") or 0, a.get("sign"))
                except IxbrlError as e:
                    doc.warnings.append(f"{name}: {e}")
        doc.facts.append(Fact(name, key, value, txt[:500], unit if el["t"] == "nonfraction" else None, a.get("decimals") or None,
                              None if ctx["instant"] else ctx["start"], end, ctx["entity"] or None, dims, a.get("contextref"), a.get("id")))
    return doc


# ------------------------------------------------------------------------------------------ xBRL-JSON
def _oim_period(p: str) -> tuple[str | None, str | None]:
    """OIM period -> (start, inclusive end). Date-only ends (duration end, instant) are end-of-day, written as the next
    day at T00:00:00 (observed on filings.xbrl.org 2026-11-17), so one day is subtracted; T24:00:00 keeps its date."""
    def d(s):
        return date.fromisoformat(s[:10]), s[10:]
    if "/" in p:
        s, e = p.split("/")
        (sd, _), (ed, et) = d(s), d(e)
        if et in ("", "T00:00:00", "T00:00:00Z"):
            ed -= timedelta(days=1)
        return sd.isoformat(), ed.isoformat()
    ed, et = d(p)
    if et in ("", "T00:00:00", "T00:00:00Z"):      # a date-only instant is end of day: Arelle writes 2026-07-01T00:00:00 for 30 June
        ed -= timedelta(days=1)
    return None, ed.isoformat()


def parse_xbrl_json(data, labels: dict | None = None) -> IxbrlDoc:
    """OIM xBRL-JSON (dict, str or bytes) -> IxbrlDoc. Numeric facts are those with a `unit` dimension."""
    obj = data if isinstance(data, dict) else json.loads(data)
    facts = obj.get("facts")
    if not isinstance(facts, dict):
        raise IxbrlError("not xBRL-JSON: no 'facts' object")
    doc = IxbrlDoc(kind="xbrl-json")
    for fid, f in facts.items():
        dm = f.get("dimensions", {})
        name, per = dm.get("concept"), dm.get("period")
        if not name or not per:
            doc.warnings.append(f"fact {fid} lacks concept or period")
            continue
        start, end = _oim_period(per)
        unit = dm.get("unit")
        value, raw = None, f.get("value")
        if unit is not None and raw is not None:
            try:
                value = float(Decimal(str(raw)))
            except InvalidOperation:
                doc.warnings.append(f"{name}: unreadable value {raw!r}")
        dims = tuple(sorted((k, str(v)) for k, v in dm.items() if k not in _STD_DIMS))
        doc.facts.append(Fact(name, concepts.concept_to_key(name, label=(labels or {}).get(name)), value,
                              None if raw is None else str(raw)[:500], unit, None if f.get("decimals") is None else str(f["decimals"]),
                              start, end, dm.get("entity"), dims, None, fid))
    return doc


def parse(data) -> IxbrlDoc:
    """Autodetect xBRL-JSON versus inline XBRL."""
    raw = data if isinstance(data, (bytes, bytearray, str)) else json.dumps(data)
    head = (raw[:200].decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw[:200]).lstrip()
    return parse_xbrl_json(raw) if head.startswith("{") else parse_ixbrl(raw)


def to_statements(doc: IxbrlDoc) -> dict:
    """Dimensionless numeric facts -> {"values": {key: {period_end: value}}, "rows", "unmapped", "conflicts"}.
    The first fact seen for a (key, period) wins; a later different value is listed in `conflicts`."""
    values: dict[str, dict[str, float]] = {}
    rows, unmapped, conflicts = [], set(), []
    for f in doc.numeric(dimensionless=True):
        if f.key is None:
            unmapped.add(f.concept)
            continue
        cur = values.setdefault(f.key, {})
        if f.period_end in cur:
            if abs(cur[f.period_end] - f.value) > 1e-9:
                conflicts.append({"key": f.key, "period_end": f.period_end, "kept": cur[f.period_end], "dropped": f.value,
                                  "concept": f.concept})
            continue
        cur[f.period_end] = f.value
        rows.append({"key": f.key, "period_end": f.period_end, "period_start": f.period_start, "value": f.value,
                     "unit": f.unit, "concept": f.concept})
    return {"values": values, "rows": rows, "unmapped": sorted(unmapped), "conflicts": conflicts}
