"""Tough graders for Deck Studio: a partner and an MD, both of whom must sign off.

Calibrated on the earlier review loop (360 partner/MD reviews of Costco storyboards, decks and models): there,
8 of 360 reviews signed off, the published Goldman Sachs board book graded about 7, and no deck got both
reviewers to sign off in the same round. The bar here is the same:

  sign-off  = overall (mean of dimensions) >= 8.0  AND  every dimension >= 7  AND  no blocking or major issue
  approved  = BOTH the partner and the MD sign off  (the lower score is the one reported)

The model only scores and lists defects; the verdict is computed here, so a grader can't wave work through.
Graders never see the round number or earlier scores (no credit for "improved"), deterministic findings
(numbers that don't tie, text overflow, consistency-check errors) are added as blocking issues, and with
samples > 1 each dimension takes its lowest score across samples.
"""
from __future__ import annotations

import json
import statistics

from .llm import Part

SIGN_OFF_OVERALL = 8.0
SIGN_OFF_DIMENSION = 7

# target -> persona -> {dimension: what it measures}
RUBRICS = {
    "storyboard": {
        "partner": {"answer": "a sized answer up front; the decision is unmistakable",
                    "storyline": "titles alone tell a complete, non-repetitive story; one question per page",
                    "evidence": "each page's exhibit would actually prove its title",
                    "visual_plan": "the planned exhibits are the right ones for each question (bridge, options matrix, roadmap…)"},
        "md": {"deal_logic": "the numbers and mechanics are right: bridges foot, periods don't overlap, authorizations aren't cash",
               "sourcing": "every material figure is sourced, dated and labelled actual / guidance / estimate",
               "risk": "downside, thresholds and what would change the answer are shown and derived"},
    },
    "draft": {
        "partner": {"storyline": "the title is the conclusion and fits the deck's story",
                    "proof": "the exhibit proves the title, visibly, without a voice-over",
                    "visuals": "one strong focal visual; clear hierarchy; not a wall of text",
                    "craft": "alignment, consistency and legibility at presentation distance",
                    "spacing": "consistent grid and margins (0.5in clear of every edge), equal gaps between blocks (0.3in or 0.5in, one per deck), aligned top edges and baselines, 0.2in padding inside cards, nothing cramped, crowded or floating; whitespace is deliberate"},
        "md": {"accuracy": "every figure and label matches the storyboard page; chart drawn faithfully (proportional bars, bridges foot)",
               "honesty": "units, periods and actual vs estimate are labelled on the face of the page",
               "polish": "would go to a board as is: no clutter, nothing cut off or decorative; the key figures and lead-ins are bold so the eye lands on them",
               "spacing": "consistent grid and margins (0.5in clear of every edge), equal gaps between blocks (0.3in or 0.5in, one per deck), aligned top edges and baselines, 0.2in padding inside cards, nothing cramped, crowded or floating; whitespace is deliberate"},
    },
    "build": {
        "partner": {"fidelity": "matches the approved design: layout, hierarchy, colours, exhibit",
                    "craft": "nothing overlaps, overflows, is cut off or misaligned; type is legible",
                    "visuals": "the exhibit reads instantly; emphasis is where the argument is",
                    "spacing": "consistent grid and margins (0.5in clear of every edge), equal gaps between blocks (0.3in or 0.5in, one per deck), aligned top edges and baselines, 0.2in padding inside cards, nothing cramped, crowded or floating; whitespace is deliberate"},
        "md": {"accuracy": "every word and number exactly as in the storyboard page; charts from the right values",
               "honesty": "units, periods, sources and estimate labels present and correct",
               "polish": "client-ready as is",
               "spacing": "consistent grid and margins (0.5in clear of every edge), equal gaps between blocks (0.3in or 0.5in, one per deck), aligned top edges and baselines, 0.2in padding inside cards, nothing cramped, crowded or floating; whitespace is deliberate"},
    },
    "deck": {
        "partner": {"storyline": "answer first; titles alone tell the story; every page has one job",
                    "proof": "each exhibit proves its title; the decisive number is traceable",
                    "visuals": "exhibits fit their questions; layouts distinct where messages differ",
                    "craft": "consistent typography, alignment, footers and numbering across pages",
                    "language": "board language: direct verbs, no placeholders, narrowest claim the evidence supports",
                    "spacing": "the same grid on every page: title, content area, footer and gaps identical slide to slide; nothing cramped"},
        "md": {"accuracy": "the same number is the same everywhere; bridges foot; arithmetic holds",
               "sourcing": "primary sources, dated; estimates labelled",
               "valuation": "alternatives on a common basis; returns against a stated hurdle; gross and net effects",
               "honesty": "caveats next to the claims they limit; discrepancies named, not smoothed",
               "polish": "board-ready, page by page",
               "spacing": "the same grid on every page: title, content area, footer and gaps identical slide to slide; nothing cramped"},
    },
}

ANCHORS = """Scale (integers 1-10, per dimension):
10 flawless — the best work you have seen from a top firm, nothing to change
 9 exceptional — one trivial nit
 8 sign-off — you would send it to the client today, unchanged
 7 good — but you would send it back once
 6 several real fixes needed
 5 significant rework
 4 or below — rebuild
Calibration: a published bulge-bracket board book grades about 7 against this standard; most first drafts grade 4-6.
Grade the work as it stands; there is no credit for effort or for improving on an earlier version. Do not round up.
Every score below 10 must name the specific defect that cost the points. List every defect you find as an issue:
blocking = would embarrass the firm or mislead the reader (wrong or unsupported number, title the page doesn't prove,
unreadable exhibit); major = you would not send it with this (any spacing, alignment or margin fault you can see
counts as major); minor = polish. Spacing is graded as hard as the numbers."""


