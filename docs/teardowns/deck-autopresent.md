# Teardown: para-lost/AutoPresent

repo: https://github.com/para-lost/AutoPresent
commit: 98e0c012e89469863d9c3c8bc87eac967d82b2e6
licence: MIT License (LICENSE:1)
ran: partial (the SlidesLib helper functions add_title, add_text, add_bullet_points were executed on brief A slides 1 and 2 with a stub for the missing mysearchlib import; no LLM, no code-generation, no SlidesBench evaluation)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/autopresent/a.pptx and a-sheet.png. Driver: s12/run_ap.py.

## Findings

- [OBSERVATION] Approach: an LLM writes a python-pptx program that calls a small helper library (SlidesLib: add_title, add_text, add_bullet_points, add_image, set_background_color, plus search, VQA and image-generation wrappers) (SlidesLib/__init__.py:11-190; generate/prompt/example_full_wlib.txt). The paper's contribution is the SlidesBench benchmark (slidesbench/, 10 example categories: art_photos, business, career, design, entrepreneur, environment, food, marketing, social_media, technology) and fine-tuned models (autopresent/train.py), plus a refinement loop (README.md "Create Slides via Programs").
- [OBSERVATION] Layout method: the model supplies absolute [left, top, width, height] in inches for each call (add_text docstring, __init__.py:77-100); nothing is computed by the library. There are no archetypes and no charts: plotting.py (55 lines) only wraps matplotlib (SlidesLib/plotting.py), so charts would be images.
- [OBSERVATION] Text fit is delegated to PowerPoint flags: add_text sets MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT after multiplying box height by the number of "\n" lines; add_bullet_points sets TEXT_TO_FIT_SHAPE but never measures (__init__.py:100-160). In my run the bullets rendered without bullet glyphs and the title sat in a 4:3 placeholder position on a 16:9 slide (out/autopresent/a-sheet.png).
- [OBSERVATION] The package is not importable as shipped: SlidesLib/__init__.py imports `mysearchlib`, which does not exist in the repo (line 9), so I exec'd only the helper functions after stubbing it.
- [OBSERVATION] Evaluation code (generate/calc_score.py, 130+ lines) scores generated decks against references (reference-based) and with VLM judging (reference-free); both need an OpenAI key, so unrun.
- [OBSERVATION] No validator and no RTL support (whole-word rtl/bidi search returned nothing in SlidesLib/).
- [INFERENCE] AutoPresent is a research baseline, not an engine for our use. What matters for S3.10 is SlidesBench: a published benchmark we may reuse for the deck eval (PLAN.md S3.10 names it), and its two-sided scoring (reference-based, reference-free).
- [UNKNOWN] SlidesBench data licence and size: not inspected beyond directory names.

## Adopt / borrow ideas / skip

Borrow ideas only: SlidesBench as an eval source (check data licence in S1.1 ledger), the program-as-spec framing. Skip the library (no layout intelligence, broken import).
