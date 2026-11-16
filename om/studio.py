"""Deck Studio: the deck workflow as drawn.

  prompt ──▶ storyboard (as a partner or MD) ──▶ sub-prompts per slide ("ask for strong visuals")
         ──▶ image model draws each slide, one by one ──▶ review / approval ──no, with comments──▶ redraw
                                                              │ yes
         ──▶ slides engine rebuilds the approved image as an editable slide (identical to the image)
         ──▶ review: correct? ──no, with comments──▶ rebuild
                       │ yes
         ──▶ output (.pptx + consistency report)

Each stage is a model stage you can route separately (Settings):
  storyboard     storyboard, critique/revise rounds, slide prompts       any text model
  slide_review   partner/MD review of drafts and of rebuilt slides        vision model
  slide_build    image -> layout JSON for the slides engine               vision model
  image model    OM_IMAGE_MODEL (gemini:… / openai:…)                     image model

The picture is the visual design only. Words and numbers always come from the storyboard (which comes from
the data), the rebuilt slide is checked against the storyboard's numbers, and the finished deck goes
through the consistency checker. Runs are saved after every step (data/studio/<id>/run.json), so a run
can pause for your approval and resume.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import grading
from . import house
from . import layout as lay
from .llm import Part

PROMPTS = Path(__file__).resolve().parent / "prompts"

PERSONAS = {
    "partner": ("Senior partner, strategy firm",
                "You are a senior partner at a top-tier strategy consulting firm. You think in storylines: answer first, the "
                "pyramid principle, every title a conclusion the page proves, one message per page, exhibits chosen for the "
                "question, and a close that assigns decisions and owners."),
    "md": ("Managing director, investment bank",
           "You are a managing director in investment banking at a bulge-bracket bank. You think in numbers that tie: every "
           "figure sourced, dated and in one unit; bridges that foot; consistent periods; alternatives on a common basis; "
           "board-ready precision and conventions."),
}

STYLE = {"palette": house.PALETTE, "font": house.FONTS["body"], "heading_font": house.FONTS["heading"]}


def _read(name: str) -> str:
    p = PROMPTS / name
    return p.read_text() if p.exists() else ""


def standard() -> str:
    """The partner/MD masterclass distilled from 360 earlier reviews, plus later lessons."""
    return (house.STYLE_GUIDE + "\n\n" + _read("masterclass_slides.md") + "\n\n" + _read("lessons_slides.md")).strip()


# --------------------------------------------------------------------------- schemas
STORYBOARD = {
    "type": "object", "required": ["title", "answer", "slides"],
    "properties": {
        "title": {"type": "string"}, "answer": {"type": "string"}, "audience": {"type": "string"},
        "slides": {"type": "array", "items": {"type": "object", "required": ["n", "title", "question", "exhibit", "body", "visual"],
                                              "properties": {
            "n": {"type": "integer"},
            "title": {"type": "string", "description": "the claim the page proves, as a full sentence"},
            "question": {"type": "string", "description": "the one question this page answers"},
            "exhibit": {"type": "string", "description": "cover | executive summary | waterfall | bar | line | table | options matrix | timeline | roadmap | kpi tiles | text"},
            "body": {"type": "array", "items": {"type": "string"}, "description": "every text line that must appear, verbatim"},
            "data": {"type": "array", "items": {"type": "object", "required": ["label", "value"], "properties": {
                "label": {"type": "string"}, "value": {"type": "string"}, "source": {"type": "string"}}}},
            "visual": {"type": "string", "description": "what the strong visual is and how it proves the title"},
            "footnotes": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "string"}}}}}}
REVIEW = {"type": "object", "required": ["approve", "score", "comments"], "properties": {
    "approve": {"type": "boolean"}, "score": {"type": "number"},
    "comments": {"type": "array", "items": {"type": "string"}}, "keep": {"type": "array", "items": {"type": "string"}}}}
PROMPTS_SCHEMA = {"type": "object", "required": ["prompts"], "properties": {"prompts": {"type": "array", "items": {
    "type": "object", "required": ["n", "prompt"], "properties": {"n": {"type": "integer"}, "prompt": {"type": "string"}}}}}}


# --------------------------------------------------------------------------- store
class Studio:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "studio"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def create(self, brief: str, persona: str = "md", mode: str = "auto", context: str = "", options: dict | None = None) -> str:
        rid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        (self.root / rid).mkdir()
        run = {"id": rid, "created": time.time(), "brief": brief.strip(), "persona": persona if persona in PERSONAS else "md",
               "mode": mode if mode in ("auto", "human") else "auto", "context": context, "options": options or {},
               "stage": "storyboard", "status": "queued", "storyboard": None, "storyboard_reviews": [], "slides": [],
               "log": [], "deck": None, "check": None, "error": None}
        self.save(run)
        return rid

    def path(self, rid: str, name: str = "") -> Path:
        if not re.fullmatch(r"[\w-]+", rid) or (name and not re.fullmatch(r"[\w.-]+", name)):
            raise ValueError("bad id")
        return self.root / rid / name if name else self.root / rid

    def load(self, rid: str) -> dict:
        return json.loads(self.path(rid, "run.json").read_text())

    def save(self, run: dict) -> None:
        with self._lock:
            tmp = self.path(run["id"], "run.json.tmp")
            tmp.write_text(json.dumps(run, indent=1, default=str))
            tmp.replace(self.path(run["id"], "run.json"))

    def write(self, rid: str, name: str, data: bytes) -> str:
        self.path(rid, name).write_bytes(data)
        return name

    def read(self, rid: str, name: str) -> bytes:
        return self.path(rid, name).read_bytes()

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.root.iterdir(), reverse=True):
            f = d / "run.json"
            if f.exists():
                r = json.loads(f.read_text())
                out.append({k: r.get(k) for k in ("id", "created", "brief", "persona", "stage", "status", "deck")}
                           | {"title": (r.get("storyboard") or {}).get("title"), "slides": len(r.get("slides") or [])})
        return out


# --------------------------------------------------------------------------- token budget
DEFAULT_BUDGET = 800_000
EST = {"storyboard": 12_000, "slide_review": 12_000, "slide_build": 18_000, "draw": 9_000}   # until real averages exist


class _Meter:
    """Wraps a router (or a provider) and adds every call's tokens to run["usage"], by stage."""

    def __init__(self, inner, run, stage=None):
        self.inner, self.run, self.stage = inner, run, stage

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def complete_json(self, *a, **kw):
        stage = self.stage or (a[0] if a else kw.get("stage"))
        res = self.inner.complete_json(*a, **kw)
        u = getattr(res, "usage", None) or {}
        tok = int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
        if not tok:                                   # provider didn't report usage: estimate from the text sent and received
            parts = a[2] if len(a) > 2 and self.stage is None else (a[1] if len(a) > 1 else [])
            sent = sum(len(getattr(p, "text", "") or "") for p in parts if hasattr(p, "text")) + 1500 * sum(
                1 for p in parts if getattr(p, "image", None) is not None)
            tok = sent // 4 + len(json.dumps(getattr(res, "data", {}))) // 4
        us = self.run.setdefault("usage", {"tokens": 0, "calls": 0, "by_stage": {}})
        us["tokens"] += tok
        us["calls"] += 1
        b = us["by_stage"].setdefault(stage, {"tokens": 0, "calls": 0})
        b["tokens"] += tok
        b["calls"] += 1
        return res


