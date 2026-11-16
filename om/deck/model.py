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

    def __post_init__(self) -> None:
        if parse_role(self.id) != self.role:
            raise ValueError(f"element {self.id!r}: role {self.role!r} does not match the id")
        if self.line is not None:
            self.line = (self.line[0], float(self.line[1]))


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
