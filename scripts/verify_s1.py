#!/usr/bin/env python3
"""S1 gate: licence ledger, GPL/AGPL isolation, labelled teardowns, buyer research.

Offline and deterministic. Exits non-zero on any failure.
"""
from __future__ import annotations

import ast
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS: list[tuple[str, bool, str]] = []
DECISIONS = {"adopt", "borrow_ideas", "isolated_service", "skip"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
LABEL = re.compile(r"^\s*[-*]\s+\[(OBSERVATION|INFERENCE|UNKNOWN)\]")
BULLET = re.compile(r"^\s*[-*]\s+\S")

# Repos the plan names in S1.1 (matched loosely against the ledger's repo column).
PLAN_REPOS = ["docling", "openbb", "crawl4ai", "edgartools", "financetoolkit", "financial-services", "formulon",
              "marker", "mineru", "presenton", "pptagent", "autopresent", "slidecoder", "clean-slides",
              "mck-ppt-design-skill", "mbb-ppt-generator", "mckinsey-pptx", "pptx-mcp", "python-pptx", "pptxgenjs",
              "gpt-researcher", "dexter", "finrobot", "unstructured", "tika", "fonttools", "pillow",
              "arabic-reshaper", "python-bidi", "duckdb", "opendataloader-bench", "spreadsheetbench",
              "financebench", "pdf.js"]

# Python import names that are GPL/AGPL and must never be imported in-process.
COPYLEFT_IMPORTS = {"fitz", "pymupdf", "marker", "magic_pdf", "mineru", "openbb", "ghostscript", "pdftotext",
                    "camelot"}

# pip distribution -> substring expected in a ledger repo id.
DIST_TO_REPO = {"python-pptx": "python-pptx", "pptx": "python-pptx", "fonttools": "fonttools", "pillow": "pillow",
                "arabic-reshaper": "arabic-reshaper", "python-bidi": "python-bidi", "duckdb": "duckdb",
                "docling": "docling", "edgartools": "edgartools", "financetoolkit": "financetoolkit",
                "crawl4ai": "crawl4ai", "openpyxl": "openpyxl", "pdfplumber": "pdfplumber",
                "pypdfium2": "pypdfium2", "pdfminer.six": "pdfminer", "anthropic": "anthropic",
                "gpt-researcher": "gpt-researcher", "unstructured": "unstructured", "mcp": "python-sdk"}


def check(name):
    def deco(fn):
        try:
            RESULTS.append((name, True, str(fn() or "")))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"[:400]))
        return fn
    return deco


def ledger_rows():
    with open(os.path.join(ROOT, "license-and-repo-ledger.csv"), newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows and [h.strip() for h in rows[0]] == ["repo", "commit_hash", "license", "decision", "reason"], rows[:1]
    return rows[1:]


@check("ledger: well-formed rows (5 fields, 40-hex or justified n/a, licence, decision)")
def _():
    rows = ledger_rows()
    bad, seen = [], set()
    for i, r in enumerate(rows, 2):
        if len(r) != 5:
            bad.append(f"line {i}: {len(r)} fields")
            continue
        repo, commit, lic, dec, reason = (x.strip() for x in r)
        if repo.lower() in seen:
            bad.append(f"line {i}: duplicate {repo}")
        seen.add(repo.lower())
        if not (HEX40.match(commit) or re.match(r"^n/a \(.{8,}\)$", commit)):
            bad.append(f"line {i}: commit {commit!r}")
        if not lic:
            bad.append(f"line {i}: no licence")
        if dec not in DECISIONS:
            bad.append(f"line {i}: decision {dec!r}")
        if len(reason) < 10:
            bad.append(f"line {i}: reason too short")
    assert not bad, bad[:10]
    pinned = sum(1 for r in rows if HEX40.match(r[1].strip()))
    return f"{len(rows)} rows, {pinned} pinned to a commit"


@check("ledger: every repo named in PLAN S1.1 has a row")
def _():
    ids = " ".join(r[0].lower() for r in ledger_rows())
    missing = [p for p in PLAN_REPOS if p not in ids]
    assert not missing, missing
    return f"{len(PLAN_REPOS)} plan repos covered"


@check("ledger: copyleft is never 'adopt'; proprietary never vendored")
def _():
    bad = []
    for repo, commit, lic, dec, reason in (map(str.strip, r) for r in ledger_rows()):
        L = lic.upper()
        strong = re.search(r"(?<!L)GPL|AGPL", L) and "LGPL" not in L.replace("AGPL", "")
        if strong and dec == "adopt" and "MPL" not in L:
            bad.append(f"{repo}: {lic} adopted")
        if re.search(r"PROPRIETARY|SOURCE.AVAILABLE|NO LICEN", L) and dec == "adopt":
            bad.append(f"{repo}: {lic} adopted")
    assert not bad, bad
    return "ok"


def declared_dists():
    dists = set()
    for fn in ("requirements.txt", "requirements-extras.txt"):
        p = os.path.join(ROOT, fn)
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.split("#")[0].strip()
                if line:
                    dists.add(re.split(r"[<>=!~\[; ]", line)[0].lower())
    pp = os.path.join(ROOT, "pyproject.toml")
    if os.path.exists(pp):
        txt = open(pp, encoding="utf-8").read()
        for m in re.finditer(r'^\s*"([A-Za-z0-9_.\-]+)', txt, re.M):
            dists.add(m.group(1).lower())
    return dists


@check("ledger: every declared dependency has a ledger row")
def _():
    ids = " ".join(r[0].lower() for r in ledger_rows())
    missing = []
    for d in sorted(declared_dists()):
        key = DIST_TO_REPO.get(d, d)
        if key not in ids:
            missing.append(d)
    assert not missing, missing
    return f"{len(declared_dists())} declared deps"


def py_files(*dirs):
    for d in dirs:
        base = os.path.join(ROOT, d)
        for dp, dn, fns in os.walk(base):
            dn[:] = [x for x in dn if x not in ("__pycache__", "node_modules")]
            for fn in fns:
                if fn.endswith(".py"):
                    yield os.path.join(dp, fn)


@check("isolation: no GPL/AGPL module imported in om/ or src/")
def _():
    hits, n = [], 0
    for path in py_files("om", "src"):
        n += 1
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in (
                    "import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant):
                names = [str(node.args[0].value)]
            for nm in names:
                if nm.split(".")[0].lower() in COPYLEFT_IMPORTS:
                    hits.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} {nm}")
    assert not hits, hits
    return f"{n} files scanned"


def teardowns():
    d = os.path.join(ROOT, "docs", "teardowns")
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".md"))