class Pipeline:
    def __init__(self, studio: Studio, router, images, renderer=lay.render_png, image_rounds: int = 3, build_rounds: int = 3,
                 storyboard_rounds: int = 3, deck_rounds: int = 1, grader_samples: int = 1, brand: str = "Research"):
        self.s, self.router, self.images, self.render = studio, router, images, renderer
        self.image_rounds, self.build_rounds, self.storyboard_rounds = image_rounds, build_rounds, storyboard_rounds
        self.deck_rounds, self.samples = deck_rounds, grader_samples
        self.brand = brand

    def _panel(self, target: str, parts: list, gates: list | None = None) -> dict:
        stage = "storyboard" if target == "storyboard" else "slide_review"
        return grading.panel(self.router, stage, target, PERSONAS, standard(), parts, gates, self.samples)

    # ------------------------------------------------------------------ driver
    def advance(self, rid: str) -> dict:
        """Run until done, an error, or a human approval is needed. Safe to call again after a restart."""
        run = self.s.load(rid)
        run["status"] = "running"
        run.setdefault("usage", {"tokens": 0, "calls": 0, "by_stage": {}})
        self.s.save(run)
        base_router, base_designer = self.router, getattr(self.images, "provider", None)
        self.router = _Meter(base_router, run)
        if base_designer is not None:
            self.images.provider = _Meter(base_designer, run, "draw")
        try:
            while run["stage"] not in ("done", "waiting"):
                stage = run["stage"]
                progressed = getattr(self, f"_{stage}")(run)
                self.s.save(run)
                if run["stage"] == stage and not progressed:   # nothing left to do without outside input
                    break
            run["status"] = "done" if run["stage"] == "done" else "waiting" if run["stage"] == "waiting" else "paused"
        except Exception as e:  # keep the run inspectable
            import traceback
            where = traceback.extract_tb(e.__traceback__)[-1]
            run["status"], run["error"] = "error", f"{type(e).__name__}: {e} (at {Path(where.filename).name}:{where.lineno} in {where.name})"
            run["traceback"] = traceback.format_exc()[-3000:]
            self._log(run, f"error: {e} (at {Path(where.filename).name}:{where.lineno})")
        finally:
            self.router = base_router
            if base_designer is not None:
                self.images.provider = base_designer
        self.s.save(run)
        return run

    # ------------------------------------------------------------------ budget
    def _budget(self, run) -> int:
        import os
        return int((run.get("options") or {}).get("token_budget") or os.environ.get("OM_STUDIO_TOKEN_BUDGET") or DEFAULT_BUDGET)

    def _avg(self, run, stage: str) -> float:
        b = (run.get("usage") or {}).get("by_stage", {}).get(stage)
        return b["tokens"] / b["calls"] if b and b["calls"] else EST[stage]

    def _reserve(self, run) -> float:
        """Tokens needed to finish every slide with one draft and one rebuild, no more reviews."""
        need = 0.0
        for sl in run.get("slides") or []:
            if sl.get("image_status") != "approved":
                need += self._avg(run, "draw")
            if sl.get("build_status") != "approved":
                need += self._avg(run, "slide_build")
        return need

    def _affords(self, run, extra: float) -> bool:
        ok = (run.get("usage") or {}).get("tokens", 0) + extra + self._reserve(run) <= self._budget(run)
        if not ok and not run.get("budget_hit"):
            run["budget_hit"] = True
            self._log(run, f"token budget reached ({run['usage']['tokens']:,} of {self._budget(run):,}): no more revision rounds; "
                           "finishing with the best versions so far")
        return ok

    def _rounds(self, run, what: str) -> int:
        default = {"storyboard": self.storyboard_rounds, "image": self.image_rounds, "build": self.build_rounds, "deck": self.deck_rounds}[what]
        return int((run.get("options") or {}).get(f"{what}_rounds") or default)

    def _log(self, run, msg):
        run["log"].append({"t": round(time.time(), 1), "msg": msg})

    def _system(self, run, role: str) -> str:
        return (PERSONAS[run["persona"]][1] + "\n\n" + role + "\n\n# The standard you hold this work to\n" + standard())

    # ------------------------------------------------------------------ 1. storyboard (+ critique rounds)
    def _storyboard(self, run):
        opts = run.get("options") or {}
        n = int(opts.get("slides") or 6)
        facts = run.get("context") or "(no data attached)"
        sys = self._system(run, (
            f"Write the storyboard for a {n}-page deck (cover included). Every number must come from the FACTS block, or be "
            "labelled as an assumption or estimate with its basis; never invent figures, dates or sources. Titles are full-sentence "
            "conclusions. 'body' holds every text line that must appear on the page, verbatim and final (no placeholders or "
            "instructions to research). 'data' lists each figure with its source. 'visual' describes the one strong exhibit that "
            "proves the title.\n\nBe decisive. Titles state the decision or the finding with its number, never a hedge "
            "('pending verification', 'unverified', 'subject to'). Where a figure is an assumption, label it once in the footnote "
            "and size the recommendation on it anyway. Never put a production note on a slide (no 'accession not supplied', no "
            "'needs verification'). Each content page gets one strong visual exhibit (bridge, bar chart, options table, timeline), "
            "not a text panel."))
        parts = [Part(f"FACTS (the only allowed source of numbers):\n{facts}", cache=True), Part(f"BRIEF:\n{run['brief']}")]
        sb = self.router.complete_json("storyboard", sys, parts, STORYBOARD).data
        self._log(run, f"storyboard drafted: {len(sb['slides'])} slides")
        best = None                                  # (score, storyboard): keep the best reviewed version, not the last edit
        rounds = self._rounds(run, "storyboard")
        for rnd in range(1, rounds + 1):
            if not self._affords(run, 2 * self._avg(run, "storyboard") + self._avg(run, "storyboard")):
                break
            rv = self._panel("storyboard", parts + [Part("STORYBOARD (read the titles alone first, then each page):\n" + json.dumps(sb, indent=1))])
            run["storyboard_reviews"].append({"round": rnd, **rv})
            self._log(run, f"storyboard review {rnd}: {rv['score']}/10 " + ("— signed off by both" if rv["approve"] else f"— {rv['why_not']}"))
            if best is None or rv["score"] > best[0]:
                best = (rv["score"], sb, rnd)
            if rv["approve"] or rnd == rounds:
                break
            sb = self.router.complete_json("storyboard", sys, parts + [
                Part("PREVIOUS STORYBOARD:\n" + json.dumps(sb, indent=1)),
                Part("REVIEW COMMENTS TO ADDRESS (all of them; fix the numbers first, then the story):\n- " + "\n- ".join(rv["comments"])),
                Part("Keep everything the reviewers did not criticise exactly as it is.")], STORYBOARD).data
        if best is None:
            best = (0, sb, 0)
        if best and best[1] is not sb:
            self._log(run, f"using the storyboard from round {best[2]} (best score, {best[0]}/10)")
            sb = best[1]
        run["storyboard_signed_off"] = bool(run["storyboard_reviews"] and run["storyboard_reviews"][-1]["approve"]) and best[1] is sb
        for i, sl in enumerate(sb["slides"], start=1):
            sl["n"] = i
        run["storyboard"] = sb
        run["slides"] = [{"n": sl["n"], "spec": sl, "prompt": None, "images": [], "approved_image": None, "image_status": "pending",
                          "builds": [], "approved_build": None, "build_status": "pending"} for sl in sb["slides"]]
        run["stage"] = "prompts"

    # ------------------------------------------------------------------ 2. sub-prompts: ask for strong visuals
    def _prompts(self, run):
        sb = run["storyboard"]
        sys = (self._system(run, (
            "Write one image-generation prompt per slide for an image model that will draw the finished slide as a picture. "
            "Ask for strong visuals: one focal exhibit that proves the title (chart, bridge, matrix, timeline, KPI tiles — "
            "never a wall of bullets), clear hierarchy, generous white space, an executive consulting / investment-bank look. "
            "Each prompt must: give the exact title text and every label and number in quotes, verbatim from the storyboard; "
            "describe the layout grid (where the title, exhibit, callouts, footnote and source line sit); describe the chart "
            "precisely (type, categories, values, highlight, axis); specify the palette and typography below; 16:9 slide, "
            "flat vector style, no photos, no logos, no 3D, no decorative clip art, no lorem ipsum."))
               + f"\n\nPalette: {json.dumps(STYLE['palette'])}. Typeface: {STYLE['font']}-like sans serif, headings and big numbers in a "
                 f"{STYLE['heading_font']}-like serif. Frame on every content slide: title top-left with NO eyebrow or kicker label above "
                 f"it; a thin dark rule under the title across the full width; source line in small grey type above a thin footer rule; "
                 f"under the rule '{self.brand}' bottom-left and the page number bottom-right.")
        res = self.router.complete_json("storyboard", sys, [Part("STORYBOARD:\n" + json.dumps(sb, indent=1))], PROMPTS_SCHEMA).data
        by_n = {p["n"]: p["prompt"] for p in res["prompts"]}
        for sl in run["slides"]:
            sl["prompt"] = by_n.get(sl["n"]) or self._fallback_prompt(sl["spec"])
        self._log(run, f"wrote {len(by_n)} slide prompts")
        run["stage"] = "images"

    def _fallback_prompt(self, spec: dict) -> str:
        return (f"A 16:9 executive presentation slide, flat vector, white background, palette {json.dumps(STYLE['palette'])}. "
                f"Title at top-left: \"{spec['title']}\". Exhibit: {spec['visual']}. Text: "
                + "; ".join(f'"{b}"' for b in spec.get("body") or []))

    # ------------------------------------------------------------------ 3-4. images, one by one, with review
    def _images(self, run):
        if self.images is None:
            raise RuntimeError("no image model configured: set OM_IMAGE_MODEL and its key in Settings (Gemini or OpenAI)")
        for sl in run["slides"]:
            if sl["image_status"] == "approved":
                continue
            if sl["image_status"] == "waiting_human":
                run["stage"] = "waiting"
                return False
            rounds = len(sl["images"])
            last = sl["images"][-1] if sl["images"] else None
            if rounds and not self._affords(run, self._avg(run, "draw") + 2 * self._avg(run, "slide_review")):
                best = max(sl["images"], key=lambda e: (e.get("review") or {}).get("score", 0))
                sl["approved_image"], sl["image_status"] = best["file"], "approved"
                self._log(run, f"slide {sl['n']}: budget — kept the best draft so far ({best['file']}), not signed off")
                return True
            comments = (last or {}).get("review", {}).get("comments") if last else None
            prompt = sl["prompt"]
            refs, source = None, None
            if last and comments:
                prompt = (sl["prompt"] + "\n\nREVISE the attached draft. Keep what works; change exactly this:\n- " + "\n- ".join(comments))
                refs = [self.s.read(run["id"], last["file"])]
                if last.get("svg"):
                    source = self.s.read(run["id"], last["svg"]).decode()
            img = self.images.generate(prompt, references=refs, source=source) if getattr(self.images, "name", "") == "svg" \
                else self.images.generate(prompt, references=refs)
            name = self.s.write(run["id"], f"slide{sl['n']:02d}-draft{rounds + 1}.png", img)
            entry = {"file": name, "round": rounds + 1, "review": None}
            if getattr(self.images, "last_source", None):
                entry["svg"] = self.s.write(run["id"], f"slide{sl['n']:02d}-draft{rounds + 1}.svg", self.images.last_source.encode())
            sl["images"].append(entry)
            self._log(run, f"slide {sl['n']}: drew draft {rounds + 1}")
            measured = []
            if entry.get("svg"):
                from .svgmeasure import check as svg_check
                measured = svg_check(self.images.last_source or "")
                entry["measured"] = measured
            if run["mode"] != "human" and not self._affords(run, 2 * self._avg(run, "slide_review")):
                sl["approved_image"], sl["image_status"] = name, "approved"
                self._log(run, f"slide {sl['n']}: budget — draft {rounds + 1} kept without review, not signed off")
                return True
            rv = self._review_image(run, sl, img, measured)
            entry["review"] = rv
            if run["mode"] == "human":
                entry["advice"] = rv                    # the graders' view, shown next to your decision
                entry["review"] = None
                sl["image_status"] = "waiting_human"
                run["stage"] = "waiting"
                return True
            self._log(run, f"slide {sl['n']}: draft {rounds + 1} scored {rv['score']}/10 " + ("— signed off by both" if rv["approve"] else f"— {rv['why_not']}"))
            if rv["approve"]:
                sl["approved_image"], sl["image_status"] = name, "approved"
            elif rounds + 1 >= self._rounds(run, "image"):
                best = max(sl["images"], key=lambda e: (e.get("review") or {}).get("score", 0))
                sl["approved_image"], sl["image_status"] = best["file"], "approved"
                self._log(run, f"slide {sl['n']}: draft NOT signed off after {rounds + 1} rounds; kept the best ({best['file']})")
            return True                         # one image per step: progress is saved and visible between drafts
        run["stage"] = "build"
        return True

    def _review_image(self, run, sl, img: bytes, measured: list[str] | None = None) -> dict:
        gates = [{"severity": "major", "issue": m, "where": "measured spacing", "fix": "move or resize by the amounts given"}
                 for m in measured or []]
        return self._panel("draft", gates=gates, parts=[
            Part("You are grading a slide DRAFT drawn by an image model. It is the design for the final slide: grade the design, "
                 "hierarchy, exhibit choice, spacing and fidelity to the storyboard page as if it were the finished page. Words and "
                 "numbers will be retyped from the storyboard, so a garbled letter is minor, but an invented, missing or wrong "
                 "figure, or a missing element, is blocking. Comments are instructions for the next draft."),
            Part("STORYBOARD PAGE (authoritative words and numbers):\n" + json.dumps(sl["spec"], indent=1)),
            Part("DRAFT:", image=img)] + ([Part("MEASURED FROM THE DRAFT'S GEOMETRY (exact, not estimates):\n- " + "\n- ".join(measured))]
                                           if measured else []))

    def redo(self, rid: str, slides: list[int], note: str = "", budget: int = 200_000, condense: bool = True) -> dict:
        """Send chosen slides back through the drawing: condense the page, rewrite its prompt, redraw, rebuild, review —
        inside its own token budget — then re-assemble. Earlier attempts are kept under 'previous'."""
        run = self.s.load(rid)
        run.setdefault("usage", {"tokens": 0, "calls": 0, "by_stage": {}})
        run["status"], run["budget_hit"], run["error"] = "paused", False, None
        run.setdefault("options", {})["token_budget"] = run["usage"]["tokens"] + int(budget)
        base_router = self.router
        self.router = _Meter(base_router, run)
        try:
            for n in slides:
                sl = next(x for x in run["slides"] if x["n"] == int(n))
                sl.setdefault("previous", []).append({k: sl.get(k) for k in ("spec", "prompt", "images", "builds", "approved_image", "approved_build")})
                if condense:
                    sl["spec"] = self._condense(run, sl["spec"], note)
                sl["prompt"] = self._one_prompt(run, sl["spec"], note)
                sl.update(images=[], builds=[], approved_image=None, approved_build=None, image_status="pending", build_status="pending",
                          signed_off=False)
                sl.pop("final", None)
                self._log(run, f"slide {sl['n']}: redo requested{' — ' + note if note else ''}")
        finally:
            self.router = base_router
        run["stage"] = "images"
        self.s.save(run)
        return self.advance(rid)

    def _condense(self, run, spec: dict, note: str) -> dict:
        from .spacing import MAX_BLOCK_WORDS, MAX_SLIDE_WORDS
        sys = self._system(run, (
            f"Rewrite ONE storyboard page so a reader gets it in five seconds: at most {MAX_SLIDE_WORDS} words on the page and "
            f"{MAX_BLOCK_WORDS} per block; one exhibit; keep the title's claim and every number exactly (same values, units and "
            "sources); cut repetition, process detail and caveats that belong in a footnote. If the page is a cash or value walk, "
            "say in 'visual' that it is a bridge (waterfall) with short step labels, totals drawn from zero and the buffer as a "
            "dashed reference line. Return the page in the same JSON shape."))
        parts = [Part(f"FACTS:\n{run.get('context') or ''}", cache=True), Part("PAGE:\n" + json.dumps(spec, indent=1))]
        if note:
            parts.append(Part("REVIEWER'S NOTE: " + note))
        schema = STORYBOARD["properties"]["slides"]["items"]
        new = self.router.complete_json("storyboard", sys, parts, schema).data
        new["n"] = spec["n"]
        return new

    def _one_prompt(self, run, spec: dict, note: str) -> str:
        sys = self._system(run, "Write the image-generation prompt for this one slide, following the same rules as for a full deck: "
                                "one strong visual, exact words and numbers in quotes, the layout grid, the house palette and frame.")
        res = self.router.complete_json("storyboard", sys, [Part("PAGE:\n" + json.dumps(spec, indent=1))] +
                                        ([Part("REVIEWER'S NOTE: " + note)] if note else []), PROMPTS_SCHEMA).data
        return next((p["prompt"] for p in res.get("prompts") or [] if p.get("prompt")), None) or self._fallback_prompt(spec)

    def reassemble(self, rid: str) -> dict:
        """Rebuild the finished deck from the approved layouts (with the emphasis pass), no model calls."""
        from . import consistency as cs
        run = self.s.load(rid)
        layouts = [lay.emphasize(json.loads(self.s.read(rid, sl["approved_build"]))) for sl in run["slides"]]
        sources = [self.s.read(rid, sl["approved_image"]) for sl in run["slides"]]
        deck, _ = lay.build_deck(layouts, sources, title=(run["storyboard"] or {}).get("title") or "Deck", brand=self.brand)
        run["deck"] = self.s.write(rid, run.get("deck") or "deck.pptx", deck)
        rep = cs.check_deck(deck, name=run["deck"], tie=False)
        run["check"] = {"counts": rep["counts"], "issues": rep["issues"][:30], "facts": rep["facts"]}
        for i, png in enumerate(self.render(deck) if self.render else [], start=1):
            self.s.write(rid, f"final{i:02d}.png", png)
            run["slides"][i - 1]["final"] = f"final{i:02d}.png"
        self._log(run, "deck re-assembled with the emphasis pass")
        self.s.save(run)
        return run

    def approve_image(self, rid: str, n: int, approve: bool, comments: list[str] | None = None) -> dict:
        """Human approval for mode='human'. Rejected drafts are redrawn with the comments on the next advance()."""
        run = self.s.load(rid)
        sl = next(x for x in run["slides"] if x["n"] == n)
        last = sl["images"][-1]
        last["review"] = {"approve": approve, "score": 10 if approve else 0, "comments": comments or [], "by": "you"}
        if approve:
            sl["approved_image"], sl["image_status"] = last["file"], "approved"
        else:
            sl["image_status"] = "pending"
        run["stage"] = "images"
        self.s.save(run)
        return run

    # ------------------------------------------------------------------ 5-6. slides engine + correctness review
    def _build(self, run):
        for sl in run["slides"]:
            if sl["build_status"] == "approved":
                continue
            target = self.s.read(run["id"], sl["approved_image"])
            prev = sl["builds"][-1] if sl["builds"] else None
            if prev and not self._affords(run, self._avg(run, "slide_build") + 2 * self._avg(run, "slide_review")):
                best = max(sl["builds"], key=lambda b: ((b.get("review") or {}).get("approve", False), (b.get("review") or {}).get("score", 0)))
                sl["approved_build"], sl["build_status"], sl["signed_off"] = best["layout"], "approved", bool((best.get("review") or {}).get("approve"))
                sl.pop("deck_comments", None)
                self._log(run, f"slide {sl['n']}: budget — kept the best rebuild so far")
                return True
            layout = self._make_layout(run, sl, target, prev)
            k = len(sl["builds"]) + 1
            self.s.write(run["id"], f"slide{sl['n']:02d}-build{k}.json", json.dumps(layout, indent=1).encode())   # saved before anything can fail
            from .spacing import check as spacing_check
            pngs, render_name = [], None
            try:
                deck, warnings = lay.build_deck([layout], [target], brand=self.brand)
                pngs = self.render(deck) if self.render else []
                render_name = self.s.write(run["id"], f"slide{sl['n']:02d}-build{k}.png", pngs[0]) if pngs else None
                over = overflow(layout)
                blocking = warnings + check_numbers(sl["spec"], layout, run.get("context") or "") + [o for o in over if o.startswith("text overflows")]
                major = spacing_check(layout) + [o for o in over if not o.startswith("text overflows")]
            except Exception as e:  # malformed layout: tell the slides engine, don't crash the run
                blocking = [f"the layout could not be rendered ({type(e).__name__}: {e}); return valid layout JSON per the contract "
                            "(colours as single hex strings, numbers as numbers)"]
                major = []
                self._log(run, f"slide {sl['n']}: build {k} could not be rendered: {e}")
            findings = blocking + major
            if not self._affords(run, 2 * self._avg(run, "slide_review")):
                sl["builds"].append({"round": k, "layout": f"slide{sl['n']:02d}-build{k}.json", "render": render_name,
                                     "findings": findings, "review": None})
                sl["approved_build"], sl["build_status"], sl["signed_off"] = f"slide{sl['n']:02d}-build{k}.json", "approved", False
                sl.pop("deck_comments", None)
                self._log(run, f"slide {sl['n']}: budget — build {k} kept without review, not signed off")
                return True
            rv = self._review_build(run, sl, target, pngs[0] if pngs else None, blocking, major)
            sl["builds"].append({"round": k, "layout": f"slide{sl['n']:02d}-build{k}.json", "render": render_name,
                                 "findings": findings, "review": rv})
            self._log(run, f"slide {sl['n']}: build {k} scored {rv['score']}/10 " + ("— signed off by both" if rv["approve"] else f"— {rv['why_not']}"))
            sl.pop("deck_comments", None)
            if rv["approve"] or k >= self._rounds(run, "build"):
                best = max(sl["builds"], key=lambda b: ((b.get("review") or {}).get("approve", False), (b.get("review") or {}).get("score", 0)))
                sl["approved_build"], sl["build_status"] = best["layout"], "approved"
                sl["signed_off"] = bool((best.get("review") or {}).get("approve"))
                if not sl["signed_off"]:
                    self._log(run, f"slide {sl['n']}: NOT signed off after {k} builds; keeping the best ({(best.get('review') or {}).get('score', 0)}/10)")
            return True
        run["stage"] = "assemble"
        return True

    def _make_layout(self, run, sl, target: bytes, prev: dict | None) -> dict:
        sys = ("You are the slides engine. Rebuild the attached slide image as an editable PowerPoint slide, identical to the "
               "image: same layout grid, positions, sizes, colours, typography, chart types and emphasis. Use native text, "
               "shapes, tables and charts so everything stays editable. The STORYBOARD PAGE is authoritative for every word "
               "and number: where the image's text differs, use the storyboard's. Measure positions carefully against the "
               "13.333 x 7.5 inch canvas. Prefer components and library icons; they follow the house grid.\n\n" + lay.guide())
        parts = [Part("STORYBOARD PAGE:\n" + json.dumps(sl["spec"], indent=1)), Part("TARGET IMAGE:", image=target)]
        approved = next((e for e in sl["images"] if e["file"] == sl["approved_image"]), {})
        if approved.get("svg"):
            parts.append(Part("SVG SOURCE OF THE TARGET (exact geometry: viewBox 1600 x 900, 120 units = 1 inch, so divide by 120 "
                              "for inches; font-size in px x 0.6 = pt):\n" + self.s.read(run["id"], approved["svg"]).decode()))
        if prev:
            parts.append(Part("YOUR PREVIOUS LAYOUT:\n" + self.s.read(run["id"], prev["layout"]).decode()))
            if prev.get("render"):
                parts.append(Part("HOW IT RENDERED:", image=self.s.read(run["id"], prev["render"])))
            parts.append(Part("FIX ALL OF THESE:\n- " + "\n- ".join((prev["review"].get("comments") or []) + prev.get("findings", []))))
        if sl.get("deck_comments"):
            parts.append(Part("THE WHOLE-DECK REVIEW ALSO REQUIRES:\n- " + "\n- ".join(sl["deck_comments"])))
        return self.router.complete_json("slide_build", sys, parts, lay.SCHEMA, max_tokens=16000).data

    def _review_build(self, run, sl, target: bytes, render: bytes | None, blocking: list[str], major: list[str]) -> dict:
        parts = [Part("You are grading the REBUILT, editable slide that will go to the client. It must match the approved design "
                      "(layout, hierarchy, colours, exhibit, spacing) and be correct (every word and number exactly as in the "
                      "storyboard page). Comments are precise fix instructions for the slides engine: element, what, where, by how much."),
                 Part("STORYBOARD PAGE:\n" + json.dumps(sl["spec"], indent=1)), Part("APPROVED DESIGN:", image=target)]
        if render:
            parts.append(Part("REBUILT SLIDE (as rendered):", image=render))
        else:
            parts.append(Part("(Rendering is unavailable — LibreOffice isn't installed — so grade the layout from the checks below.)"))
            blocking = blocking + ["the rebuilt slide could not be rendered for visual review"]
        gates = list(blocking) + [{"severity": "major", "issue": m, "where": "spacing check"} for m in major]
        return self._panel("build", parts, gates)

    # ------------------------------------------------------------------ 7. output
    def _assemble(self, run):
        from . import consistency as cs
        from .spacing import deck_check
        layouts = [lay.emphasize(json.loads(self.s.read(run["id"], sl["approved_build"]))) for sl in run["slides"]]
        sources = [self.s.read(run["id"], sl["approved_image"]) for sl in run["slides"]]
        title = (run["storyboard"] or {}).get("title") or "Deck"
        deck, warnings = lay.build_deck(layouts, sources, title=title, brand=self.brand)
        name = re.sub(r"[^A-Za-z0-9 _.-]", "", title)[:60].strip() or "deck"
        run["deck"] = self.s.write(run["id"], f"{name.replace(' ', '_')}.pptx", deck)
        rep = cs.check_deck(deck, name=run["deck"], tie=False)
        run["check"] = {"counts": rep["counts"], "issues": rep["issues"][:30], "facts": rep["facts"]}
        pngs = self.render(deck) if self.render else []
        for i, png in enumerate(pngs, start=1):
            self.s.write(run["id"], f"final{i:02d}.png", png)
            run["slides"][i - 1]["final"] = f"final{i:02d}.png"
        # the whole deck, graded by both: titles-only read, same number everywhere, same grid on every page
        gates = [{"severity": "blocking" if i["severity"] == "high" else "major", "issue": i["title"], "where": "consistency check"}
                 for i in rep["issues"] if i["severity"] in ("high", "medium")]
        gates += [{"severity": "major", "issue": m, "where": "spacing check"} for m in deck_check(layouts)]
        parts = [Part("You are grading the WHOLE DECK as the client will read it: titles alone first, then page by page. "
                      "Name pages as 'slide N' in every issue's 'where'."),
                 Part("TITLES IN ORDER:\n" + "\n".join(f"{sl['n']}. {sl['spec']['title']}" for sl in run["slides"])),
                 Part("STORYBOARD:\n" + json.dumps(run["storyboard"], indent=1))]
        for i, png in enumerate(pngs[:15], start=1):
            parts.append(Part(f"SLIDE {i}:", image=png))
        if not self._affords(run, 2 * self._avg(run, "slide_review") * 2):
            run["signed_off"] = False
            self._log(run, f"deck ready: {run['deck']} · budget — whole-deck review skipped · NOT signed off · consistency check: {rep['counts']}")
            run["stage"] = "done"
            return True
        rv = self._panel("deck", parts, gates)
        run.setdefault("deck_reviews", []).append(rv)
        k = len(run["deck_reviews"])
        self._log(run, f"deck review {k}: {rv['score']}/10 " + ("— signed off by both" if rv["approve"] else f"— {rv['why_not']}"))
        if not rv["approve"] and k < self._rounds(run, "deck") and self._affords(run, self._avg(run, "slide_build") * 2):
            flagged = {}
            for iss in rv["issues"]:
                if iss["severity"] in ("blocking", "major"):
                    for n in map(int, re.findall(r"(?:slide|page)s?\s*(\d+)", iss.get("where", "") + " " + iss.get("issue", ""), re.I)):
                        flagged.setdefault(n, []).append(f"{iss.get('issue', '')} → {iss.get('fix', '')}")
            flagged = {n: c for n, c in flagged.items() if 1 <= n <= len(run["slides"])}
            if flagged:
                for sl in run["slides"]:
                    if sl["n"] in flagged:
                        sl["deck_comments"], sl["build_status"] = flagged[sl["n"]], "pending"
                self._log(run, f"deck review sends slides {sorted(flagged)} back to the slides engine")
                run["stage"] = "build"
                return True
        run["signed_off"] = bool(rv["approve"]) and all(sl.get("signed_off") for sl in run["slides"])
        self._log(run, f"deck ready: {run['deck']} · {'SIGNED OFF' if run['signed_off'] else 'NOT signed off'} · consistency check: {rep['counts']}")
        run["stage"] = "done"
        return True


