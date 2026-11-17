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
import unicodedata
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from datetime import date, datetime
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


def iso_date(x, p):
    """Real calendar date, strictly YYYY-MM-DD."""
    string(pattern=r"\d{4}-\d{2}-\d{2}")(x, p)
    try:
        date.fromisoformat(x)
    except ValueError:
        _err(p, f"not a real calendar date: {x!r}")
    return x


def utc_timestamp(x, p):
    """ISO-8601 UTC timestamp ending in 'Z'."""
    string(pattern=r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")(x, p)
    return timestamp(x, p)


FORBIDDEN_LAYOUT_KEYS = frozenset({
    "x", "y", "w", "h", "left", "top", "width", "height", "font", "font_size", "font_family", "color", "colour",
    "fill", "rgb", "hex", "emu", "position", "size_pt"})


def reject_layout_keys(x, p):
    """The model never supplies layout: raise on any forbidden key at any depth of a raw spec tree."""
    if isinstance(x, dict):
        for k, e in x.items():
            if isinstance(k, str) and k.lower() in FORBIDDEN_LAYOUT_KEYS:
                _err(f"{p}.{k}", "layout/style key is forbidden in a spec (the layout solver owns geometry, fonts, colours)")
            reject_layout_keys(e, f"{p}.{k}")
    elif isinstance(x, (list, tuple)):
        for i, e in enumerate(x):
            reject_layout_keys(e, f"{p}[{i}]")


# Action-title lint (deterministic; S3.1/S3.2). A title is a *claim*, not a topic label.
TITLE_MAX_WORDS = 15
TITLE_MAX_CHARS = 110          # about two lines on a 16:9 title box
TITLE_MIN_WORDS = 4
_VERBS = frozenset("""be is are was were been being am will would can could should may might must do does did done have has
had having grow grew grown rise rose risen fall fell fallen drive drove driven lead led support show showed shown
suggest imply mean means need require offer deliver generate produce reduce increase decrease improve expand
accelerate slow weaken strengthen outperform underperform exceed lag trail beat miss cut raise lift lower hold
remain stay become make made take took give gave see saw get got keep kept add pay paid earn earned cost buy bought
sell sold fund finance justify warrant undervalue overvalue price value imply enable allow reflect indicate rank
dominate depend rely face expect forecast project reach hit top gain lose lost win won compress widen narrow
shrink double triple halve convert rebound recover stabilise stabilize peak trough yield return outgrow
""".split())


def _verbish(tok):
    t = tok.lower()
    if not t.isalpha():
        return False
    cands = {t, t[:-1], t[:-2], t[:-3], t[:-3] + "e", t[:-2] + "e", t[:-3] + "y"}
    cands.discard("")
    if cands & _VERBS:
        return True
    return len(t) >= 5 and t.endswith(("ed", "ing")) or t.endswith(("ize", "ise", "ify")) and len(t) >= 6


def _has_emoji(s):
    return any(ord(c) >= 0x1F000 or c in "\u200d\ufe0f" or unicodedata.category(c) == "So" for c in s)


def action_title_lint(x, p):
    """Action title: a one-sentence claim. Rules (all deterministic):

    * <= 15 words and <= 110 characters, no leading/trailing space, single line;
    * no trailing period, no ``!``, no em dash, an en dash only between digits ("2024\u20132026"), no emoji or pictographs;
    * >= 4 words and at least one verb-ish word after the first word (auxiliary/lexicon verb, inflected form of one,
      or a word ending -ed/-ing/-ize/-ise/-ify) so a bare noun phrase such as "Revenue by segment" is rejected.
    """
    string()(x, p)
    if x != x.strip() or "\n" in x or "\r" in x:
        _err(p, "must be a single trimmed line")
    if len(x) > TITLE_MAX_CHARS:
        _err(p, f"title is {len(x)} chars; max {TITLE_MAX_CHARS} (about two lines)")
    words = x.split()
    if len(words) > TITLE_MAX_WORDS:
        _err(p, f"title has {len(words)} words; max {TITLE_MAX_WORDS}")
    if x.endswith("."):
        _err(p, "title must not end with a period")
    if "!" in x:
        _err(p, "title must not contain '!'")
    if "\u2014" in x:
        _err(p, "title must not contain em dashes")
    if "\u2013" in x and re.search(r"(?<!\d)\u2013|\u2013(?!\d)", x):
        _err(p, "title may use an en dash only between digits (2024\u20132026)")
    if _has_emoji(x):
        _err(p, "title must not contain emoji")
    if len(words) < TITLE_MIN_WORDS:
        _err(p, f"title must state a claim of at least {TITLE_MIN_WORDS} words, got {len(words)}")
    if not any(_verbish(w.strip(",;:()%$\"'")) for w in words[1:]):
        _err(p, "title reads as a noun phrase; it must contain a verb stating the claim")
    return x


ARCHETYPE = string(pattern=r"[a-z0-9_]+")
BLOCK_TYPES = ("text", "bullets", "chart", "table", "kpi", "quote", "image_ref", "timeline", "matrix2x2", "process",
               "tree")


def block(x, p):
    """Typed content block: ``{"type": <BLOCK_TYPES>, ...JSON data}``. Geometry/style keys are rejected."""
    if not isinstance(x, dict):
        _err(p, f"expected object, got {type(x).__name__}")
    if "type" not in x:
        _err(f"{p}.type", "required field missing")
    enum(*BLOCK_TYPES)(x["type"], f"{p}.type")
    reject_layout_keys(x, p)
    return {_key(k, p): json_value(e, f"{p}.{k}") for k, e in x.items()}


HASH = string(pattern=r"[0-9a-f]{64}")
_LOCAL = r"\$?[A-Z]{1,3}\$?[1-9][0-9]*"
_SHEET = r"(?:'[^']+'|[^'!:\s]+)"
CELL = string(pattern=_LOCAL)
LOCAL_REF = string(pattern=f"{_LOCAL}(?::{_LOCAL})?")                      # A1 or A1:B9
NODE_REF = string(pattern=f"{_SHEET}!{_LOCAL}")                             # Sheet!A1
SHEET_REF = string(pattern=f"{_SHEET}!{_LOCAL}(?::{_LOCAL})?")              # Sheet!A1 or Sheet!A1:B9
NAME = string(pattern=r"[A-Za-z_][A-Za-z0-9_.]*")
ID = string(pattern=r"[^\s]+")
STATUS = ("queued", "running", "awaiting_review", "succeeded", "failed", "cancelled")
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
    cell_locator: str | None = None      # "Sheet!A1" or "Sheet!A1:B2"
    xbrl_concept: str | None = None      # "us-gaap:Revenues"
    url: str | None = None               # http/https only; ``source_url`` is the legacy alias (must not differ)
    as_of: str | None = None             # YYYY-MM-DD
    SCHEMA: ClassVar = {
        "doc_id": ID, "sha256_span_hash": HASH, "page": optional(integer(1)), "bbox_norm": optional(bbox),
        "quote": string(0), "source_url": optional(string(pattern=r"https?://\S+|file:///\S+")),
        "sheet": optional(string()), "cell": optional(LOCAL_REF), "cell_locator": optional(SHEET_REF),
        "xbrl_concept": optional(string(pattern=r"[A-Za-z][A-Za-z0-9-]*:[A-Za-z][A-Za-z0-9_]*")),
        "url": optional(string(pattern=r"https?://\S+")), "as_of": optional(iso_date)}

    def _check(self, path):
        if self.url and self.source_url and self.url != self.source_url:
            _err(f"{path}.url", "differs from source_url (alias); give one or make them equal")


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
    archetype: str | None = None         # [a-z0-9_]+ ; the layout engine picks geometry from this
    action_title: str | None = None      # one-sentence claim, see ``action_title_lint``
    blocks: list = _list()               # typed content blocks, see ``BLOCK_TYPES``
    sources: list = _list()              # Citations backing the slide
    as_of: str | None = None             # YYYY-MM-DD
    SCHEMA: ClassVar = {
        "id": ID, "layout": enum(*SLIDE_LAYOUTS), "title": string(0), "bullets": listing(string(0)),
        "notes": string(0), "citations": listing(nested(Citation)), "data": mapping(string(), json_value),
        "archetype": optional(ARCHETYPE), "action_title": optional(action_title_lint),
        "blocks": listing(block), "sources": listing(nested(Citation)), "as_of": optional(iso_date)}

    @classmethod
    def _parse(cls, d, path):
        reject_layout_keys(d, path)      # first, so the offending key is reported with its full path
        return super()._parse(d, path)


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


# ---------------------------------------------------------------- evidence ledger & ghost deck
@dataclass
class EvidenceRecord(Contract):
    """One link of a tamper-evident hash chain of tool calls. ``record_hash`` = sha256(canonical JSON of the rest)."""
    job_id: str
    seq: int
    tool: str
    args_sha256: str
    source: str
    timestamp: str
    output_sha256: str
    prev_hash: str
    record_hash: str
    page: int | None = None
    bbox_norm: tuple | None = None
    GENESIS: ClassVar[str] = "0" * 64
    SCHEMA: ClassVar = {
        "job_id": ID, "seq": integer(0), "tool": string(), "args_sha256": HASH, "source": string(),
        "timestamp": utc_timestamp, "output_sha256": HASH, "prev_hash": HASH, "record_hash": HASH,
        "page": optional(integer(1)), "bbox_norm": optional(bbox)}

    def compute_hash(self) -> str:
        body = {k: v for k, v in self.to_dict().items() if k != "record_hash"}
        return sha256_hex(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False))

    def _check(self, path):
        zero = self.prev_hash == self.GENESIS
        if self.seq == 0 and not zero:
            _err(f"{path}.prev_hash", "must be 64 zeros for seq 0")
        if self.seq > 0 and zero:
            _err(f"{path}.prev_hash", "must link to the previous record for seq > 0")
        if self.record_hash != self.compute_hash():
            _err(f"{path}.record_hash", "does not match the hash of the record (tampered or stale)")

    @classmethod
    def seal(cls, **fields_):
        """Build a record, computing ``record_hash`` (``prev_hash`` defaults to the genesis zeros)."""
        fields_.setdefault("prev_hash", cls.GENESIS)
        rec = cls(record_hash=cls.GENESIS, **fields_)
        rec.record_hash = rec.compute_hash()
        return rec.validate()


