"""S3.8 vision critic loop: LibreOffice -> PNG -> VLM critic (through src/harness/adapter.py only) -> SlideRepairPatch.

Runs only after the deterministic validator passes. The model names shape ids and picks tokens/roles; it never
writes colours, fonts or free geometry: every op is sanitised, then applied deterministically (grid snap,
`fit_text`, bounds check). A patch that introduces a new critical validator finding is rolled back.
"""
from __future__ import annotations

import copy
import inspect
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from om import replay
from om.contracts import PATCH_OPS, SlideRepairPatch
from om.deck import fit as fitmod
from om.deck import validate as validate_mod
from om.deck.model import Element, Para, Run, SolvedSlide
from om.deck.render import render
from om.deck.theme import CANVAS_H, CANVAS_W, COLS, Theme, grid_w, grid_x
from src.harness.adapter import image_part

log = logging.getLogger("om.deck.critic")

THEME_SIZES = (10, 12, 14, 24, 40, 44)
SEVERITIES = ("critical", "major", "minor")
PROTECTED_ROLES = {"title", "title_rule", "footer_rule", "footer", "page_number"}      # the house frame stays
ARG_KEYS = {
    "move": ("x", "y"), "resize": ("w", "h"), "set_text": ("text",), "set_font_size": ("size",),
    "set_style": ("color", "fill"), "delete": (), "reorder": ("to",),
}
NOT_RUN_LIVE = "critic: not run live"
SKIPPED_CRITICAL = "critic: skipped (validator critical)"

HOUSE_RULES = (
    "House rules: every content slide has a title (max 2 lines) with a thin title rule beneath it; a footer rule "
    "with the footer text and a page number sits at the bottom (the cover has no page number); no eyebrows or "
    "kickers above the title; every content element's left and right edges sit on the 12-column grid; key figures "
    "(numbers, %, $) are bold; one accent colour only, used sparingly; no text clipped, overlapping or touching an "
    "edge; generous, even whitespace.")

_ARGS_SCHEMA = {"type": "object", "properties": {
    "x": {"type": "number"}, "y": {"type": "number"}, "w": {"type": "number"}, "h": {"type": "number"},
    "text": {"type": "string"}, "size": {"type": "number"}, "color": {"type": "string"}, "fill": {"type": "string"},
    "to": {"type": "integer"}}}
CRITIC_SCHEMA = {
    "type": "object", "required": ["ok", "score", "issues", "patch"],
    "properties": {
        "ok": {"type": "boolean"},
        "score": {"type": "number"},
        "issues": {"type": "array", "items": {"type": "object", "required": ["shape", "problem", "severity"], "properties": {
            "shape": {"type": "string"}, "problem": {"type": "string"}, "severity": {"type": "string", "enum": list(SEVERITIES)}}}},
        "patch": {"anyOf": [{"type": "null"}, {"type": "object", "required": ["slide_index", "ops"], "properties": {
            "slide_index": {"type": "integer"}, "reason": {"type": "string"},
            "ops": {"type": "array", "items": {"type": "object", "required": ["op", "target", "args"], "properties": {
                "op": {"type": "string", "enum": list(PATCH_OPS)}, "target": {"type": "string"}, "args": _ARGS_SCHEMA}}}}}]},
    },
}


# ------------------------------------------------------------------------------------------------ rasterize
def _tools() -> tuple[str | None, str | None]:
    return shutil.which("soffice") or shutil.which("libreoffice"), shutil.which("pdftoppm")