# --------------------------------------------------------------------------- deterministic checks on a built slide
def _nums(text: str) -> set[str]:
    from .consistency import parse_numbers
    out = set()
    for n in parse_numbers(text, accounting=False):
        if n.kind is None and n.decimals == 0 and abs(n.value) < 100:
            continue                                  # page numbers, footnote markers, counts like "3 options"
        if re.fullmatch(r"(?:19|20)\d{2}", n.raw):
            continue
        out.add(re.sub(r"\s+", "", n.raw.lower()).strip("().,"))
    return out


def check_numbers(spec: dict, layout: dict, facts: str = "") -> list[str]:
    """Numbers the storyboard page needs must appear; numbers on the slide must come from the page or the run's sourced facts."""
    want = " \n".join([spec.get("title", "")] + list(spec.get("body") or []) + [d.get("value", "") for d in spec.get("data") or []]
                      + list(spec.get("footnotes") or []) + [spec.get("source", "")])
    have_text = lay.texts(layout)
    chart_vals = {f"{v:g}" for e in lay.expand(layout).get("elements") or [] if e.get("type") == "chart"
                  for s in e.get("series") or [] for v in s.get("values") or [] if v is not None}
    want_n, have_n = _nums(want), _nums(have_text)
    bare = lambda s: re.sub(r"[^\d.]", "", s).rstrip("0").rstrip(".")  # noqa: E731
    have_bare = {bare(x) for x in have_n} | {bare(x) for x in chart_vals}
    out = [f"number missing from the slide: {x}" for x in sorted(want_n - have_n) if bare(x) not in have_bare]
    want_bare = {bare(x) for x in want_n} | {bare(x) for x in _nums(facts)} | {bare(re.sub(r"[,\s]", "", x)) for x in re.findall(r"\$?[\d,]+(?:\.\d+)?", facts)}
    factor = re.compile(r"^\d[x×]$")                     # "2×" in a derivation, not a figure
    out += [f"number not in storyboard: {x}" for x in sorted(have_n - want_n) if bare(x) not in want_bare and not factor.match(x)]
    return out


