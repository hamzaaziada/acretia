"""Theme tokens, fonts, sizes and the 12-column grid (single source: om/house.py)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from om import house

CANVAS_W, CANVAS_H = house.CANVAS
MARGIN_X = house.GRID["margin_x"]
GUTTER = 0.2
COLS = 12

SCHEME_SLOTS = {
    "text": "dk1", "background": "lt1", "secondary": "dk2", "panel": "lt2", "accent": "accent1",
    "series2": "accent2", "series3": "accent3", "light": "accent4", "positive": "accent5", "negative": "accent6",
}
SIZES = {"title": 24, "body": 14, "label": 12, "note": 10, "stat": 40, "divider": 40, "cover": 44}


def col_width() -> float:
    return (CANVAS_W - 2 * MARGIN_X - (COLS - 1) * GUTTER) / COLS


def grid_x(col: int) -> float:
    """Left edge of column `col` (0..11); `col == 12` gives the right margin edge."""
    if not 0 <= col <= COLS:
        raise ValueError(f"column {col} outside 0..{COLS}")
    if col == COLS:
        return round(CANVAS_W - MARGIN_X, 2)
    return round(MARGIN_X + col * (col_width() + GUTTER), 2)


def grid_w(span: int) -> float:
    if not 1 <= span <= COLS:
        raise ValueError(f"span {span} outside 1..{COLS}")
    return round(span * col_width() + (span - 1) * GUTTER, 2)


POSITIVE_ACCESSIBLE = "#0B7A54"


@dataclass
class Theme:
    """Theme tokens. D-S3-12: the deck theme's `positive` is #0B7A54 (5.35:1 on white, 4.82:1 on the panel grey), not the
    v1 house green #0F8A5F (4.36:1), so positive text and fills under white labels pass WCAG AA 4.5:1 at small sizes.
    The v1 palette in om/house.py is unchanged."""
    name: str
    colors: dict[str, str]
    fonts: dict[str, str]
    sizes: dict[str, float] = field(default_factory=lambda: dict(SIZES))
    grid: dict[str, float] = field(default_factory=dict)

    @classmethod
    def house(cls) -> "Theme":
        h = house.FONTS
        return cls(
            name="house",
            colors={**house.PALETTE, "positive": POSITIVE_ACCESSIBLE},
            fonts={"major": h["heading"], "minor": h["body"], "major_cs": "Arial", "minor_cs": "Arial"},
            sizes=dict(SIZES),
            grid={**house.GRID, "gutter": GUTTER, "cols": COLS, "canvas_w": CANVAS_W, "canvas_h": CANVAS_H},
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Theme":
        return cls(**d)