def rasterize(pptx_bytes: bytes, *, dpi: int = 80, timeout: float = 120) -> list[bytes]:
    """One PNG per slide. Returns [] (reason in `rasterize.last_reason`) when the tools are missing or fail."""
    rasterize.last_reason = ""
    soffice, pdftoppm = _tools()
    if not soffice or not pdftoppm:
        rasterize.last_reason = "soffice/pdftoppm not installed"
        return []
    try:
        with tempfile.TemporaryDirectory(prefix="critic-") as td:
            tmp = Path(td)
            (tmp / "deck.pptx").write_bytes(pptx_bytes)
            profile = tmp / "profile"
            r = subprocess.run(
                [soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf",
                 "--outdir", str(tmp), str(tmp / "deck.pptx")],
                capture_output=True, timeout=timeout, cwd=td, env={**os.environ, "HOME": td})
            pdf = tmp / "deck.pdf"
            if r.returncode != 0 or not pdf.is_file():
                rasterize.last_reason = f"libreoffice failed: {r.stderr.decode(errors='replace')[:200]}"
                return []
            r = subprocess.run([pdftoppm, "-png", "-r", str(dpi), str(pdf), str(tmp / "pg")],
                               capture_output=True, timeout=timeout)
            pages = sorted(tmp.glob("pg*.png"))
            if r.returncode != 0 or not pages:
                rasterize.last_reason = f"pdftoppm failed: {r.stderr.decode(errors='replace')[:200]}"
                return []
            return [p.read_bytes() for p in pages]
    except (subprocess.TimeoutExpired, OSError) as e:
        rasterize.last_reason = f"rasterize error: {type(e).__name__}: {e}"
        return []


rasterize.last_reason = ""


# ------------------------------------------------------------------------------------------------ patch sanitising
def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _clean_args(op: str, args: dict, theme: Theme) -> tuple[dict, str | None]:
    """Whitelist args per op; returns (clean, reason-to-drop or None)."""
    if not isinstance(args, dict):
        return {}, "args is not an object"
    extra = set(args) - set(ARG_KEYS[op])
    if extra:
        return {}, f"args {sorted(extra)} not allowed for {op}"
    out: dict = {}
    for k, v in args.items():
        if k in ("x", "y", "w", "h"):
            if not _num(v):
                return {}, f"{k} must be a number"
            out[k] = float(v)
        elif k == "text":
            if not isinstance(v, str) or not v.strip():
                return {}, "text must be a non-empty string"
            out[k] = v
        elif k == "size":
            if not _num(v) or int(v) != v or int(v) not in THEME_SIZES:
                return {}, f"size {v!r} not in the theme size set {THEME_SIZES}"
            out[k] = int(v)
        elif k in ("color", "fill"):
            if not isinstance(v, str) or v not in theme.colors:        # tokens only: raw hex / names are dropped
                return {}, f"{k} {v!r} is not a theme token"
            out[k] = v
        elif k == "to":
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                return {}, "to must be a non-negative integer"
            out[k] = v
    if op in ("move",) and not out:
        return {}, "move needs x and/or y"
    if op == "resize" and not out:
        return {}, "resize needs w and/or h"
    required = {"set_text": "text", "set_font_size": "size", "reorder": "to"}.get(op)
    if required and required not in out:
        return {}, f"{op} needs {required}"
    if op == "set_style" and not out:
        return {}, "set_style needs color and/or fill"
    return out, None


def sanitize_patch(raw: Any, slide: SolvedSlide, theme: Theme) -> tuple[dict | None, list[dict]]:
    """Keep only ops that reference existing element ids with allowed ops/args; log and return what was dropped."""
    dropped: list[dict] = []
    if not raw:
        return None, dropped
    if not isinstance(raw, dict) or not isinstance(raw.get("ops"), list):
        return None, [{"reason": "patch is not an object with ops"}]
    ids = {e.id for e in slide.elements}
    ops: list[dict] = []
    for o in raw["ops"]:
        if not isinstance(o, dict):
            dropped.append({"op": o, "reason": "op is not an object"})
            continue
        op, target = o.get("op"), o.get("target")
        if op not in PATCH_OPS:
            reason = f"unknown op {op!r}"
        elif target not in ids:
            reason = f"unknown shape id {target!r}"
        else:
            args, reason = _clean_args(op, o.get("args") or {}, theme)
            if reason is None:
                ops.append({"op": op, "target": target, "args": args})
                continue
        dropped.append({"op": op, "target": target, "reason": reason})
    for d in dropped:
        log.warning("critic patch op dropped: %s", d)
    if not ops:
        return None, dropped
    patch = {"slide_index": slide.index, "ops": ops, "reason": str(raw.get("reason") or "")[:300]}
    try:
        SlideRepairPatch.from_dict({**patch, "slide_index": max(slide.index, 0)})
    except Exception as e:  # noqa: BLE001 - contract violation: drop whole patch
        dropped.append({"reason": f"patch violates SlideRepairPatch: {e}"})
        return None, dropped
    return patch, dropped


