"""Typed, validated, JSON-round-trippable contracts shared by every pipeline stage (stdlib only).

Every contract is a dataclass with ``to_dict`` / ``from_dict`` / ``validate`` / ``to_json`` / ``from_json``.
A class declares ``SCHEMA`` (field name -> validator); the shared ``Contract`` base does the rest.
Invalid input raises ``ContractError`` whose message starts with a field path, e.g.
``ModelManifest.outputs[2].citations[0].bbox_norm[1]: must be <= 1, got 1.01``.
Unknown keys are rejected, ``bool`` is never accepted as a number, NaN/inf are never accepted.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from datetime import datetime
from typing import Any, ClassVar


class ContractError(ValueError):
    """Raised for any contract violation; the message begins with the offending field path."""


def sha256_hex(data) -> str:
    """Lowercase hex SHA-256 of ``str`` (UTF-8) or bytes-like input."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(bytes(data)).hexdigest()


def _err(path, msg):
    raise ContractError(f"{path}: {msg}")


# ---------------------------------------------------------------- validators: (value, path) -> normalized value
def string(min_len=1, pattern=None):
    rx = re.compile(pattern) if pattern else None

    def v(x, p):
        if not isinstance(x, str):
            _err(p, f"expected string, got {type(x).__name__}")
        if len(x) < min_len:
            _err(p, "must not be empty" if min_len == 1 else f"length must be >= {min_len}")
        if rx and not rx.fullmatch(x):
            _err(p, f"does not match {pattern!r}: {x!r}")
        return x
    return v


def integer(lo=None, hi=None):
    def v(x, p):
        if isinstance(x, bool) or not isinstance(x, int):
            _err(p, f"expected integer, got {type(x).__name__}")
        if lo is not None and x < lo:
            _err(p, f"must be >= {lo}, got {x}")
        if hi is not None and x > hi:
            _err(p, f"must be <= {hi}, got {x}")
        return x
    return v


def number(lo=None, hi=None):
    def v(x, p):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            _err(p, f"expected number, got {type(x).__name__}")
        if not math.isfinite(x):
            _err(p, f"must be finite, got {x}")
        if lo is not None and x < lo:
            _err(p, f"must be >= {lo}, got {x}")
        if hi is not None and x > hi:
            _err(p, f"must be <= {hi}, got {x}")
        return float(x)
    return v


def boolean(x, p):
    if not isinstance(x, bool):
        _err(p, f"expected boolean, got {type(x).__name__}")
    return x


def enum(*choices):
    def v(x, p):
        if not isinstance(x, str) or x not in choices:
            _err(p, f"must be one of {list(choices)}, got {x!r}")
        return x
    return v


def optional(inner):
    return lambda x, p: None if x is None else inner(x, p)


def json_value(x, p):
    """Any JSON value (finite numbers, string keys)."""
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, (int, float)):
        return number()(x, p) if isinstance(x, float) else x
    if isinstance(x, (list, tuple)):
        return [json_value(e, f"{p}[{i}]") for i, e in enumerate(x)]
    if isinstance(x, dict):
        return {_key(k, p): json_value(e, f"{p}[{k!r}]") for k, e in x.items()}
    _err(p, f"not JSON-serialisable: {type(x).__name__}")


def scalar(x, p):
    if isinstance(x, (list, tuple, dict)):
        _err(p, f"expected scalar, got {type(x).__name__}")
    return json_value(x, p)


def _key(k, p):
    if not isinstance(k, str):
        _err(p, f"keys must be strings, got {k!r}")
    return k


def listing(item, min_len=0, unique=None):
    """List of ``item``; ``unique`` = True (items distinct) or an attribute name (items' attr distinct)."""
    def v(x, p):
        if not isinstance(x, (list, tuple)):
            _err(p, f"expected list, got {type(x).__name__}")
        if len(x) < min_len:
            _err(p, f"needs at least {min_len} item(s)")
        out, seen = [], set()
        for i, e in enumerate(x):
            e = item(e, f"{p}[{i}]")
            if unique:
                k = getattr(e, unique) if isinstance(unique, str) else e
                if k in seen:
                    _err(f"{p}[{i}]" + (f".{unique}" if isinstance(unique, str) else ""), f"duplicate {k!r}")
                seen.add(k)
            out.append(e)
        return out
    return v


