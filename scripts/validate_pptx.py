#!/usr/bin/env python3
"""validate_pptx.py deck.pptx [--json] [--severity critical|major|minor]: deterministic deck gate; exit 1 on any critical."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from om.deck.validate import SEVERITY_ORDER, validate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("deck")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--severity", choices=list(SEVERITY_ORDER), default="minor", help="lowest severity to show")
    a = ap.parse_args(argv)
    rep = validate(a.deck)
    shown = [f for f in rep.findings if SEVERITY_ORDER[f["severity"]] <= SEVERITY_ORDER[a.severity]]
    if a.json:
        print(json.dumps({"ok": rep.ok, "critical": rep.critical, "findings": shown}, indent=2, ensure_ascii=False))
    else:
        for f in shown:
            where = f"slide {f['slide']}"
            if f["shape_name"]:
                where += f" · shape {f['shape_id']} \"{f['shape_name']}\""
            print(f"[{f['severity']}] {where} · {f['rule']} · {f['message']}")
        print(f"{len(rep.findings)} findings, {rep.critical} critical: {'OK' if rep.ok else 'FAIL'}")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
