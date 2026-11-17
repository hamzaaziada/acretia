#!/usr/bin/env python3
"""S3.10 deck eval: corpus of 20 briefs, reliability run, results files, scorecard rows and rendered samples (offline).

    python3 scripts/eval_s3.py --corpus --reliability 100 --samples
    python3 scripts/eval_s3.py --corpus --out /tmp/results          # results to another directory, scorecard untouched
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from om.deck import eval as ev  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", action="store_true", help="build the 20-brief corpus")
    ap.add_argument("--reliability", type=int, default=0, metavar="N", help="build N generated specs")
    ap.add_argument("--seed", type=int, default=7, help="reliability generator seed")
    ap.add_argument("--out", default=None, help="results directory (default evals/decks/results); the scorecard is only written for the default")
    ap.add_argument("--samples", action="store_true", help="render docs/samples/s3 (pptx, per-slide PNG, art directions)")
    ap.add_argument("--samples-dir", default=str(ROOT / "docs" / "samples" / "s3"))
    a = ap.parse_args(argv)
    if not (a.corpus or a.reliability or a.samples):
        ap.error("nothing to do: pass --corpus, --reliability N or --samples")
    corpus = rel = None
    if a.corpus:
        corpus = ev.run_corpus()
        for r in corpus:
            print(f"{r['name']:<38} slides={r['slides']:<3} critical={r['critical']} major={r['major']} variety={r['variety']} "
                  f"unsourced={r['unsourced']} art={r['art_direction']} build_s={r['build_seconds']}")
    if a.reliability:
        rel = ev.run_reliability(a.reliability, a.seed)
        print(f"reliability: {rel['success']}/{rel['n']} = {rel['success_rate']:.1%}; 10-slide p50={rel['p50_10_slide_s']}s "
              f"p90={rel['p90_10_slide_s']}s; unsourced={rel['unsourced']}; determinism ok={rel['determinism']['ok']}")
    if corpus is not None or rel is not None:
        prev = {}
        out = Path(a.out) if a.out else ev.RESULTS_DIR
        pj = out / "summary.json"
        if pj.exists():
            import json
            prev = json.loads(pj.read_text(encoding="utf-8"))
        summary = ev.summarize(corpus if corpus is not None else None, rel)
        for k in ("corpus", "reliability"):
            if k not in summary and k in prev:
                summary[k] = prev[k]
        jp, mp = ev.write_results(summary, out)
        print(f"wrote {jp} and {mp}")
        if not a.out:
            print(f"wrote {ev.write_scorecard(corpus, rel)}")
    if a.samples:
        info = ev.render_samples(Path(a.samples_dir))
        print(f"samples: {len(info['decks'])} decks, {len(info['art'])} art directions, rendered={info['rendered']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