def mapping(key, val):
    def v(x, p):
        if not isinstance(x, dict):
            _err(p, f"expected object, got {type(x).__name__}")
        return {key(_key(k, p), f"{p}[{k!r}]"): val(e, f"{p}[{k!r}]") for k, e in x.items()}
    return v


def nested(cls):
    return lambda x, p: cls._parse(x, p)


def bbox(x, p):
    if not isinstance(x, (list, tuple)) or len(x) != 4:
        _err(p, "expected [x0, y0, x1, y1]")
    c = tuple(number(0, 1)(e, f"{p}[{i}]") for i, e in enumerate(x))
    if c[0] > c[2]:
        _err(f"{p}[2]", f"x1 ({c[2]}) must be >= x0 ({c[0]})")
    if c[1] > c[3]:
        _err(f"{p}[3]", f"y1 ({c[3]}) must be >= y0 ({c[1]})")
    return c


def timestamp(x, p):
    string()(x, p)
    try:
        datetime.fromisoformat(x.replace("Z", "+00:00"))
    except ValueError:
        _err(p, f"not an ISO-8601 timestamp: {x!r}")
    return x


HASH = string(pattern=r"[0-9a-f]{64}")
_LOCAL = r"\$?[A-Z]{1,3}\$?[1-9][0-9]*"
_SHEET = r"(?:'[^']+'|[^'!:\s]+)"
CELL = string(pattern=_LOCAL)
LOCAL_REF = string(pattern=f"{_LOCAL}(?::{_LOCAL})?")                      # A1 or A1:B9
NODE_REF = string(pattern=f"{_SHEET}!{_LOCAL}")                             # Sheet!A1
SHEET_REF = string(pattern=f"{_SHEET}!{_LOCAL}(?::{_LOCAL})?")              # Sheet!A1 or Sheet!A1:B9
NAME = string(pattern=r"[A-Za-z_][A-Za-z0-9_.]*")
ID = string(pattern=r"[^\s]+")
STATUS = ("queued", "running", "succeeded", "failed", "cancelled")
SEVERITIES = ("critical", "high", "medium", "low", "info")
MODEL_TYPES = ("three_statement", "dcf", "lbo", "merger", "comps")
PATCH_OPS = ("move", "resize", "set_text", "set_font_size", "set_style", "delete", "reorder")
SLIDE_LAYOUTS = ("title", "section", "bullets", "two_column", "chart", "table", "image")
BOX_KINDS = ("title", "body", "text", "chart", "table", "image", "footer")


# ---------------------------------------------------------------- base class
class Contract:
    SCHEMA: ClassVar[dict]

    @classmethod
    def _parse(cls, d, path):
        if not isinstance(d, dict):
            _err(path, f"expected object, got {type(d).__name__}")
        known = {f.name: f for f in fields(cls)}
        for k in d:
            if k not in known:
                _err(f"{path}.{k}", "unknown field")
        kw = {}
        for n, f in known.items():
            if n in d:
                kw[n] = cls.SCHEMA[n](d[n], f"{path}.{n}")
            elif f.default is MISSING and f.default_factory is MISSING:
                _err(f"{path}.{n}", "required field missing")
        obj = cls(**kw)
        obj._check(path)
        return obj

    def _check(self, path):
        """Cross-field rules; override. Raise via ``_err``."""

    @classmethod
    def from_dict(cls, d):
        return cls._parse(d, cls.__name__)

    def to_dict(self):
        return _plain(self)

    def validate(self):
        type(self)._parse(self.to_dict(), type(self).__name__)
        return self

    def to_json(self, **kw):
        return json.dumps(self.to_dict(), allow_nan=False, sort_keys=True, **kw)

    @classmethod
    def from_json(cls, s):
        try:
            d = json.loads(s)
        except ValueError as e:
            raise ContractError(f"{cls.__name__}: invalid JSON ({e})") from None
        return cls.from_dict(d)


def _plain(x):
    if is_dataclass(x) and not isinstance(x, type):
        return {f.name: _plain(getattr(x, f.name)) for f in fields(x)}
    if isinstance(x, (list, tuple)):
        return [_plain(e) for e in x]
    if isinstance(x, dict):
        return {k: _plain(e) for k, e in x.items()}
    return x


def _list():
    return field(default_factory=list)


def _dict():
    return field(default_factory=dict)


