"""Regenerate evals/decks/briefs/NN-<slug>.yaml from the authoring modules (offline, deterministic).

    python3 evals/decks/build_corpus.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.decks import corpus_a, corpus_ar, corpus_b, corpus_c, corpus_d  # noqa: E402

ORDER = [corpus_a.d01, corpus_a.d02, corpus_a.d03, corpus_a.d04, corpus_b.d05, corpus_b.d06, corpus_b.d07, corpus_b.d08,
         corpus_b.d09, corpus_c.d10, corpus_c.d11, corpus_c.d12, corpus_c.d13, corpus_ar.d14, corpus_ar.d15, corpus_d.d16,
         corpus_d.d17, corpus_d.d18, corpus_ar.d19, corpus_d.d20]


def main(out: Path | None = None) -> list[Path]:
    import yaml
    out = out or ROOT / "evals" / "decks" / "briefs"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.yaml"):
        old.unlink()
    paths = []
    for i, fn in enumerate(ORDER, 1):
        b = fn()
        slug = b["spec"]["deck_id"].split("-", 1)[1]
        p = out / f"{i:02d}-{slug}.yaml"
        p.write_text(yaml.safe_dump(b, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
        paths.append(p)
    return paths


if __name__ == "__main__":
    for p in main():
        print(p.relative_to(ROOT))