@dataclass
class GhostTitle(Contract):
    id: str
    action_title: str
    supporting_point: str = ""
    archetype_hint: str | None = None
    SCHEMA: ClassVar = {"id": ID, "action_title": action_title_lint, "supporting_point": string(0),
                        "archetype_hint": optional(ARCHETYPE)}


@dataclass
class GhostDeck(Contract):
    """The storyline as action titles only; must be approved by a person before any slide is rendered."""
    deck_id: str
    title: str
    audience: str
    titles: list = _list()
    approved: bool = False
    approved_by: str | None = None
    SCHEMA: ClassVar = {"deck_id": ID, "title": string(), "audience": string(),
                        "titles": listing(nested(GhostTitle), unique="id"), "approved": boolean,
                        "approved_by": optional(string())}

    def _check(self, path):
        if self.approved and not self.approved_by:
            _err(f"{path}.approved_by", "required when approved is true")
        if self.approved and not self.titles:
            _err(f"{path}.titles", "cannot approve an empty ghost deck")


CONTRACTS = (Citation, WorkbookGraph, ModelSpec, ModelManifest, SlideSpec, SolvedSlideLayout, SlideRepairPatch,
             DeckSpec, GridSpec, GridCell, DealMemory, Job, ValidationReport, EvidenceRecord, GhostTitle, GhostDeck)
