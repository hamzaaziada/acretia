"""Deterministic .pptx validator (S3.7): overflow, bounds, overlap, contrast, font floors, house rules, slop.

Reads python-pptx plus raw XML. Shape role comes from the shape name `s{n}.{role}[.{suffix}]` (deck-engine contract);
foreign shapes get the generic checks only. Findings are dicts `{severity, rule, slide, shape_id, shape_name, message}`.
"""
from __future__ import annotations

import colorsys
import glob
import io
import os
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree

from om import house
from om.deck import slop

EMU = 914400.0
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
_A = "{%s}" % NS["a"]
NAME_RE = re.compile(r"^s(\d+)\.([a-z_]+)(?:\.(.+))?$")
FRAME_ROLES = {"title", "subtitle", "source", "footer", "page_number", "title_rule", "footer_rule"}
BLEED_ROLES = {"visual", "cover", "divider", "decor"}
SCHEME_MAP = {"tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2"}
EFFECT_TAGS = ("gradFill", "outerShdw", "innerShdw", "sp3d", "scene3d", "prstShdw", "reflection", "glow")
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
FIGURE_RE = re.compile(r"(?:[$€£]\d[\d,]*(?:\.\d+)?\s?(?:bn|mm|tn|m|k|b)?(?!\w))|(?:\d[\d,]*(?:\.\d+)?(?:%|x(?!\w)|\s?bps(?!\w)))")


@dataclass
class Report:
    findings: list[dict] = field(default_factory=list)

    @property
    def critical(self) -> int:
        return sum(1 for f in self.findings if f["severity"] == "critical")

    @property
    def ok(self) -> bool:
        return self.critical == 0

    def to_dict(self) -> dict:
        return {"ok": self.ok, "critical": self.critical, "findings": self.findings}


@dataclass
class Sh:
    id: int
    name: str
    role: str | None
    kind: str            # text | line | chart | table | pic | group | shape
    x: float
    y: float
    w: float
    h: float
    el: Any
    shape: Any
    fill: str | None = None
    has_text: bool = False

    @property
    def r(self) -> float:
        return self.x + self.w

    @property
    def b(self) -> float:
        return self.y + self.h


def xp(el, expr: str) -> list:
    return etree._Element.xpath(el, expr, namespaces=NS)


# ---------------------------------------------------------------- theme and colour
@dataclass
class ThemeInfo:
    colors: dict[str, str]
    major: str
    minor: str
    extra_fonts: set[str] = field(default_factory=set)


def _parse_theme(blob: bytes | None) -> ThemeInfo:
    colors = {"dk1": "000000", "lt1": "FFFFFF", "dk2": "1F3C88", "lt2": "F2F3F5"}
    major, minor = "Calibri", "Calibri"
    if blob:
        try:
            root = etree.fromstring(blob)
            for node in xp(root, "//a:clrScheme/*"):
                c = node[0]
                val = c.get("val") if c.tag == _A + "srgbClr" else c.get("lastClr")
                if val:
                    colors[etree.QName(node).localname] = val.upper()
            mj = xp(root, "//a:fontScheme/a:majorFont/a:latin/@typeface")
            mn = xp(root, "//a:fontScheme/a:minorFont/a:latin/@typeface")
            major, minor = (mj[0] if mj else major), (mn[0] if mn else minor)
        except etree.XMLSyntaxError:
            pass
    return ThemeInfo(colors, major, minor)