# ---------------------------------------------------------------- citations & workbook
@dataclass
class Citation(Contract):
    doc_id: str
    sha256_span_hash: str
    page: int | None = None
    bbox_norm: tuple | None = None
    quote: str = ""
    source_url: str | None = None
    sheet: str | None = None
    cell: str | None = None
    SCHEMA: ClassVar = {
        "doc_id": ID, "sha256_span_hash": HASH, "page": optional(integer(1)), "bbox_norm": optional(bbox),
        "quote": string(0), "source_url": optional(string(pattern=r"https?://\S+|file:///\S+")),
        "sheet": optional(string()), "cell": optional(LOCAL_REF)}


@dataclass
class GraphNode(Contract):
    formula: str | None = None
    value: Any = None
    SCHEMA: ClassVar = {"formula": optional(string(pattern=r"=.+")), "value": scalar}


@dataclass
class WorkbookGraph(Contract):
    nodes: dict = _dict()          # "Sheet!A1" -> GraphNode
    edges: dict = _dict()          # "Sheet!A1" -> ["Sheet!B2", "Sheet!C1:C9", ...] (precedents)
    names: dict = _dict()          # defined name -> "Sheet!A1" / range
    SCHEMA: ClassVar = {
        "nodes": mapping(NODE_REF, nested(GraphNode)),
        "edges": mapping(NODE_REF, listing(SHEET_REF, unique=True)),
        "names": mapping(NAME, SHEET_REF)}

    def _check(self, path):
        for k in self.edges:
            if k not in self.nodes:
                _err(f"{path}.edges[{k!r}]", "edge source is not a node")


# ---------------------------------------------------------------- models
@dataclass
class ModelSpec(Contract):
    ticker: str
    model_type: str
    years: list = _list()
    company: str = ""
    scenarios: list = field(default_factory=lambda: ["base"])
    assumptions: dict = _dict()
    SCHEMA: ClassVar = {
        "ticker": string(pattern=r"[A-Z0-9][A-Z0-9.\-]{0,11}"), "model_type": enum(*MODEL_TYPES),
        "years": listing(integer(1900, 2200), min_len=1), "company": string(0),
        "scenarios": listing(string(), min_len=1, unique=True), "assumptions": mapping(string(), json_value)}

    def _check(self, path):
        if any(a >= b for a, b in zip(self.years, self.years[1:])):
            _err(f"{path}.years", "must be strictly increasing")


@dataclass
class ManifestOutput(Contract):
    id: str
    sheet: str
    ref: str
    units: str
    citations: list = _list()
    SCHEMA: ClassVar = {"id": ID, "sheet": string(), "ref": LOCAL_REF, "units": string(),
                        "citations": listing(nested(Citation))}


@dataclass
class ModelManifest(Contract):
    workbook_sha256: str
    outputs: list = _list()
    SCHEMA: ClassVar = {"workbook_sha256": HASH, "outputs": listing(nested(ManifestOutput), unique="id")}


# ---------------------------------------------------------------- slides
@dataclass
class SlideSpec(Contract):
    id: str
    layout: str
    title: str = ""
    bullets: list = _list()
    notes: str = ""
    citations: list = _list()
    data: dict = _dict()
    SCHEMA: ClassVar = {
        "id": ID, "layout": enum(*SLIDE_LAYOUTS), "title": string(0), "bullets": listing(string(0)),
        "notes": string(0), "citations": listing(nested(Citation)), "data": mapping(string(), json_value)}


@dataclass
class DeckSpec(Contract):
    deck_id: str
    title: str
    slides: list = _list()
    aspect: str = "16:9"
    template: str = ""
    SCHEMA: ClassVar = {"deck_id": ID, "title": string(), "slides": listing(nested(SlideSpec), unique="id"),
                        "aspect": enum("16:9", "4:3"), "template": string(0)}


@dataclass
class LayoutBox(Contract):
    id: str
    kind: str
    x: float
    y: float
    w: float
    h: float
    SCHEMA: ClassVar = {"id": ID, "kind": enum(*BOX_KINDS), "x": number(0), "y": number(0),
                        "w": number(0), "h": number(0)}