def overflow(layout: dict) -> list[str]:
    """Text that needs more room than its box (same estimate the spacing check uses)."""
    from .spacing import text_height
    out = []
    for i, e in enumerate(lay.expand(layout).get("elements") or [], start=1):
        if e.get("type") not in ("text", "shape") or not e.get("paragraphs"):
            continue
        need, h = text_height(e), float(e.get("h") or 0)
        if h and need > h * 1.25:
            first = " ".join(r.get("text", "") for r in (e["paragraphs"][0].get("runs") or []))[:40]
            sure = need > h * 1.6 and need - h > 0.25
            out.append(f"{'text overflows' if sure else 'text likely overflows'} its box (element {i}, “{first}…”): "
                       f"needs ~{need:.2f} in, box is {h:.2f} in")
    return out


# --------------------------------------------------------------------------- facts for the storyboard
def build_context(data_service=None, index=None, rooms=None, tickers: list[str] | None = None, room: int | None = None,
                  extra: str = "", log=None) -> str:
    """Facts the storyboard may use, each with its source. SEC fundamentals for tickers; figures from a data room."""
    lines = []
    for t in tickers or []:
        try:
            r, _ = data_service.comps_row(t)
        except Exception as e:
            if log:
                log(f"{t}: {e}")
            continue
        m = lambda k: r.get(k)  # noqa: E731
        bits = [f"{(r.get('name') or t)} ({t.upper()}), SEC 10-K/10-Q XBRL; LTM to {m('ltm_end')}, fiscal year ending {m('last_fy_end')}:"]
        for label, k, unit in (("revenue LTM", "revenue_ltm", "$m"), ("revenue FY", "revenue_fy", "$m"), ("revenue growth LTM", "revenue_growth_ltm_yoy", "%"),
                               ("gross margin LTM", "margin_gross_ltm", "%"), ("EBITDA LTM", "ebitda_ltm", "$m"), ("EBITDA margin LTM", "margin_ebitda_ltm", "%"),
                               ("operating cash flow LTM", "cfo_ltm", "$m"), ("capex LTM", "capex_ltm", "$m"), ("free cash flow LTM", "fcf_ltm", "$m"),
                               ("net income LTM", "net_income_ltm", "$m"), ("cash", "ev_bridge_cash_lcu", "$m"), ("total debt", "ev_bridge_total_debt_lcu", "$m"),
                               ("shares outstanding", "shares_out", "shares")):
            v = m(k)
            if v is not None:
                bits.append(f"{label} {v:,.1f}{'%' if unit == '%' else (' ' + unit)}")
        lines.append("- " + "; ".join(bits))
        try:
            lines += capital_facts(data_service, t)
        except Exception as e:  # history is a bonus; the headline row above still stands
            if log:
                log(f"{t} history: {e}")
    if room and index is not None and rooms is not None:
        from .consistency import LABEL, _fmt_value, room_facts
        seen = set()
        for f in room_facts(index, rooms, int(room)):
            key = (f.metric, f.period, round(f.value, 3))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {LABEL.get(f.metric, f.metric)}{' (' + f.period + ')' if f.period else ''}: {_fmt_value(f)}"
                         f"{' [projection]' if f.projection else ''} — {f.where}")
    if extra.strip():
        lines.append("Additional facts provided by the user:\n" + extra.strip())
    return "\n".join(lines)[:20000]