def _hex(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _resolve(el, th: ThemeInfo) -> str | None:
    """Colour element (srgbClr/schemeClr/sysClr/prstClr) -> RRGGBB, applying lumMod/lumOff."""
    if el is None:
        return None
    tag = etree.QName(el).localname
    if tag == "srgbClr":
        val = (el.get("val") or "000000").upper()
    elif tag == "schemeClr":
        key = SCHEME_MAP.get(el.get("val"), el.get("val"))
        val = th.colors.get(key, "000000" if key in ("dk1", "tx1") else "FFFFFF")
    elif tag == "sysClr":
        val = (el.get("lastClr") or ("FFFFFF" if el.get("val") == "window" else "000000")).upper()
    elif tag == "prstClr":
        val = {"black": "000000", "white": "FFFFFF"}.get(el.get("val"), "000000")
    else:
        return None
    mod, off = el.find(_A + "lumMod"), el.find(_A + "lumOff")
    if mod is not None or off is not None:
        r, g, b = (v / 255 for v in _hex(val))
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        l = l * (int(mod.get("val")) / 1e5 if mod is not None else 1) + (int(off.get("val")) / 1e5 if off is not None else 0)
        r, g, b = colorsys.hls_to_rgb(h, min(max(l, 0), 1), s)
        val = "%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))
    return val


def _solid(parent, th: ThemeInfo) -> str | None:
    if parent is None:
        return None
    sf = parent.find(_A + "solidFill")
    if sf is None or len(sf) == 0:
        return None
    return _resolve(sf[0], th)


def _lum(rgb: str) -> float:
    def ch(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _hex(rgb)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast_ratio(fg: str, bg: str) -> float:
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


# ---------------------------------------------------------------- measurement
@lru_cache(maxsize=None)
def _font_path(kind: str, bold: bool) -> str | None:
    w = "Bold" if bold else "Regular"
    pats = {"arabic": [f"/usr/share/fonts/truetype/noto/NotoSansArabic*{w}.ttf", f"/usr/share/fonts/truetype/noto/NotoNaskhArabic-{w}.ttf",
                       "/usr/share/fonts/truetype/noto/NotoSansArabic*.ttf"],
            "sans": [f"/usr/share/fonts/truetype/liberation/LiberationSans-{w}.ttf"],
            "serif": [f"/usr/share/fonts/truetype/liberation/LiberationSerif-{w}.ttf"]}[kind]
    for p in pats:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[0]
    return None


@lru_cache(maxsize=256)
def _pil_font(kind: str, bold: bool, px: int):
    from PIL import ImageFont
    path = _font_path(kind, bold)
    if not path:
        return None
    try:
        return ImageFont.truetype(path, px)
    except OSError:
        return None


@dataclass
class _M:
    lines: int
    height_in: float
    widest_in: float


def _fallback_measure(text: str, size: float, width: float, bold: bool, serif: bool, ls: float) -> _M:
    arabic = bool(re.search("[؀-ۿ]", text))
    kind = "arabic" if arabic else ("serif" if serif else "sans")
    px = 100
    font = _pil_font(kind, bold, px)
    if arabic:
        try:
            import arabic_reshaper
            text = arabic_reshaper.reshape(text)
        except Exception:
            pass

    def tw(s: str) -> float:
        if font is None:
            return len(s) * size * 0.55 / 72
        return font.getlength(s) / px * size / 72

    lines, widest, cur = 1, 0.0, ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if tw(trial) * 1.03 <= width or not cur:
            cur = trial
        else:
            widest = max(widest, tw(cur))
            lines += 1
            cur = word
    widest = max(widest, tw(cur))
    return _M(lines, lines * 1.2 * size / 72 * ls, widest)


def _measure(text: str, size: float, width: float, *, bold: bool, major: bool, serif: bool, rtl: bool | None, ls: float) -> _M:
    try:
        from om.deck.metrics import measure
        m = measure(text, size, width, bold=bold, font="major" if major else "minor", rtl=rtl, line_spacing=ls)
        return _M(m.lines, m.height_in, m.widest_in)
    except Exception:
        return _fallback_measure(text, size, width, bold, serif, ls)


# ---------------------------------------------------------------- shape model
def _paras(txbody) -> list[dict]:
    out = []
    for p in txbody.findall(_A + "p"):
        ppr = p.find(_A + "pPr")
        runs, text = [], ""
        for ch in p:
            if ch.tag in (_A + "r", _A + "fld"):
                t = ch.find(_A + "t")
                s = (t.text or "") if t is not None else ""
                rpr = ch.find(_A + "rPr")
                sz = rpr.get("sz") if rpr is not None else None
                runs.append({"t": s, "size": int(sz) / 100 if sz else None, "bold": rpr is not None and rpr.get("b") in ("1", "true"),
                             "rpr": rpr, "fld": ch.tag == _A + "fld" and ch.get("type", "").startswith("slidenum")})
                text += s
            elif ch.tag == _A + "br":
                text += "\n"
                runs.append({"t": "\n", "size": None, "bold": False, "rpr": None, "fld": False})

        def pts(tag):
            e = ppr.find(f"{_A}{tag}/{_A}spcPts") if ppr is not None else None
            return int(e.get("val")) / 100 if e is not None else 0.0

        lsp = ppr.find(f"{_A}lnSpc/{_A}spcPct") if ppr is not None else None
        out.append({"text": text, "runs": runs, "ppr": ppr, "after": pts("spcAft"), "before": pts("spcBef"),
                    "ls": int(lsp.get("val")) / 1e5 if lsp is not None else 1.0,
                    "marl": int(ppr.get("marL", 0)) / EMU if ppr is not None else 0.0,
                    "rtl": (ppr is not None and ppr.get("rtl") == "1")})
    return out


def _psize(p: dict, default: float = 18.0) -> float:
    sizes = [r["size"] for r in p["runs"] if r["size"] and r["t"].strip()] or [r["size"] for r in p["runs"] if r["size"]]
    return max(sizes) if sizes else default


def _pbold(p: dict) -> bool:
    n = sum(len(r["t"]) for r in p["runs"])
    return n > 0 and sum(len(r["t"]) for r in p["runs"] if r["bold"]) * 2 >= n


class _Ctx:
    def __init__(self, th: ThemeInfo, sw: float, sh: float, extra_colors: set[str]):
        self.th, self.sw, self.sh = th, sw, sh
        self.palette = {c.lstrip("#").upper() for c in house.PALETTE.values()} | set(th.colors.values()) | extra_colors
        self.m = house.GRID["margin_x"]
        self.out: list[dict] = []

    def add(self, sev, rule, slide, sh: Sh | None, msg):
        self.out.append({"severity": sev, "rule": rule, "slide": slide, "shape_id": sh.id if sh else None,
                         "shape_name": sh.name if sh else None, "message": msg})


def _fill_of(sp_el, th: ThemeInfo) -> str | None:
    sppr = sp_el.find("{%s}spPr" % NS["p"])
    if sppr is not None:
        if sppr.find(_A + "noFill") is not None:
            return None
        c = _solid(sppr, th)
        if c:
            return c
    st = sp_el.find("{%s}style" % NS["p"])
    if st is not None and sppr is not None and sppr.find(_A + "gradFill") is None:
        fr = st.find(_A + "fillRef")
        if fr is not None and fr.get("idx", "0") != "0" and len(fr):
            return _resolve(fr[0], th)
    return None


def _collect(slide, th: ThemeInfo) -> list[Sh]:
    out = []
    for s in slide.shapes:
        if s.left is None or s.width is None:
            continue
        el = s._element
        name = s.name or ""
        m = NAME_RE.match(name)
        role = m.group(2) if m else None
        tag = etree.QName(el).localname
        geom = xp(el, ".//a:prstGeom/@prst")
        x, y, w, h = (s.left / EMU, s.top / EMU, s.width / EMU, s.height / EMU)
        if tag == "cxnSp" or (geom and geom[0] == "line") or (tag == "sp" and (h < 0.001 or w < 0.001) and not s.has_text_frame):
            kind = "line"
        elif tag == "graphicFrame":
            kind = "chart" if xp(el, ".//c:chart") else ("table" if xp(el, ".//a:tbl") else "shape")
        elif tag == "pic":
            kind = "pic"
        elif tag == "grpSp":
            kind = "group"
        else:
            kind = "text" if s.has_text_frame and s.text_frame.text.strip() else "shape"
        out.append(Sh(s.shape_id, name, role, kind, x, y, w, h, el, s, _fill_of(el, th) if tag == "sp" else None,
                      kind == "text"))
    return out


def _slide_bg(slide, th: ThemeInfo) -> str:
    for part in (slide, slide.slide_layout, slide.slide_layout.slide_master):
        bg = part._element.find(".//{%s}bg" % NS["p"])
        if bg is None:
            continue
        c = _solid(bg.find("{%s}bgPr" % NS["p"]), th)
        if c:
            return c
        ref = bg.find("{%s}bgRef" % NS["p"])
        if ref is not None and len(ref):
            c = _resolve(ref[0], th)
            if c:
                return c
    return th.colors.get("lt1", "FFFFFF")


# ---------------------------------------------------------------- the checks
def _run_color(run: dict, para: dict, sp_el, th: ThemeInfo) -> str:
    c = _solid(run["rpr"], th) if run["rpr"] is not None else None
    if c:
        return c
    d = para["ppr"].find(_A + "defRPr") if para["ppr"] is not None else None
    c = _solid(d, th)
    if c:
        return c
    if sp_el is not None:
        fr = sp_el.find("{%s}style/%sfontRef" % (NS["p"], _A))
        if fr is not None and len(fr):
            c = _resolve(fr[0], th)
            if c:
                return c
    return th.colors.get("dk1", "000000")


def _contrast_for(ctx: _Ctx, n: int, sh: Sh, paras: list[dict], bg: str, sp_el, label: str = "") -> None:
    worst = None
    for p in paras:
        size = _psize(p)
        for r in p["runs"]:
            if not r["t"].strip():
                continue
            fg = _run_color(r, p, sp_el, ctx.th)
            need = 3.0 if (size >= 24 or (r["bold"] and size >= 18.66)) else 4.5
            ratio = contrast_ratio(fg, bg)
            if ratio < need and (worst is None or ratio < worst[0]):
                worst = (ratio, need, fg, r["t"].strip()[:30])
    if worst:
        ctx.add("critical", "contrast", n, sh, f"{label}text #{worst[2]} on #{bg} is {worst[0]:.2f}:1, needs {worst[1]}:1 (\"{worst[3]}\")")


def _tables(sh: Sh):
    for tc in xp(sh.el, ".//a:tbl//a:tc"):
        yield tc


def _check_slide(ctx: _Ctx, slide, n: int) -> None:
    th = ctx.th
    shapes = _collect(slide, th)
    bg = _slide_bg(slide, th)
    roles = {s.role for s in shapes if s.role}
    named = bool(roles)
    cover, divider = "cover" in roles, "divider" in roles
    by_role = {}
    for s in shapes:
        by_role.setdefault(s.role, []).append(s)
    sizes: set[float] = set()
    maxm = ctx.m

    # --- per shape text checks
    for s in shapes:
        tx = s.el.find("{%s}txBody" % NS["p"])
        frames = []   # (paras, bg_override, sp_el, label)
        if tx is not None and s.kind != "line":
            frames.append((_paras(tx), None, s.el, ""))
        if s.kind == "table":
            for tc in _tables(s):
                t = tc.find(_A + "txBody")
                if t is not None:
                    tcpr = tc.find(_A + "tcPr")
                    frames.append((_paras(t), _solid(tcpr, th), None, "table "))
        chart_title = None
        if s.kind == "chart":
            try:
                ch = s.shape.chart
                if ch.has_title and ch.chart_title.has_text_frame:
                    chart_title = ch.chart_title.text_frame.text
                small = [int(v) for v in xp(ch._chartSpace, ".//a:defRPr/@sz | .//a:rPr/@sz")]
                if any(v < 1000 for v in small):
                    ctx.add("major", "chart_font", n, s, f"chart text {min(small) / 100:g} pt, minimum 10 pt")
            except Exception:
                pass
        for paras, bgo, sp_el, label in frames:
            for p in paras:
                for r in p["runs"]:
                    if r["size"] and r["t"].strip():
                        sizes.add(r["size"])
                        if r["size"] < house.MIN_ANY_PT - 1e-6:
                            ctx.add("critical", "font_floor", n, s, f"{label}text at {r['size']:g} pt, minimum {house.MIN_ANY_PT} pt")
                            break
                        if s.role == "body" and r["size"] < 12:
                            ctx.add("major", "font_floor", n, s, f"body text at {r['size']:g} pt, minimum 12 pt")
                            break
                kind = "title" if s.role == "title" else "text"
                for rule, msg in slop.lint_text(p["text"].replace("\n", " "), kind=kind):
                    ctx.add("critical", rule, n, s, msg)
                for r in p["runs"]:
                    rpr = r["rpr"]
                    if rpr is None:
                        continue
                    for tg in ("latin", "cs"):
                        e = rpr.find(_A + tg)
                        tf = e.get("typeface") if e is not None else None
                        if tf and not tf.startswith("+") and tf not in (th.major, th.minor) and tf not in th.extra_fonts:
                            ctx.add("major", "theme_font", n, s, f"font \"{tf}\" is not a theme font")
            fbg = bgo or bg
            if bgo is None:
                fbg = _bg_under(s, shapes, bg)
            _contrast_for(ctx, n, s, paras, fbg, sp_el, label)
        if chart_title:
            for rule, msg in slop.lint_text(chart_title):
                ctx.add("critical", rule, n, s, f"chart title: {msg}")

        # body bold figures
        if s.role in ("body", "callout") and tx is not None:
            missed = []
            for p in _paras(tx):
                mask = []
                for r in p["runs"]:
                    mask += [r["bold"]] * len(r["t"])
                for m in FIGURE_RE.finditer(p["text"]):
                    if not any(mask[m.start():m.end()]):
                        missed.append(m.group(0).strip())
            if missed:
                ctx.add("minor", "bold_figures", n, s, "figures not bold: " + ", ".join(missed[:5]))

        # overflow
        if s.kind == "text" and tx is not None:
            _overflow(ctx, n, s, tx)

        # effects and colours inside the shape XML
        for tg in EFFECT_TAGS:
            if xp(s.el, f".//a:{tg}"):
                ctx.add("critical", "slop_effects", n, s, f"{tg} effect is banned")
        bad = sorted({c.upper() for c in xp(s.el, ".//a:srgbClr/@val")} - ctx.palette)
        if bad:
            ctx.add("major", "theme_color", n, s, "colours outside the theme and house palette: " + ", ".join("#" + b for b in bad))

    for tg in EFFECT_TAGS:   # slide-level (background etc.)
        if xp(slide._element, f"./p:cSld/p:bg//a:{tg}"):
            ctx.add("critical", "slop_effects", n, None, f"{tg} effect in slide background")

    # --- bounds, safe margin, overlap
    for s in shapes:
        if s.x < -0.02 or s.y < -0.02 or s.r > ctx.sw + 0.02 or s.b > ctx.sh + 0.02:
            ctx.add("critical", "bounds", n, s, f"box ({s.x:.2f},{s.y:.2f},{s.w:.2f},{s.h:.2f}) leaves the {ctx.sw:.2f} x {ctx.sh:.2f} in slide")
        elif s.role not in {"footer", "footer_rule", "page_number"} | BLEED_ROLES and s.kind != "group":
            e = house.GRID["safe"] - 0.02
            if s.x < e or s.y < e or s.r > ctx.sw - e or s.b > ctx.sh - e:
                ctx.add("major", "safe_margin", n, s, f"within {house.GRID['safe']} in of the slide edge")
    boxes = [s for s in shapes if s.kind not in ("line", "group") and s.role != "decor" and (s.has_text or s.fill or s.kind in ("chart", "table", "pic"))]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            ix = min(a.r, b.r) - max(a.x, b.x)
            iy = min(a.b, b.b) - max(a.y, b.y)
            if ix <= 0 or iy <= 0 or ix * iy <= 0.02:
                continue
            if _contains(a, b) or _contains(b, a):
                continue
            ctx.add("critical", "overlap", n, a, f"overlaps \"{b.name}\" (shape {b.id}) by {ix * iy:.2f} in2")

    # --- grid
    cw = (ctx.sw - 2 * maxm - 11 * 0.2) / 12
    lefts = [maxm + k * (cw + 0.2) for k in range(12)]
    rights = [maxm + (k + 1) * cw + k * 0.2 for k in range(12)]

    def on(v, edges):
        return any(abs(v - e) <= 0.02 for e in edges)
    for s in shapes:
        if s.kind in ("line", "group") or s.role in BLEED_ROLES | {"title_rule", "footer_rule"}:
            continue
        lo, ro = on(s.x, lefts), on(s.r, rights)
        ok = (lo or ro) if s.role in FRAME_ROLES else (lo and ro)
        if not ok:
            ctx.add("major", "grid", n, s, f"edges x {s.x:.2f}..{s.r:.2f} off the 12-column grid")

    # --- type sizes, rounded cards, whitespace
    if len(sizes) > 4:
        ctx.add("major", "type_sizes", n, None, f"{len(sizes)} distinct type sizes ({', '.join(f'{v:g}' for v in sorted(sizes))}), maximum 4")
    rr = [s for s in shapes if xp(s.el, ".//a:prstGeom[@prst='roundRect']")]
    if len(rr) >= 3:
        ctx.add("major", "rounded_cards", n, rr[0], f"{len(rr)} rounded cards; use square panels")
    if named and not cover and not divider:
        _whitespace(ctx, n, shapes)

    # --- house rules
    if not named:
        return
    title = (by_role.get("title") or [None])[0]
    if not cover and not divider and title is not None:
        full = ctx.sw - 2 * maxm
        ok = any(r.kind == "line" and r.w >= 0.9 * full and title.b - 0.05 <= r.y <= title.b + 0.25 for r in by_role.get("title_rule", []))
        if not ok:
            ctx.add("critical", "house_title_rule", n, title, "no title_rule line spanning the margins within 0.25 in under the title")
    if not any(r.kind == "line" for r in by_role.get("footer_rule", [])):
        ctx.add("critical", "house_footer", n, None, "missing footer_rule line")
    if not cover:
        pn = by_role.get("page_number", [])
        okpn = False
        for q in pn:
            tx = q.el.find("{%s}txBody" % NS["p"])
            if tx is not None:
                ps = _paras(tx)
                okpn = okpn or any(p["text"].strip() == str(n) or any(r["fld"] for r in p["runs"]) for p in ps)
        if not okpn:
            ctx.add("critical", "house_footer", n, pn[0] if pn else None, f"page_number text must equal the slide number {n}")
    if title is not None and not cover and not divider:
        rule = (by_role.get("title_rule") or [None])[0]
        limit = rule.y if rule else title.b
        for s in shapes:
            if s is title or s.kind != "text" or s.role in ("title", "decor", "visual", "footer", "page_number"):
                continue
            words = len(s.shape.text_frame.text.split())
            if s.b <= title.y + 0.01 or (s.b <= limit + 0.01 and words < 6 and s.y < title.y + title.h):
                ctx.add("critical", "house_eyebrow", n, s, "eyebrow/kicker text above or beside the title")


def _contains(o: Sh, i: Sh, slack: float = 0.02) -> bool:
    return o.x - slack <= i.x and o.y - slack <= i.y and o.r + slack >= i.r and o.b + slack >= i.b


def _bg_under(s: Sh, shapes: list[Sh], bg: str) -> str:
    best = None
    cands = [s] + [o for o in shapes if o is not s and o.kind != "line" and _contains(o, s, 0.02)]
    for o in cands:
        if o.fill and (best is None or o.w * o.h < best.w * best.h):
            best = o
    return best.fill if best else bg


def _overflow(ctx: _Ctx, n: int, s: Sh, tx) -> None:
    bp = tx.find(_A + "bodyPr")
    g = lambda k, d: int(bp.get(k, d)) / EMU if bp is not None else d / EMU
    li, ti, ri, bi = g("lIns", 91440), g("tIns", 45720), g("rIns", 91440), g("bIns", 45720)
    nowrap = bp is not None and bp.get("wrap") == "none"
    avail = s.w - li - ri
    total = ti + bi
    widest = 0.0
    th = ctx.th
    for p in _paras(tx):
        size = _psize(p)
        bold = _pbold(p)
        face = None
        for r in p["runs"]:
            e = r["rpr"].find(_A + "latin") if r["rpr"] is not None else None
            if e is not None:
                face = e.get("typeface")
                break
        major = face in ("+mj-lt", th.major) and face != th.minor
        serif = (face or "") in ("Cambria", "Georgia", "Times New Roman") or (major and th.major in ("Cambria", "Georgia", "Times New Roman"))
        w = max(avail - p["marl"], 0.1)
        rtl = True if p["rtl"] else None
        segs = p["text"].split("\n") or [""]
        h = 0.0
        for seg in segs:
            if not seg.strip():
                h += 1.2 * size / 72 * p["ls"]
                continue
            m = _measure(seg, size, 1000.0 if nowrap else w, bold=bold, major=major, serif=serif, rtl=rtl, ls=p["ls"])
            h += m.height_in
            widest = max(widest, m.widest_in)
            widest_word = max((_measure(wd, size, 1000.0, bold=bold, major=major, serif=serif, rtl=rtl, ls=1.0).widest_in
                               for wd in seg.split()), default=0.0)
            m.widest_in = max(m.widest_in, widest_word)
            if m.widest_in > w + 0.02:
                ctx.add("critical", "overflow", n, s, f"a line is {m.widest_in:.2f} in wide in a {w:.2f} in box (\"{seg.strip()[:30]}\")")
                return
        total += h + (p["after"] + p["before"]) / 72
    if total > s.h + 0.02:
        ctx.add("critical", "overflow", n, s, f"text needs {total:.2f} in of height, box is {s.h:.2f} in")


def _whitespace(ctx: _Ctx, n: int, shapes: list[Sh]) -> None:
    top, bot = 1.55, 6.95
    x0, x1 = ctx.m, ctx.sw - ctx.m
    step = 0.05
    cells = set()
    for s in shapes:
        if s.kind == "line" or s.role in FRAME_ROLES | {"decor"} or s.kind == "group":
            continue
        ax, bx, ay, by = max(s.x, x0), min(s.r, x1), max(s.y, top), min(s.b, bot)
        if bx <= ax or by <= ay:
            continue
        for i in range(int((ax - x0) / step), int((bx - x0) / step + 0.9999)):
            for j in range(int((ay - top) / step), int((by - top) / step + 0.9999)):
                cells.add((i, j))
    total = int(round((x1 - x0) / step)) * int(round((bot - top) / step))
    if total and len(cells) / total > 0.85:
        ctx.add("major", "whitespace", n, None, f"content covers {len(cells) / total:.0%} of the content band, keep at least 15% whitespace")


# ---------------------------------------------------------------- package checks
def _check_package(data: bytes, out: list[dict]) -> bool:
    ok = True
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        out.append({"severity": "critical", "rule": "xml", "slide": 0, "shape_id": None, "shape_name": None, "message": f"not a zip: {e}"})
        return False
    names = set(zf.namelist())
    for nm in sorted(names):
        if nm.endswith((".xml", ".rels")):
            try:
                root = etree.fromstring(zf.read(nm))
            except etree.XMLSyntaxError as e:
                out.append({"severity": "critical", "rule": "xml", "slide": 0, "shape_id": None, "shape_name": None, "message": f"{nm} does not parse: {e}"})
                ok = False
                continue
            if nm.endswith(".rels"):
                base = posixpath.dirname(posixpath.dirname(nm))
                for rel in root:
                    if rel.get("TargetMode") == "External":
                        continue
                    t = rel.get("Target", "")
                    path = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(base, t))
                    if path not in names:
                        out.append({"severity": "critical", "rule": "xml", "slide": 0, "shape_id": None, "shape_name": None,
                                    "message": f"{nm}: relationship target {path} is missing"})
                        ok = False
    return ok


def validate(source: str | os.PathLike | bytes, *, theme: Any = None) -> Report:
    """Validate a deck. `theme` (optional, om.deck.theme.Theme or dict) widens the allowed colours and fonts."""
    data = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    rep = Report()
    pkg_ok = _check_package(data, rep.findings)
    from pptx import Presentation
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    try:
        prs = Presentation(io.BytesIO(data))
        sw, sh = prs.slide_width / EMU, prs.slide_height / EMU
        th = _parse_theme(prs.slide_master.part.part_related_by(RT.THEME).blob)
    except Exception as e:  # unreadable package: the xml findings (if any) already say why
        if pkg_ok:
            rep.findings.append({"severity": "critical", "rule": "xml", "slide": 0, "shape_id": None, "shape_name": None,
                                 "message": f"cannot open as pptx: {e}"})
        return rep
    extra: set[str] = set()
    if theme is not None:
        cols = getattr(theme, "colors", None) or (theme.get("colors") if isinstance(theme, dict) else None) or {}
        extra = {str(v).lstrip("#").upper() for v in cols.values()}
        fonts = getattr(theme, "fonts", None) or (theme.get("fonts") if isinstance(theme, dict) else None) or {}
        th.extra_fonts = {str(v) for v in fonts.values()}
    ctx = _Ctx(th, sw, sh, extra)
    for i, slide in enumerate(prs.slides, 1):
        _check_slide(ctx, slide, i)
    rep.findings += ctx.out
    rep.findings.sort(key=lambda f: (f["slide"], SEVERITY_ORDER[f["severity"]]))
    return rep