@dataclass
class SolvedSlideLayout(Contract):
    slide_id: str
    unit: str = "norm"             # "norm" (page is 1x1) or "emu"
    width: float = 1.0
    height: float = 1.0
    boxes: list = _list()
    SCHEMA: ClassVar = {"slide_id": ID, "unit": enum("norm", "emu"), "width": number(0), "height": number(0),
                        "boxes": listing(nested(LayoutBox), unique="id")}

    def _check(self, path):
        if self.unit == "norm" and (self.width != 1 or self.height != 1):
            _err(f"{path}.width", "normalised layouts must have width == height == 1")
        for i, b in enumerate(self.boxes):
            if b.x + b.w > self.width:
                _err(f"{path}.boxes[{i}].w", f"box exceeds page width ({b.x + b.w} > {self.width})")
            if b.y + b.h > self.height:
                _err(f"{path}.boxes[{i}].h", f"box exceeds page height ({b.y + b.h} > {self.height})")


@dataclass
class PatchOp(Contract):
    op: str
    target: str
    args: dict = _dict()
    SCHEMA: ClassVar = {"op": enum(*PATCH_OPS), "target": ID, "args": mapping(string(), json_value)}


@dataclass
class SlideRepairPatch(Contract):
    slide_index: int
    ops: list = _list()
    reason: str = ""
    SCHEMA: ClassVar = {"slide_index": integer(0), "ops": listing(nested(PatchOp), min_len=1),
                        "reason": string(0)}


# ---------------------------------------------------------------- grids
@dataclass
class GridQuestion(Contract):
    id: str
    text: str
    SCHEMA: ClassVar = {"id": ID, "text": string()}


@dataclass
class GridSpec(Contract):
    grid_id: str
    documents: list = _list()      # doc ids
    questions: list = _list()
    SCHEMA: ClassVar = {"grid_id": ID, "documents": listing(ID, unique=True),
                        "questions": listing(nested(GridQuestion), unique="id")}


@dataclass
class GridCell(Contract):
    doc_id: str
    question_id: str
    answer: str
    content_hash: str
    citations: list = _list()
    confidence: float | None = None
    SCHEMA: ClassVar = {"doc_id": ID, "question_id": ID, "answer": string(0), "content_hash": HASH,
                        "citations": listing(nested(Citation)), "confidence": optional(number(0, 1))}


# ---------------------------------------------------------------- deal memory, jobs, validation
@dataclass
class MemoryVersion(Contract):
    version: int
    created_at: str
    note: str = ""
    SCHEMA: ClassVar = {"version": integer(1), "created_at": timestamp, "note": string(0)}


@dataclass
class DealMemory(Contract):
    deal_id: str
    name: str
    definitions: dict = _dict()
    formatting: dict = _dict()
    versions: list = _list()
    SCHEMA: ClassVar = {"deal_id": ID, "name": string(), "definitions": mapping(string(), string(0)),
                        "formatting": mapping(string(), json_value), "versions": listing(nested(MemoryVersion))}

    def _check(self, path):
        for i, (a, b) in enumerate(zip(self.versions, self.versions[1:]), 1):
            if b.version <= a.version:
                _err(f"{path}.versions[{i}].version", "versions must be strictly increasing")


@dataclass
class JobStep(Contract):
    name: str
    status: str = "queued"
    detail: str = ""
    SCHEMA: ClassVar = {"name": string(), "status": enum(*STATUS), "detail": string(0)}


@dataclass
class Job(Contract):
    id: str
    kind: str
    status: str = "queued"
    steps: list = _list()
    attempts: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    SCHEMA: ClassVar = {"id": ID, "kind": string(), "status": enum(*STATUS), "steps": listing(nested(JobStep)),
                        "attempts": integer(0), "tokens": integer(0), "cost_usd": number(0),
                        "error": optional(string(0))}


@dataclass
class Finding(Contract):
    rule: str
    severity: str
    message: str
    location: str = ""
    SCHEMA: ClassVar = {"rule": string(), "severity": enum(*SEVERITIES), "message": string(),
                        "location": string(0)}


@dataclass
class ValidationReport(Contract):
    target: str
    passed: bool
    findings: list = _list()
    SCHEMA: ClassVar = {"target": string(), "passed": boolean, "findings": listing(nested(Finding))}

    def _check(self, path):
        for i, f in enumerate(self.findings):
            if self.passed and f.severity in ("critical", "high"):
                _err(f"{path}.passed", f"cannot pass with a {f.severity} finding (findings[{i}])")


CONTRACTS = (Citation, WorkbookGraph, ModelSpec, ModelManifest, SlideSpec, SolvedSlideLayout, SlideRepairPatch,
             DeckSpec, GridSpec, GridCell, DealMemory, Job, ValidationReport)