# ------------------------------------------------------------------------------------------------ critique
def _describe(slide: SolvedSlide) -> str:
    rows = []
    for e in slide.elements:
        txt = ""
        if e.text:
            txt = " | " + " / ".join("".join(r.t for r in p.runs) for p in e.text.paras)[:80]
        rows.append(f"- {e.id} [{e.role}] x={e.x:.2f} y={e.y:.2f} w={e.w:.2f} h={e.h:.2f}{txt}")
    return "\n".join(rows)


def build_messages(slide_png: bytes, slide: SolvedSlide, theme: Theme) -> list[dict]:
    system = (
        "You are a strict visual QA reviewer for investment-banking slides. You see a rendered slide image plus the "
        "list of its shapes. Report visual defects by naming shape ids from the list ONLY. You may propose a repair "
        "patch using only these ops: move{x,y}, resize{w,h}, set_text{text}, set_font_size{size}, set_style{color,fill}, "
        "delete, reorder{to}. Colours must be theme tokens (" + ", ".join(sorted(theme.colors)) + "); font sizes must be one "
        "of " + ", ".join(str(s) for s in THEME_SIZES) + ". Never write hex colours or font names. Geometry is in inches "
        "on a 13.333 x 7.5 canvas and is snapped to the grid afterwards. " + HOUSE_RULES)
    user = (f"Slide {slide.index} (archetype {slide.archetype}). Shapes:\n{_describe(slide)}\n\n"
            "Return JSON {\"ok\": bool, \"score\": 0-10, \"issues\": [{\"shape\": id, \"problem\": str, \"severity\": "
            "\"critical|major|minor\"}], \"patch\": {\"slide_index\": int, \"ops\": [{\"op\", \"target\", \"args\"}], "
            "\"reason\": str} or null}. ok is true only if nothing needs fixing.")
    return [{"role": "system", "content": system},
            {"role": "user", "content": [{"type": "text", "text": user}, image_part(slide_png)]}]


def critique(slide_png: bytes, slide: SolvedSlide, *, adapter, job_id: str | None = None, theme: Theme | None = None) -> dict:
    """One VLM call through the adapter. Returns {ok, score, issues, patch, dropped}; the patch is already sanitised."""
    theme = theme or Theme.house()
    res = adapter.chat(build_messages(slide_png, slide, theme), json_schema=CRITIC_SCHEMA, job_id=job_id)
    data = res.data if isinstance(getattr(res, "data", None), dict) else {}
    ids = {e.id for e in slide.elements}
    issues = []
    for i in data.get("issues") or []:
        if isinstance(i, dict) and i.get("shape") in ids and i.get("severity") in SEVERITIES:
            issues.append({"shape": i["shape"], "problem": str(i.get("problem", ""))[:300], "severity": i["severity"]})
    patch, dropped = sanitize_patch(data.get("patch"), slide, theme)
    score = data.get("score")
    score = max(0.0, min(10.0, float(score))) if _num(score) else None
    ok = bool(data.get("ok")) and not any(i["severity"] == "critical" for i in issues) and patch is None
    return {"ok": ok, "score": score, "issues": issues, "patch": patch, "dropped": dropped}


# ------------------------------------------------------------------------------------------------ apply
def _snap_span(x: float, w: float) -> tuple[float, float]:
    """Nearest column for the left edge, nearest span for the width, clamped inside the 12 columns."""
    c = min(range(COLS), key=lambda i: abs(grid_x(i) - x))
    s = min(range(1, COLS + 1), key=lambda n: abs(grid_w(n) - w))
    s = min(s, COLS - c)
    return grid_x(c), grid_w(s)


