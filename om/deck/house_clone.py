"""Firm template cloner: a client .potx/.pptx (plus 2-3 sample decks) -> HouseProfile (S3.9).

Deterministic, no LLM, no network. Every value read from the client is range-checked; anything outside a sane
range falls back to the house value and says so in ``evidence``.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field

from lxml import etree
from pptx import Presentation
from pptx.util import Emu

from om.deck.theme import SCHEME_SLOTS, Theme

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS = {"a": _A}
EMU = 914400.0
_SLOT_TO_TOKEN = {v: k for k, v in SCHEME_SLOTS.items()}
TITLE_RANGE = (18.0, 40.0)
BODY_RANGE = (9.0, 24.0)
MIN_CONTRAST = 4.5


class CloneError(ValueError):
    pass


def _lum(hexv: str) -> float:
    h = hexv.lstrip("#")
    out = []
    for i in (0, 2, 4):
        v = int(h[i:i + 2], 16) / 255
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(fg: str, bg: str) -> float:
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


class ClientTheme(Theme):
    """A Theme that can also be called, so ``profile.theme`` and ``profile.theme()`` both work."""

    def __call__(self) -> Theme:
        return Theme.from_dict(self.to_dict())


def _as_client(t: Theme) -> ClientTheme:
    return ClientTheme(**t.to_dict())


@dataclass
class HouseProfile:
    theme: Theme
    grid: dict
    sizes: dict
    layout_name: str
    evidence: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.theme, ClientTheme):
            self.theme = _as_client(self.theme)

    def to_dict(self) -> dict:
        return {"theme": Theme.to_dict(self.theme), "grid": dict(self.grid), "sizes": dict(self.sizes),
                "layout_name": self.layout_name, "evidence": list(self.evidence)}

    @classmethod
    def from_dict(cls, d: dict) -> "HouseProfile":
        return cls(theme=Theme.from_dict(d["theme"]), grid=dict(d["grid"]), sizes=dict(d["sizes"]),
                   layout_name=d["layout_name"], evidence=list(d.get("evidence", [])))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1, sort_keys=True)

    @classmethod
    def load(cls, path: str) -> "HouseProfile":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


# ---------------------------------------------------------------- reading the template

def _open(path: str):
    with open(path, "rb") as fh:
        data = fh.read()
    if path.lower().endswith((".potx", ".potm")):
        src = zipfile.ZipFile(io.BytesIO(data))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                blob = src.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    blob = re.sub(rb"presentationml\.template(\.macroEnabled)?\.main\+xml",
                                  b"presentationml.presentation.main+xml", blob)
                dst.writestr(item, blob)
        data = out.getvalue()
    return Presentation(io.BytesIO(data)), data


def _theme_root(prs):
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    part = prs.slide_master.part.part_related_by(RT.THEME)
    return etree.fromstring(part.blob)


def _slot_hex(el) -> str | None:
    if el is None:
        return None
    s = el.find("a:srgbClr", _NS)
    if s is not None:
        return "#" + s.get("val").upper()
    s = el.find("a:sysClr", _NS)
    if s is not None and s.get("lastClr"):
        return "#" + s.get("lastClr").upper()
    return None


def _ph_kind(shape) -> str | None:
    if not shape.is_placeholder:
        return None
    t = str(shape.placeholder_format.type).split(".")[-1].split(" ")[0]
    return {"TITLE": "title", "CENTER_TITLE": "title", "BODY": "body", "OBJECT": "body", "FOOTER": "footer",
            "SLIDE_NUMBER": "slide_number"}.get(t)


def _box(shape) -> dict | None:
    try:
        if shape.left is None or shape.top is None or not shape.width or not shape.height:
            return None
        return {"x": shape.left / EMU, "y": shape.top / EMU, "w": shape.width / EMU, "h": shape.height / EMU}
    except Exception:
        return None


def _pick_layout(prs):
    best, best_score = None, -1
    for lay in prs.slide_layouts:
        kinds = {_ph_kind(s) for s in lay.placeholders}
        score = ("title" in kinds) * 2 + ("body" in kinds) * 2 + ("footer" in kinds) + ("slide_number" in kinds)
        if "content" in lay.name.lower():
            score += 1
        if score > best_score:
            best, best_score = lay, score
    return best


def _master_title_size(prs) -> float | None:
    root = prs.slide_master._element
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": _A}
    el = root.find(".//p:txStyles/p:titleStyle/a:lvl1pPr/a:defRPr", ns)
    if el is not None and el.get("sz"):
        return int(el.get("sz")) / 100.0
    return None


def _master_body_size(prs) -> float | None:
    root = prs.slide_master._element
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": _A}
    el = root.find(".//p:txStyles/p:bodyStyle/a:lvl1pPr/a:defRPr", ns)
    if el is not None and el.get("sz"):
        return int(el.get("sz")) / 100.0
    return None


# ---------------------------------------------------------------- sample decks

def _is_rule(shape, slide_w: float) -> bool:
    tag = etree.QName(shape._element).localname
    if tag == "cxnSp":
        return (shape.height or 0) <= Emu(12700) and (shape.width or 0) / EMU > 0.5 * slide_w
    if tag == "sp":
        geom = shape._element.find(".//a:prstGeom", _NS)
        if geom is not None and geom.get("prst") == "line":
            return (shape.height or 0) <= Emu(12700) and (shape.width or 0) / EMU > 0.5 * slide_w
    return False


def _sample_stats(paths) -> dict:
    title_sizes, body_sizes, lefts, rules, seen = [], [], [], [], 0
    for p in paths:
        prs, _ = _open(p)
        sw = prs.slide_width / EMU
        for slide in prs.slides:
            seen += 1
            title_shape = None
            for sh in slide.shapes:
                if _ph_kind(sh) == "title" or sh.name.lower().startswith("title"):
                    title_shape = sh
                    break
            for sh in slide.shapes:
                if sh.has_text_frame and sh.text_frame.text.strip():
                    sizes = [r.font.size.pt for para in sh.text_frame.paragraphs for r in para.runs
                             if r.font.size is not None]
                    if title_shape is not None and sh.shape_id == title_shape.shape_id:
                        title_sizes += sizes
                    else:
                        body_sizes += sizes
                    if sh.left is not None:
                        lefts.append(round(sh.left / EMU, 2))
            if title_shape is not None:
                bottom = ((title_shape.top or 0) + (title_shape.height or 0)) / EMU
                has = any(_is_rule(s, sw) and 0 <= s.top / EMU - bottom <= 0.6 for s in slide.shapes)
                rules.append(has)
    mode = lambda xs: Counter(xs).most_common(1)[0][0] if xs else None  # noqa: E731
    return {"slides": seen, "title": mode(title_sizes), "body": mode(body_sizes), "margin": mode(lefts),
            "rule": (sum(rules) * 2 > len(rules)) if rules else None}


# ---------------------------------------------------------------- clone

def clone(template_path: str, sample_decks=()) -> HouseProfile:
    prs, _ = _open(template_path)
    house = Theme.house()
    ev: list[str] = []
    colors, fonts = dict(house.colors), dict(house.fonts)
    grid, sizes = dict(house.grid), dict(house.sizes)

    # colours
    root = _theme_root(prs)
    cs = root.find(".//a:clrScheme", _NS)
    for slot, token in _SLOT_TO_TOKEN.items():
        v = _slot_hex(cs.find(f"a:{slot}", _NS)) if cs is not None else None
        if v:
            colors[token] = v
            ev.append(f"colors.{token}: client {slot} {v}")
        else:
            ev.append(f"colors.{token}: house fallback {colors[token]} (client {slot} missing)")
    if contrast(colors["text"], colors["background"]) < MIN_CONTRAST:
        ev.append(f"colors: client text/background contrast {contrast(colors['text'], colors['background']):.2f} "
                  f"< {MIN_CONTRAST}; house text/background used")
        colors["text"], colors["background"] = house.colors["text"], house.colors["background"]
    if contrast(colors["accent"], colors["background"]) < 3.0:
        ev.append(f"colors.accent: contrast on background {contrast(colors['accent'], colors['background']):.2f} < 3; house accent used")
        colors["accent"] = house.colors["accent"]

    # fonts
    fs = root.find(".//a:fontScheme", _NS)
    for tag, role in (("majorFont", "major"), ("minorFont", "minor")):
        f = fs.find(f"a:{tag}", _NS) if fs is not None else None
        for kind, key in (("latin", role), ("cs", f"{role}_cs")):
            el = f.find(f"a:{kind}", _NS) if f is not None else None
            face = el.get("typeface") if el is not None else ""
            if face and not face.startswith("+"):
                fonts[key] = face
                ev.append(f"fonts.{key}: client {face}")
            else:
                ev.append(f"fonts.{key}: house fallback {fonts[key]} (client empty)")

    # slide size
    w, h = prs.slide_width / EMU, prs.slide_height / EMU
    grid["canvas_w"], grid["canvas_h"] = round(w, 3), round(h, 3)
    if abs(w - house.grid["canvas_w"]) > 0.01 or abs(h - house.grid["canvas_h"]) > 0.01:
        ev.append(f"slide size: client {w:.3f}x{h:.3f} in differs from house {house.grid['canvas_w']}x{house.grid['canvas_h']}")
    else:
        ev.append(f"slide size: client {w:.3f}x{h:.3f} in")

    # layout placeholders
    lay = _pick_layout(prs)
    layout_name = lay.name if lay is not None else ""
    boxes: dict[str, dict] = {}
    if lay is not None:
        for sh in lay.placeholders:
            k, b = _ph_kind(sh), _box(sh)
            if k and b and k not in boxes:
                boxes[k] = b
    ev.append(f"layout: {layout_name or 'none'}")

    def sane(name: str, val: float, lo: float, hi: float) -> bool:
        ok = lo <= val <= hi
        if not ok:
            ev.append(f"grid.{name}: client {val:.2f} outside {lo}..{hi}; house {grid[name]} used")
        return ok

    t = boxes.get("title")
    if t:
        for name, val, lo, hi in (("margin_x", t["x"], 0.2, 1.6), ("title_y", t["y"], 0.1, 1.5),
                                  ("title_h", t["h"], 0.4, 1.6)):
            if sane(name, val, lo, hi):
                grid[name] = round(val, 3)
                ev.append(f"grid.{name}: client title placeholder {val:.3f}")
        # keep the rule/subtitle below the client title box
        if grid["title_y"] + grid["title_h"] + 0.1 > grid["title_rule_y"]:
            grid["title_rule_y"] = round(grid["title_y"] + grid["title_h"] + 0.1, 3)
            grid["subtitle_y"] = round(grid["title_rule_y"] + 0.15, 3)
    else:
        ev.append("grid.title: house fallback (no title placeholder)")
    b = boxes.get("body")
    if b:
        top, bottom = b["y"], b["y"] + b["h"]
        if 1.0 <= top <= 3.5 and top + 1.5 < bottom <= h - 0.3:
            grid["content_top"], grid["content_bottom"] = round(top, 3), round(bottom, 3)
            ev.append(f"grid.content: client body placeholder {top:.3f}..{bottom:.3f}")
        else:
            ev.append(f"grid.content: client body {top:.2f}..{bottom:.2f} outside sane range; house used")
    else:
        ev.append("grid.content: house fallback (no body placeholder)")
    for k, yname in (("footer", "footer_y"), ("slide_number", "footer_y")):
        if k in boxes and 5.5 <= boxes[k]["y"] <= h - 0.1:
            grid[yname] = round(boxes[k]["y"], 3)
            ev.append(f"grid.footer_y: client {k} placeholder {boxes[k]['y']:.3f}")
            break
    for k in ("footer", "slide_number"):
        if k in boxes:
            sizes[f"{k}_box"] = [round(boxes[k][c], 3) for c in ("x", "y", "w", "h")]

    # sizes
    stats = _sample_stats(list(sample_decks)) if sample_decks else {}
    title_sz = stats.get("title") or _master_title_size(prs)
    src = "sample decks modal" if stats.get("title") else "master titleStyle"
    if title_sz is not None:
        if TITLE_RANGE[0] <= title_sz <= TITLE_RANGE[1]:
            sizes["title"] = float(title_sz)
            ev.append(f"sizes.title: {title_sz} pt ({src})")
        else:
            ev.append(f"sizes.title: client {title_sz} pt outside {TITLE_RANGE}; house {sizes['title']} used")
    body_sz = stats.get("body") or _master_body_size(prs)
    if body_sz is not None:
        if BODY_RANGE[0] <= body_sz <= BODY_RANGE[1]:
            sizes["body"] = float(body_sz)
            ev.append(f"sizes.body: {body_sz} pt")
        else:
            ev.append(f"sizes.body: client {body_sz} pt outside {BODY_RANGE}; house {sizes['body']} used")
    if stats:
        m = stats.get("margin")
        if m is not None and 0.2 <= m <= 1.6:
            grid["margin_x"] = float(m)
            ev.append(f"grid.margin_x: sample decks modal left edge {m} in ({stats['slides']} slides)")
        elif m is not None:
            ev.append(f"grid.margin_x: sample modal {m} in outside 0.2..1.6; kept {grid['margin_x']}")
        if stats.get("rule") is not None:
            sizes["title_rule"] = bool(stats["rule"])
            ev.append(f"title rule under title: {'yes' if stats['rule'] else 'no'} (sample decks)")
    theme = Theme(name="client", colors=colors, fonts=fonts, sizes=sizes, grid=grid)
    return HouseProfile(theme=theme, grid=grid, sizes=sizes, layout_name=layout_name, evidence=ev)
