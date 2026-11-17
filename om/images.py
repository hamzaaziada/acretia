"""Image models for Deck Studio (slide drafts as pictures). Model-agnostic like om/llm.py.

  .env:
    OM_IMAGE_MODEL=gemini:gemini-nano-banana-2.1      # or openai:gpt-image-2.5-flare
    GEMINI_API_KEY=…  /  OPENAI_API_KEY=…

  gemini   POST https://generativelanguage.googleapis.com/v1/models/{model}:generateContent  (x-goog-api-key)
           generationConfig.imageConfig {aspectRatio: "16:9", imageSize: "2K"}; reference images go in as
           inline_data parts, so a rejected draft is revised *from the draft itself* plus the reviewer's comments.
  openai   POST https://api.openai.com/v1/images/generations  {model, prompt, size: "1536x864", quality}
           -> data[0].b64_json. No reference image on this endpoint: revisions go in through the prompt.
With no key, the image stage reports what to configure (Settings) instead of failing silently.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request

DEFAULTS = {"gemini": "gemini-nano-banana-2.1", "openai": "gpt-image-2.5-flare", "custom": "gpt-image-2"}
KEYS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "custom": "CUSTOM_API_KEY"}


class ImageError(Exception):
    pass


def _post(url: str, body: dict, headers: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt * 3)
                continue
            raise ImageError(f"HTTP {e.code}: {e.read()[:300]!r}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 3:
                time.sleep(2 ** attempt * 3)
                continue
            raise ImageError(f"unreachable: {e}")
    raise ImageError("retries exhausted")


class GeminiImages:
    name = "gemini"

    def __init__(self, model: str, key: str, transport=None):
        self.model, self.key, self.transport = model, key, transport or _post

    def generate(self, prompt: str, references: list[bytes] | None = None, aspect: str = "16:9", size: str = "2K") -> bytes:
        parts = [{"text": prompt}] + [{"inline_data": {"mime_type": _mime(r), "data": base64.b64encode(r).decode()}}
                                      for r in (references or [])]
        body = {"contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": aspect, "imageSize": size}}}
        j = self.transport(f"https://generativelanguage.googleapis.com/v1/models/{self.model}:generateContent", body,
                           {"x-goog-api-key": self.key})
        for c in j.get("candidates") or []:
            for part in (c.get("content") or {}).get("parts") or []:
                data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
                if data:
                    return base64.b64decode(data)
        raise ImageError(f"no image in response: {json.dumps(j)[:300]}")


class OpenAIImages:
    name = "openai"

    def __init__(self, model: str, key: str, transport=None, base_url: str = "https://api.openai.com/v1"):
        self.model, self.key, self.transport, self.base_url = model, key, transport or _post, base_url.rstrip("/")

    def generate(self, prompt: str, references: list[bytes] | None = None, aspect: str = "16:9", size: str = "2K") -> bytes:
        dims = {"16:9": "1536x864", "4:3": "1536x1152", "1:1": "1024x1024"}.get(aspect, "1536x864")
        j = self.transport(f"{self.base_url}/images/generations",
                           {"model": self.model, "prompt": prompt[:32000], "n": 1, "size": dims, "quality": "high"},
                           {"Authorization": f"Bearer {self.key}"})
        item = ((j.get("data") or [{}])[0]) if isinstance(j, dict) else {}
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"].split(",", 1)[-1])
        if item.get("url"):                                   # some gateways return a link instead of bytes
            if item["url"].startswith("data:"):
                return base64.b64decode(item["url"].split(",", 1)[-1])
            with urllib.request.urlopen(urllib.request.Request(item["url"], headers={"User-Agent": "Acretia/0.1"}), timeout=120) as r:
                return r.read()
        raise ImageError(f"no image in response: {json.dumps(j)[:300]}")


class SvgImages:
    """No image endpoint? A strong text model draws the slide as SVG (exact text, exact geometry), rendered to PNG
    locally with LibreOffice. Revisions edit the SVG source, and the source goes to the slides engine too."""
    name = "svg"

    def __init__(self, designer_spec: str, provider=None, renderer=None):
        from .llm import make_provider
        self.designer_spec = designer_spec
        self.model = designer_spec
        self.provider = provider or make_provider(designer_spec)
        self.render = renderer or render_svg
        self.last_source: str | None = None

    SYSTEM = ("You are a presentation designer at a top consulting firm. You draw one finished 16:9 slide as a single SVG: "
              'viewBox="0 0 1600 900" (120 units = 1 inch; the slide is 13.333 x 7.5 in), white background, flat vector, no '
              "scripts, no external images or fonts, no foreignObject. Use font-family Arial for text and Cambria for big numbers "
              "and headings where asked. Every word and number must be exactly as given. Lay out with precise, consistent spacing; "
              "keep text inside its boxes (estimate ~0.55 x font-size per character) and nothing within 60 units of the edges "
              "except the footer. Return JSON: {\"svg\": \"<svg …>…</svg>\"}.")

    @staticmethod
    def grid() -> str:
        """The house grid in SVG units (120 per inch), so drafts are on-grid before anyone grades them."""
        from . import house
        G, u = house.GRID, lambda v: round(v * 120)
        return (f"HOUSE GRID (SVG units, 120 = 1 in): left/right margins {u(G['margin_x'])} (content x {u(G['margin_x'])}..{1600 - u(G['margin_x'])}); "
                f"nothing within {u(house.GRID['safe'])} of an edge except the footer. Title block top {u(G['title_y'])}, at most two lines, "
                f"{round(house.TYPE['title'] / 0.6)}px bold; NO eyebrow or label above it. Title rule (1px, text colour) at y {u(G['title_rule_y'])}, "
                f"margin to margin. Subtitle at y {u(G['subtitle_y'])}. Content area y {u(G['content_top'])}..{u(G['content_bottom'])}. Note/source "
                f"at y {u(G['note_y'])}, {-(-house.MIN_ANY_PT * 10 // 6):.0f}px. Footer rule at y {u(G['footer_rule_y'])}; footer text baseline "
                f"~y {u(G['footer_y']) + 18}: deck name left, page number right. Gaps between blocks: all {u(house.GAPS[0])} or all "
                f"{u(house.GAPS[1])} units — one choice per slide, including between text and the card or chart above or below it. "
                f"Card padding {u(house.CARD_PADDING)} units. Body text at least {-(-house.MIN_BODY_PT * 10 // 6):.0f}px, nothing below "
                f"{-(-house.MIN_ANY_PT * 10 // 6):.0f}px. No empty band across the slide. Equal cards are equal; tops aligned. "
                f"Size cards to their content (no big empty cards) and fill the content area with the exhibit.")

    def generate(self, prompt: str, references: list[bytes] | None = None, source: str | None = None, **kw) -> bytes:
        from .llm import Part
        parts = [Part(self.grid()), Part("DESIGN BRIEF:\n" + prompt)]
        if source:
            parts.append(Part("CURRENT SVG (revise it; keep what works, change what the brief's revision notes ask):\n" + source))
        res = self.provider.complete_json(self.SYSTEM, parts, {"type": "object", "required": ["svg"],
                                                               "properties": {"svg": {"type": "string"}}}, max_tokens=16000)
        svg = sanitize_svg(res.data.get("svg") or "")
        png = self.render(svg)
        if not png:
            raise ImageError("could not render the SVG draft (LibreOffice and poppler are needed)")
        self.last_source = svg
        return png


def sanitize_svg(svg: str) -> str:
    """Drop anything that could reach out or run: scripts, foreignObject, event handlers, external references."""
    import re as _re
    m = _re.search(r"<svg[\s\S]*</svg>", svg)
    if not m:
        raise ImageError("the designer returned no SVG")
    svg = m.group(0)
    svg = _re.sub(r"<(script|foreignObject|iframe|object|embed)[\s\S]*?</\1\s*>", "", svg, flags=_re.I)
    svg = _re.sub(r"<(script|foreignObject|iframe|object|embed)\b[^>]*/>", "", svg, flags=_re.I)
    svg = _re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", svg, flags=_re.I)
    svg = _re.sub(r"(xlink:href|href)\s*=\s*(\"(?!#|data:image/)[^\"]*\"|'(?!#|data:image/)[^']*')", "", svg, flags=_re.I)
    svg = _re.sub(r"url\(\s*['\"]?(?!#)[^)]*\)", "none", svg, flags=_re.I)
    svg = _re.sub(r"@import[^;]*;", "", svg, flags=_re.I)
    return svg


def render_svg(svg: str, dpi: int = 120) -> bytes | None:
    """SVG -> PNG via LibreOffice (to PDF) and pdftoppm; None if the tools aren't installed."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    exe = shutil.which("soffice") or ("/Applications/LibreOffice.app/Contents/MacOS/soffice"
                                       if Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists() else None)
    ppm = shutil.which("pdftoppm")
    if not exe or not ppm:
        return None
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "slide.svg"
        src.write_text(svg)
        try:
            subprocess.run([exe, "--headless", "--norestore", f"-env:UserInstallation=file://{d}/profile", "--convert-to", "pdf",
                            "--outdir", d, str(src)], capture_output=True, timeout=120)
            pdf = Path(d) / "slide.pdf"
            if not pdf.exists():
                return None
            subprocess.run([ppm, "-r", str(dpi), "-png", "-singlefile", str(pdf), str(Path(d) / "out")], capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return None
        out = Path(d) / "out.png"
        return out.read_bytes() if out.exists() else None


def _mime(b: bytes) -> str:
    return "image/jpeg" if b[:3] == b"\xff\xd8\xff" else "image/webp" if b[8:12] == b"WEBP" else "image/png"


def configured_spec() -> str | None:
    spec = (os.environ.get("OM_IMAGE_MODEL") or "").strip()
    if spec:
        return spec
    for name in ("gemini", "openai"):
        if (os.environ.get(KEYS[name]) or "").strip():
            return name
    return None


def make_image_provider(spec: str | None = None, transport=None):
    spec = spec or configured_spec()
    if not spec:
        return None
    if spec.startswith("svg:"):
        from .llm import LLMError
        try:
            return SvgImages(spec[4:] or "custom")
        except LLMError as e:
            raise ImageError(str(e))
    name, _, model = spec.partition(":")
    name = name.strip().lower()
    if name not in DEFAULTS:
        raise ImageError(f"unknown image provider {name!r}; use gemini, openai or custom")
    key_env = (os.environ.get("OM_PROVIDER_CUSTOM_API_KEY_ENV") or KEYS[name]) if name == "custom" else KEYS[name]
    key = (os.environ.get(key_env) or "").strip()
    if not key:
        raise ImageError(f"{name} image model needs {key_env} (Settings)")
    if name == "custom":
        base = (os.environ.get("OM_PROVIDER_CUSTOM_BASE_URL") or "").strip()
        if not base:
            raise ImageError("custom image model needs the endpoint's base URL (Settings)")
        from .llm import LLMError, key_host_guard
        try:
            key_host_guard(base)
        except LLMError as e:
            raise ImageError(str(e))
        prov = OpenAIImages(model or DEFAULTS[name], key, transport, base_url=base)
        prov.name = "custom"
        return prov
    cls = GeminiImages if name == "gemini" else OpenAIImages
    return cls(model or DEFAULTS[name], key, transport)


def describe() -> str:
    try:
        p = make_image_provider()
    except ImageError as e:
        return f"misconfigured: {e}"
    if p and p.name == "svg":
        return f"draws as SVG with {p.designer_spec}"
    return f"{p.name}:{p.model}" if p else "none"
