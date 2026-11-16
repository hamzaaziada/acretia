"""Learning log: append-only JSONL of per-style scores (data/deck_styles/scores.jsonl, uncommitted)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def default_path() -> Path:
    base = os.environ.get("ACRETIA_DATA")
    root = Path(base) if base else Path(__file__).resolve().parents[3] / "data"
    return root / "deck_styles" / "scores.jsonl"


def record(style: str, *, deck_id: str, slide: int, candidate_id: str, source: str, scores: dict, persona=None,
           validator_ok: bool | None = None, path=None) -> dict:
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "style": style, "deck_id": deck_id, "slide": slide,
           "candidate_id": candidate_id, "source": source, "scores": scores, "persona": persona, "validator_ok": validator_ok}
    p = Path(path) if path else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def read(path=None) -> list[dict]:
    p = Path(path) if path else default_path()
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def entry_score(row: dict) -> float | None:
    """The single 0-10 number for a row: persona (if numeric) blended with final/overall, else mean of numeric scores."""
    s = row.get("scores") or {}
    base = s.get("final", s.get("overall"))
    if not isinstance(base, (int, float)):
        nums = [v for v in s.values() if isinstance(v, (int, float))]
        base = sum(nums) / len(nums) if nums else None
    p = row.get("persona")
    if isinstance(p, (int, float)) and base is not None:
        return (base + p) / 2
    return base if base is not None else (p if isinstance(p, (int, float)) else None)
