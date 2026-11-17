"""SolvedSlide model: the only input to the renderer and the validator's oracle (docs/deck-engine.md)."""
from __future__ import annotations

import base64
import re
from dataclasses import asdict, dataclass, field
from typing import Any

_ID_RE = re.compile(r"^s(\d+)\.([a-z_]+)(?:\.([A-Za-z0-9_.\-]+))?$")


def parse_role(element_id: str) -> str:
    """Role encoded in an element id `s{index}.{role}[.{suffix}]`; ValueError when malformed."""
    m = _ID_RE.match(element_id)
    if not m:
        raise ValueError(f"bad element id {element_id!r}: expected s<index>.<role>[.<suffix>]")
    return m.group(2)


SHAPE_PRST = frozenset({"chevron", "homePlate", "diamond", "ellipse", "triangle", "downTriangle", "rect",
                        "rightArrow"})


@dataclass
class Run:
    t: str
    b: bool = False
    color: str | None = None


@dataclass
class Para:
    runs: list[Run]
    align: str = "l"
    level: int = 0
    bullet: bool = False
    space_after: float = 4


@dataclass
class TextSpec:
    paras: list[Para]
    size: float
    font: str = "minor"
    color: str = "text"
    valign: str = "t"
    inset: float = 0.0
    autofit: bool = False


@dataclass
class Element:
    id: str
    kind: str
    role: str
    x: float
    y: float
    w: float
    h: float
    text: TextSpec | None = None
    fill: str | None = None
    line: tuple[str, float] | None = None
    chart: dict | None = None
    table: dict | None = None
    image: dict | None = None
    binding: dict | None = None
    shape: dict | None = None
    connector: dict | None = None

    def __post_init__(self) -> None:
        if parse_role(self.id) != self.role:
            raise ValueError(f"element {self.id!r}: role {self.role!r} does not match the id")
        if self.line is not None:
            self.line = (self.line[0], float(self.line[1]))
        if self.kind == "shape":
            sh = self.shape
            if not isinstance(sh, dict) or sh.get("prst") not in SHAPE_PRST:
                raise ValueError(f"element {self.id!r}: shape.prst must be one of {sorted(SHAPE_PRST)}")
            if sh.get("rot", 0) not in (0, 90, 180, 270):
                raise ValueError(f"element {self.id!r}: shape.rot must be 0, 90, 180 or 270")
        elif self.shape is not None:
            raise ValueError(f"element {self.id!r}: shape data on kind {self.kind!r}")
        if self.kind == "connector":
            c = self.connector
            if not isinstance(c, dict) or c.get("type") not in ("elbow", "straight"):
                raise ValueError(f"element {self.id!r}: connector.type must be elbow or straight")
            for k in ("start", "end"):
                v = c.get(k)
                if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(n, (int, float)) for n in v)):
                    raise ValueError(f"element {self.id!r}: connector.{k} must be [x, y]")
            self.connector = {**c, "start": list(c["start"]), "end": list(c["end"]), "arrow": bool(c.get("arrow", False))}
        elif self.connector is not None:
            raise ValueError(f"element {self.id!r}: connector data on kind {self.kind!r}")


@dataclass
class SolvedSlide:
    index: int
    archetype: str
    elements: list[Element]
    rtl: bool = False
    notes: str = ""
    visual_type: str = ""
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        for el in d["elements"]:
            img = el.get("image")
            if img and isinstance(img.get("png"), (bytes, bytearray)):
                img["png"] = base64.b64encode(img["png"]).decode("ascii")
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SolvedSlide":
        els = []
        for e in d["elements"]:
            e = dict(e)
            if e.get("text"):
                t = e["text"]
                e["text"] = TextSpec(**{**t, "paras": [
                    Para(**{**p, "runs": [Run(**r) for r in p["runs"]]}) for p in t["paras"]]})
            if e.get("line") is not None:
                e["line"] = tuple(e["line"])
            if e.get("image") and isinstance(e["image"].get("png"), str):
                e["image"] = {**e["image"], "png": base64.b64decode(e["image"]["png"])}
            els.append(Element(**e))
        return cls(**{**d, "elements": els})
