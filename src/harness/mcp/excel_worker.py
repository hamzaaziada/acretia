"""Child-process worker for the Excel MCP server. Reads one JSON job on stdin, writes one JSON result on stdout.

It runs under RLIMIT_AS (set by the parent) so a hostile workbook cannot exhaust the server's memory."""
from __future__ import annotations

import json
import re
import sys


def _plain(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)  # formula error objects etc.


def evaluate(path: str, cells: list) -> dict:
    from om import formula as fx
    from om import xlsx
    with open(path, "rb") as f:
        book = xlsx.read(f.read())
    eng = fx.from_book(book)
    eng.calculate(iterate=True)
    out = {}
    for ref in cells:
        m = re.fullmatch(r"(?:'((?:[^']|'')+)'|([^'!]+))!(\$?[A-Z]{1,3}\$?\d+)", str(ref))
        if not m:
            return {"failure": f"bad cell reference {ref!r}; use Sheet!A1"}
        sheet = (m.group(1) or "").replace("''", "'") or m.group(2)
        if sheet not in book.sheets:
            return {"failure": f"no such sheet {sheet!r}"}
        r, c = xlsx.split_ref(m.group(3))
        raw = book.sheets[sheet].get((r, c))
        out[str(ref)] = {"value": _plain(eng.values.get((sheet, r, c), raw.value if raw else None)),
                         "formula": raw.formula if raw else None}
    return {"values": out, "unsupported_functions": sorted(map(str, eng.unsupported))[:50]}


def grade(path: str) -> dict:
    from om import modelcheck
    with open(path, "rb") as f:
        return modelcheck.grade(f.read())


def main() -> None:
    job = json.loads(sys.stdin.read())
    try:
        if job["op"] == "evaluate":
            res = evaluate(job["path"], job["cells"])
        elif job["op"] == "grade":
            res = {"result": grade(job["path"])}
        else:
            res = {"failure": "unknown op"}
    except MemoryError:
        res = {"failure": "workbook exceeded the memory limit", "code": "memory_limit"}
    except Exception as e:
        res = {"failure": f"{type(e).__name__}: {str(e)[:300]}"}
    sys.stdout.write("\n@@RESULT@@" + json.dumps(res, default=str) + "\n")


if __name__ == "__main__":
    main()