def _in_bounds(e: Element) -> bool:
    return e.x >= -1e-6 and e.y >= -1e-6 and e.x + e.w <= CANVAS_W + 1e-6 and e.y + e.h <= CANVAS_H + 1e-6


def _text_of(e: Element) -> str:
    return " ".join("".join(r.t for r in p.runs) for p in e.text.paras) if e.text else ""


def _refit(e: Element, paras: list[Para], size: float) -> bool:
    """Fit at exactly `size` (no shrink); False means the text would overflow."""
    ts = e.text
    r = fitmod.fit_text(paras, e.w, e.h, size=size, floor=size, role=e.role, block_id=e.id, inset=ts.inset, font=ts.font)
    if not r.ok:
        return False
    ts.paras, ts.size = r.paras, size
    return True


def _apply_op(e: Element, slide: SolvedSlide, op: str, a: dict, theme: Theme) -> str | None:
    """Mutate `e` (a copy) in place; return a refusal reason or None."""
    if op in ("move", "resize"):
        old = (e.x, e.y, e.w, e.h)
        if "x" in a or "w" in a:
            e.x, e.w = _snap_span(a.get("x", e.x), a.get("w", e.w))
        if "y" in a:
            e.y = round(a["y"], 2)
        if "h" in a:
            e.h = round(a["h"], 2)
        if not _in_bounds(e):
            e.x, e.y, e.w, e.h = old
            return "would push the box out of bounds"
        if e.text and (e.w, e.h) != old[2:] and not _refit(e, e.text.paras, e.text.size):
            e.x, e.y, e.w, e.h = old
            return "text would overflow the new box"
    elif op == "set_text":
        if not e.text:
            return "shape has no text"
        first = e.text.paras[0]
        bold = first.runs[0].b if first.runs else False
        paras = [Para([Run(a["text"], b=bold)], align=first.align, level=first.level, bullet=first.bullet,
                      space_after=first.space_after)]
        if not _refit(e, paras, e.text.size):
            return "text would overflow"
    elif op == "set_font_size":
        if not e.text:
            return "shape has no text"
        if not _refit(e, e.text.paras, a["size"]):
            return "text would overflow at that size"
    elif op == "set_style":
        if "color" in a:
            if not e.text:
                return "shape has no text"
            e.text.color = a["color"]
        if "fill" in a:
            e.fill = a["fill"]
    return None


def apply_patch_ex(slide: SolvedSlide, patch: dict, theme: Theme) -> tuple[SolvedSlide, list[dict], list[dict]]:
    """Returns (new slide, applied ops, refused ops with reasons). The input slide is never mutated."""
    new = copy.deepcopy(slide)
    applied, refused = [], []
    for o in (patch or {}).get("ops", []):
        op, target, args = o["op"], o["target"], o.get("args") or {}
        idx = next((i for i, e in enumerate(new.elements) if e.id == target), None)
        if idx is None:
            refused.append({**o, "reason": "unknown shape id"})
            continue
        e = new.elements[idx]
        if op == "delete":
            reason = f"{e.role} belongs to the house frame" if e.role in PROTECTED_ROLES else None
            if reason is None:
                del new.elements[idx]
        elif op == "reorder":
            to = min(args["to"], len(new.elements) - 1)
            new.elements.insert(to, new.elements.pop(idx))
            reason = None
        else:
            work = copy.deepcopy(e)
            reason = _apply_op(work, new, op, args, theme)
            if reason is None:
                new.elements[idx] = work
        (refused.append({**o, "reason": reason}) if reason else applied.append(o))
    return new, applied, refused


def apply_patch(slide: SolvedSlide, patch: dict | SlideRepairPatch, theme: Theme) -> SolvedSlide:
    """Deterministic, non-mutating. Move/resize snap to the 12-col grid; text is re-fitted; unsafe ops are refused."""
    if isinstance(patch, SlideRepairPatch):
        patch = patch.to_dict()
    return apply_patch_ex(slide, patch, theme)[0]