@check("teardowns: deck, excel, grid and research notes exist")
def _():
    names = [os.path.basename(p) for p in teardowns()]
    for prefix in ("deck-", "excel-", "grid-", "research-"):
        assert any(n.startswith(prefix) and "summary" not in n for n in names), f"no {prefix}* teardown"
    return f"{len(names)} files"


@check("teardowns: headers (repo, commit, licence, ran) and every finding labelled")
def _():
    bad, findings, obs = [], 0, 0
    for p in teardowns():
        name = os.path.basename(p)
        txt = open(p, encoding="utf-8").read()
        if "summary" in name:
            continue
        head = txt[:1500].lower()
        for key in ("repo:", "commit:", "licen", "ran:"):
            if key not in head:
                bad.append(f"{name}: missing {key}")
        m = re.search(r"commit:\s*`?([0-9a-fn/][^\s`]*)", head)
        if m and not (HEX40.match(m.group(1)) or m.group(1).startswith("n/a")):
            bad.append(f"{name}: commit {m.group(1)!r}")
        ran_no = re.search(r"ran:\s*`?no", head) is not None
        labelled = [ln for ln in txt.splitlines() if LABEL.match(ln)]
        findings += len(labelled)
        o = sum("[OBSERVATION]" in ln for ln in labelled)
        obs += o
        if not labelled:
            bad.append(f"{name}: no labelled findings")
        if not ran_no and o == 0:
            bad.append(f"{name}: ran but no [OBSERVATION]")
        # Bullets under a Findings heading must carry a label.
        sec = re.search(r"^#+\s*Findings[^\n]*\n(.*?)(?=^#+\s|\Z)", txt, re.M | re.S)
        if sec:
            unl = [ln for ln in sec.group(1).splitlines()
                   if BULLET.match(ln) and not LABEL.match(ln) and not ln.startswith("  ")]
            if unl:
                bad.append(f"{name}: {len(unl)} unlabelled findings, e.g. {unl[0][:60]!r}")
    assert not bad, bad[:12]
    return f"{findings} labelled findings, {obs} observations"


@check("buyer research: sourced criteria and three persona rubrics")
def _():
    p = os.path.join(ROOT, "docs", "buyer-research.md")
    txt = open(p, encoding="utf-8").read()
    urls = set(re.findall(r"https?://[^\s)\]>]+", txt))
    assert len(urls) >= 30, f"only {len(urls)} distinct source URLs"
    assert re.search(r"persona rubric", txt, re.I), "no persona rubric section"
    for who in ("analyst", "engagement manager|EM\\b", "principal|investment committee"):
        assert re.search(who, txt, re.I), f"no rubric for {who}"
    cites = len(re.findall(r"\[\d+\]", txt))
    unsourced = len(re.findall(r"\[UNSOURCED\]", txt))
    assert cites >= 40, f"only {cites} inline citations"
    assert unsourced <= max(3, cites // 10), f"{unsourced} unsourced claims"
    return f"{len(urls)} sources, {cites} citations, {unsourced} unsourced"


def main() -> int:
    w = max(len(n) for n, _, _ in RESULTS)
    fails = sum(not ok for _, ok, _ in RESULTS)
    for n, ok, d in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {n.ljust(w)}  {d}")
    print(f"\nS1 gate: {len(RESULTS) - fails}/{len(RESULTS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
