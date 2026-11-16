"""Shared S8 types: a number read from a report (Figure), the extractor's output, and the items/statements that
`om.intl.tieout.release` hands to `om.model3`. Only `om/intl/tieout.py` constructs `IntlStatements`."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .. import statements as _stm
from ..contracts import Citation


@dataclass
class Figure:
    key: str | None
    label: str
    value: float | None
    raw: str
    scale: float
    period_end: date
    period_start: date | None
    statement: str | None
    page: int
    bbox_norm: tuple
    label_bbox: tuple | None
    confidence: float
    ocr_conf: float | None
    source: str                      # "native" | "ocr" | "derived"
    doc_id: str
    sha256_span_hash: str
    status: str = "ok"               # "ok" | "review"
    reasons: list = field(default_factory=list)
    row: int | None = None
    is_total: bool = False
    components: list | None = None


@dataclass
class ExtractedStatements:
    doc_id: str
    company: str
    currency: str
    unit_scale: float
    periods: list
    figures: list
    standard: str | None
    language: str
    fiscal_year_end_month: int
    source_url: str | None = None
    warnings: list = field(default_factory=list)


@dataclass
class IntlItem(_stm.Item):
    citation: Citation | None = None
    confidence: float | None = None
    figure: Figure | None = None

    def source(self) -> str:
        f = self.figure
        if f is None:
            return ""
        x0, y0, x1, y1 = (float(v) for v in f.bbox_norm)
        conf = self.confidence if self.confidence is not None else f.confidence
        return f"p.{f.page} bbox {x0:.4f},{y0:.4f},{x1:.4f},{y1:.4f} conf {conf:.2f} '{f.raw}' {f.doc_id[:12]}"


@dataclass
class IntlStatements(_stm.Statements):
    standard: str | None = None
    language: str = "en"
    basis_flags: dict = field(default_factory=dict)
    review: list = field(default_factory=list)
    release_report: object = None    # om.intl.tieout.TieReport