def _schema(dims: dict) -> dict:
    return {"type": "object", "required": ["headline", "scores", "issues"], "properties": {
        "headline": {"type": "string"},
        "scores": {"type": "object", "required": list(dims), "properties": {
            d: {"type": "object", "required": ["score", "why"], "properties": {
                "score": {"type": "integer", "minimum": 1, "maximum": 10}, "why": {"type": "string"}}} for d in dims}},
        "issues": {"type": "array", "items": {"type": "object", "required": ["severity", "where", "issue", "fix"], "properties": {
            "severity": {"type": "string", "enum": ["blocking", "major", "minor"]}, "where": {"type": "string"},
            "issue": {"type": "string"}, "fix": {"type": "string"}}}}}}


def verdict(scores: dict[str, int], issues: list[dict]) -> dict:
    vals = list(scores.values())
    overall = round(statistics.fmean(vals), 2) if vals else 0.0
    low = min(vals) if vals else 0
    sev = {s: sum(1 for i in issues if i.get("severity") == s) for s in ("blocking", "major", "minor")}
    ok = overall >= SIGN_OFF_OVERALL and low >= SIGN_OFF_DIMENSION and sev["blocking"] == 0 and sev["major"] == 0
    why = []
    if overall < SIGN_OFF_OVERALL:
        why.append(f"overall {overall} < {SIGN_OFF_OVERALL}")
    if low < SIGN_OFF_DIMENSION:
        why.append(", ".join(f"{d} {s}" for d, s in scores.items() if s < SIGN_OFF_DIMENSION) + f" under {SIGN_OFF_DIMENSION}")
    if sev["blocking"] or sev["major"]:
        why.append(f"{sev['blocking']} blocking / {sev['major']} major issue{'s' if sev['blocking'] + sev['major'] != 1 else ''}")
    return {"overall": overall, "lowest": low, "sign_off": ok, "counts": sev, "why_not": "; ".join(why)}


def grade(router, stage: str, target: str, persona: str, persona_text: str, standard: str, parts: list[Part],
          gates: list[str] | None = None, samples: int = 1) -> dict:
    dims = RUBRICS[target][persona]
    rubric = "\n".join(f"- {d}: {what}" for d, what in dims.items())
    system = (f"{persona_text}\n\nYou are grading, not editing. Be exacting: your reputation rides on what leaves the building.\n\n"
              f"Dimensions:\n{rubric}\n\n{ANCHORS}\n\n# The standard\n{standard}")
    runs = []
    for _ in range(max(1, samples)):
        runs.append(router.complete_json(stage, system, parts, _schema(dims)).data)
    scores = {d: min(int(r["scores"][d]["score"]) for r in runs) for d in dims}            # toughest sample per dimension
    why = {d: min(runs, key=lambda r: int(r["scores"][d]["score"]))["scores"][d].get("why", "") for d in dims}
    issues = [dict(i, persona=persona) for r in runs for i in r.get("issues") or []]
    for g in gates or []:                       # automatic findings: str = blocking, or {"severity", "issue", "where"}
        g = g if isinstance(g, dict) else {"severity": "blocking", "issue": g}
        issues.append({"severity": g.get("severity", "blocking"), "where": g.get("where", "automatic check"), "issue": g["issue"],
                       "fix": g.get("fix", "fix so the check passes"), "persona": "check"})
    v = verdict(scores, issues)
    return {"persona": persona, "headline": runs[0].get("headline", ""), "scores": scores, "why": why, "issues": issues, **v}


def panel(router, stage: str, target: str, personas: dict, standard: str, parts: list[Part], gates: list[str] | None = None,
          samples: int = 1) -> dict:
    """Partner and MD grade independently; approved only if both sign off. Returns a review dict for the run."""
    graded = [grade(router, stage, target, p, personas[p][1], standard, parts, gates, samples) for p in ("partner", "md")]
    seen, issues = set(), []
    for g in graded:
        for i in g["issues"]:
            k = (i.get("where", "").lower(), i.get("issue", "")[:80].lower())
            if k not in seen:
                seen.add(k)
                issues.append(i)
    rank = {"blocking": 0, "major": 1, "minor": 2}
    issues.sort(key=lambda i: rank.get(i.get("severity"), 3))
    approve = all(g["sign_off"] for g in graded)
    score = min(g["overall"] for g in graded)
    comments = [f"[{i['severity']}] {i.get('where', '')}: {i.get('issue', '')} → {i.get('fix', '')}".strip() for i in issues]
    return {"approve": approve, "score": score, "comments": comments, "issues": issues, "panel": graded,
            "why_not": " · ".join(f"{g['persona']}: {g['why_not']}" for g in graded if not g["sign_off"])}


def describe_bar() -> str:
    return (f"Sign-off: both partner and MD, each with overall ≥ {SIGN_OFF_OVERALL}, every dimension ≥ {SIGN_OFF_DIMENSION}, "
            "and no blocking or major issue.")


def as_text(review: dict) -> str:
    return json.dumps({k: review[k] for k in ("score", "approve", "why_not")}, indent=None)