# ------------------------------------------------------------------------------------------------ loop
def _validate(fn: Callable, data: bytes, theme: Theme):
    try:
        takes_theme = "theme" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        takes_theme = False
    return fn(data, theme=theme) if takes_theme else fn(data)


def _crit_keys(rep) -> set[tuple]:
    return {(f.get("slide"), f.get("rule"), f.get("shape_name")) for f in rep.findings if f.get("severity") == "critical"}


def _finish(slides, report, status: str):
    report["critic"] = status
    return slides, report


def loop(slides: list[SolvedSlide], theme: Theme, *, adapter=None, title: str, max_loops: int = 3,
         validate: Callable = validate_mod.validate, job_id: str | None = None):
    """Render -> validate; only if clean: rasterize -> critique -> patch -> re-render -> re-validate (max `max_loops`)."""
    report: dict = {"critic": "not started", "loops": 0, "slides": {}, "patches_applied": [], "patches_rolled_back": [],
                    "patches_refused": [], "dropped": [], "validator": {}}
    data = render(slides, theme, title=title)
    rep = _validate(validate, data, theme)
    report["validator"] = {"critical": rep.critical, "findings": len(rep.findings)}
    if rep.critical:
        return _finish(slides, report, SKIPPED_CRITICAL)
    if adapter is None:
        return _finish(slides, report, NOT_RUN_LIVE)
    cur = list(slides)
    for _ in range(max_loops):
        pngs = rasterize(data)
        if len(pngs) != len(cur):
            return _finish(cur, report, f"critic: skipped (rasterizer: {rasterize.last_reason or 'page count mismatch'})")
        scores, patches = {}, {}
        for s, png in zip(cur, pngs):
            try:
                c = critique(png, s, adapter=adapter, job_id=job_id, theme=theme)
            except replay.ReplayMiss:
                return _finish(slides if not report["loops"] else cur, report, NOT_RUN_LIVE)
            except Exception as e:  # noqa: BLE001 - adapter/transport failure: never fake a score
                report["error"] = f"{type(e).__name__}: {e}"[:300]
                return _finish(cur, report, "critic: error (not run live)" if not report["loops"] else "critic: error")
            scores[s.index] = {"score": c["score"], "ok": c["ok"], "issues": c["issues"]}
            report["dropped"] += [{"slide": s.index, **d} for d in c["dropped"]]
            if c["patch"]:
                patches[s.index] = c["patch"]
        report["loops"] += 1
        report["slides"] = scores            # latest critique per slide
        report.setdefault("history", []).append({k: v["score"] for k, v in scores.items()})
        if all(v["ok"] for v in scores.values()):
            return _finish(cur, report, "critic: ok")
        cand, applied_by = list(cur), {}
        for i, s in enumerate(cur):
            p = patches.get(s.index)
            if p:
                cand[i], ap, rf = apply_patch_ex(s, p, theme)
                applied_by[i] = ap
                report["patches_refused"] += [{"slide": s.index, **r} for r in rf]
        if not any(applied_by.values()):
            continue
        base_keys = _crit_keys(rep)
        new_data = render(cand, theme, title=title)
        new_rep = _validate(validate, new_data, theme)
        if _crit_keys(new_rep) - base_keys:                 # something broke: retry slide by slide
            keep = list(cur)
            for i, ap in applied_by.items():
                if not ap:
                    continue
                trial = list(keep)
                trial[i] = cand[i]
                t_rep = _validate(validate, render(trial, theme, title=title), theme)
                entry = {"slide": cur[i].index, "ops": ap}
                if _crit_keys(t_rep) - base_keys:
                    report["patches_rolled_back"].append(entry)
                else:
                    keep[i] = cand[i]
                    report["patches_applied"].append(entry)
            cand = keep
            new_data = render(cand, theme, title=title)
            new_rep = _validate(validate, new_data, theme)
        else:
            report["patches_applied"] += [{"slide": cur[i].index, "ops": ap} for i, ap in applied_by.items() if ap]
        cur, data, rep = cand, new_data, new_rep
        report["validator"] = {"critical": rep.critical, "findings": len(rep.findings)}
    return _finish(cur, report, "critic: max loops reached")
