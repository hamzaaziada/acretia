#!/usr/bin/env python3
"""Validate an .xlsx model: scripts/validate_xlsx.py PATH [--json] [--circ forbid|breaker] [--no-green]

Exits 1 if any critical finding, 2 if the file cannot be read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from om import validate_xlsx  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--circ", choices=("forbid", "breaker"), default="breaker")
    ap.add_argument("--no-green", action="store_true", help="do not require green fonts on cross-sheet links")
    ap.add_argument("--units", default=None, help="expected scale for every sheet: thousands, millions or billions")
    a = ap.parse_args(argv)
    try:
        with open(a.path, "rb") as fh:
            data = fh.read()
        res = validate_xlsx.validate(data, circ_policy=a.circ, require_green_links=not a.no_green, units=a.units)
    except Exception as e:  # unreadable or corrupt file
        print(f"cannot validate {a.path}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2, default=str) if a.json else validate_xlsx.report(res))
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