# --------------------------------------------------------------------------- capital-allocation and liquidity history (XBRL)
CAPITAL_TAGS = [
    ("Revenue", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"), "USD"),
    ("Operating cash flow", ("NetCashProvidedByUsedInOperatingActivities",), "USD"),
    ("Capital expenditure", ("PaymentsToAcquirePropertyPlantAndEquipment",), "USD"),
    ("Dividends paid", ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"), "USD"),
    ("Share repurchases paid", ("PaymentsForRepurchaseOfCommonStock",), "USD"),
    ("Shares repurchased (count)", ("StockRepurchasedAndRetiredDuringPeriodShares",), "shares"),
    ("Diluted EPS", ("EarningsPerShareDiluted",), "USD/shares"),
    ("Cash and cash equivalents (year end)", ("CashAndCashEquivalentsAtCarryingValue",), "USD"),
    ("Short-term investments (year end)", ("ShortTermInvestments",), "USD"),
    ("Long-term debt, current portion (year end)", ("LongTermDebtCurrent",), "USD"),
    ("Long-term debt, non-current (year end)", ("LongTermDebtNoncurrent",), "USD"),
    ("Debt maturing in the next 12 months", ("LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",), "USD"),
    ("Operating lease liabilities (year end)", ("OperatingLeaseLiability",), "USD"),
    ("Finance lease liabilities (year end)", ("FinanceLeaseLiability",), "USD"),
    ("Buyback authorization remaining (year end)", ("StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount1",), "USD"),
]


def capital_facts(data_service, ticker: str, years: int = 3) -> list[str]:
    """Three fiscal years of cash generation, uses, liquidity and buyback capacity from the 10-K XBRL facts, plus
    figures derived in code (so the storyboard writer never has to do the arithmetic)."""
    import os
    from .sec import SecClient
    cik = data_service._cik(ticker)
    if cik is None:
        return []
    sec = SecClient(os.environ.get("SEC_USER_AGENT", ""), Path(data_service.data_dir) / "raw" / "sec")
    g = sec.companyfacts(cik).get("facts", {}).get("us-gaap", {})

    def series(tags, unit):
        for tag in tags:
            vals = (g.get(tag, {}).get("units", {}) or {}).get(unit) or []
            fy = {}
            for v in vals:
                if v.get("form") == "10-K" and v.get("fp") == "FY" and (not v.get("start") or _days(v["start"], v["end"]) > 300):
                    if v["end"] not in fy or v.get("filed", "") > fy[v["end"]].get("filed", ""):
                        fy[v["end"]] = v
            if fy:
                return tag, {e: fy[e]["val"] for e in sorted(fy)[-years:]}
        return None, {}
    data, tags = {}, {}
    for label, tag_list, unit in CAPITAL_TAGS:
        tag, ser = series(tag_list, unit)
        if ser:
            data[label], tags[label] = ser, tag
    if not data:
        return []
    ends = sorted({e for ser in data.values() for e in ser})[-years:]
    fmt = lambda v, unit: (f"${v / 1e6:,.0f}m" if unit == "USD" else f"${v:,.2f}" if unit == "USD/shares" else f"{v:,.0f}")  # noqa: E731
    out = [f"- {ticker.upper()} capital allocation and liquidity, fiscal years ending {', '.join(ends)} (10-K XBRL; each line names its tag):"]
    for label, _, unit in CAPITAL_TAGS:
        if label in data:
            out.append(f"  - {label}: " + "; ".join(f"FY ending {e}: {fmt(data[label][e], unit)}" for e in ends if e in data[label])
                       + f"  [{tags[label]}]")
    # derived in code, labelled as such
    d = []
    ocf, capex = data.get("Operating cash flow", {}), data.get("Capital expenditure", {})
    for e in ends:
        if e in ocf and e in capex:
            d.append(f"free cash flow (operating cash flow − capex) FY ending {e}: ${(ocf[e] - capex[e]) / 1e6:,.0f}m")
    last = ends[-1]
    cash = data.get("Cash and cash equivalents (year end)", {}).get(last)
    sti = data.get("Short-term investments (year end)", {}).get(last) or 0
    debt = sum(data.get(k, {}).get(last) or 0 for k in ("Long-term debt, current portion (year end)", "Long-term debt, non-current (year end)"))
    if cash is not None:
        d.append(f"cash plus short-term investments at {last}: ${(cash + sti) / 1e6:,.0f}m")
        if debt:
            d.append(f"net cash (cash + short-term investments − long-term debt) at {last}: ${(cash + sti - debt) / 1e6:,.0f}m")
        if capex.get(last):
            d.append(f"cash and short-term investments / last fiscal year's capex: {(cash + sti) / capex[last]:.1f}x")
    rets = [data.get(k, {}).get(last) or 0 for k in ("Dividends paid", "Share repurchases paid")]
    if any(rets) and ocf.get(last) and capex.get(last):
        fcf = ocf[last] - capex[last]
        d.append(f"cash returned (dividends + buybacks) FY ending {last}: ${sum(rets) / 1e6:,.0f}m = {sum(rets) / fcf * 100:.0f}% of that year's free cash flow")
    if d:
        out.append("  - Derived in code from the lines above: " + "; ".join(d))
    try:
        sub = sec.submissions(cik)
        rec = sub.get("filings", {}).get("recent", {})
        for form, filed, acc, rep, doc in zip(rec.get("form", []), rec.get("filingDate", []), rec.get("accessionNumber", []),
                                              rec.get("reportDate", []), rec.get("primaryDocument", [])):
            if form == "10-K" and rep == last:
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
                out.append(f"  - Source filing for the latest year: {sub.get('name', ticker.upper())} Form 10-K for the fiscal year ended "
                           f"{rep}, filed {filed}, accession {acc} ({url}). Cite it as \"Costco 10-K for FY ended {rep}, filed {filed}\".")
                break
    except Exception:
        pass
    out.append("  - Not in these facts (do not assert; label any use as an assumption): forward capex guidance, dividends declared "
               "after the fiscal year end, share price, any special dividend, a minimum cash policy.")
    return out


def _days(a: str, b: str) -> int:
    import datetime as _dt
    return (_dt.date.fromisoformat(b) - _dt.date.fromisoformat(a)).days
