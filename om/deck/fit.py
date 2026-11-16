"""Constraint text fitting: reflow -> tighten -> shrink (1 pt steps) -> structured FitError."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from . import metrics
from .metrics import para_height

TIGHT_SPACING = 0.9


@dataclass
class FitError:
    block_id: str
    words_over: int
    chars_over: int
    message: str


@dataclass
class FitResult:
    ok: bool
    size: float
    paras: list[Any]
    line_spacing: float
    height_in: float
    steps: list[str] = field(default_factory=list)
    error: FitError | None = None


@dataclass
class TitleFit:
    ok: bool
    lines: int
    words_over: int
    line_texts: list[str]


def _chars(paras: list[Any]) -> int:
    return sum(len("".join(r.t for r in p.runs)) for p in paras)


def _drop_last_word(paras: list[Any]) -> list[Any]:
    out = copy.deepcopy(paras)
    for p in reversed(out):
        for r in reversed(p.runs):
            if r.t.strip():
                parts = r.t.rstrip().rsplit(" ", 1)
                r.t = parts[0] if len(parts) > 1 else ""
                return [q for q in out if "".join(x.t for x in q.runs).strip()]
    return out


def _block_no(block_id: str) -> str:
    m = re.search(r"(\d+)$", block_id or "")
    return f" {m.group(1)}" if m else ""


def fit_text(paras: list[Any], w: float, h: float, *, size: float, floor: float, role: str,
             block_id: str, inset: float = 0.0, font: str = "minor") -> FitResult:
    """Fit `paras` into a w x h inch box (insets subtracted)."""
    iw, ih = w - 2 * inset, h - 2 * inset
    ps = copy.deepcopy(paras)

    def height(p: list[Any], sz: float, ls: float, sa: float | None) -> float:
        return para_height(p, iw, sz, font=font, line_spacing=ls, space_after_pt=sa)

    hh = height(ps, size, 1.0, None)
    if hh <= ih:
        return FitResult(True, size, ps, 1.0, hh, ["reflow"])
    steps = ["tighten:space_after"]
    hh = height(ps, size, 1.0, 0.0)
    if hh > ih:
        steps.append("tighten:line_spacing")
        ls = TIGHT_SPACING
        hh = height(ps, size, ls, 0.0)
    else:
        ls = 1.0
    for p in ps:
        p.space_after = 0
    if hh <= ih:
        return FitResult(True, size, ps, ls, hh, steps)
    sz = size
    while sz - 1 >= floor:
        sz -= 1
        hh = height(ps, sz, ls, 0.0)
        if hh <= ih:
            return FitResult(True, sz, ps, ls, hh, steps + [f"shrink:{sz:g}"])
    steps.append(f"shrink:{floor:g}")
    cur, cut = ps, 0
    while cur and cut < 5000 and height(cur, floor, ls, 0.0) > ih:
        cur = _drop_last_word(cur)
        cut += 1
    err = FitError(block_id, cut, max(_chars(ps) - _chars(cur), 0),
                   f"{role} block{_block_no(block_id)} is {cut} words over; cut or split")
    return FitResult(False, floor, ps, ls, height(ps, floor, ls, 0.0), steps, err)


def fit_title(text: str, w: float, *, size: float = 24, max_lines: int = 2,
              font: str = "major", bold: bool = True) -> TitleFit:
    """A title fits if it wraps to at most `max_lines` lines."""
    m = metrics.measure(text, size, w, bold=bold, font=font)
    if m.lines <= max_lines:
        return TitleFit(True, m.lines, 0, m.line_texts)
    kept = " ".join(m.line_texts[:max_lines]).split()
    return TitleFit(False, m.lines, max(len(text.split()) - len(kept), 1), m.line_texts)
