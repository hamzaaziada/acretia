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
        dists |= pyproject_optional_dists(txt)
    return dists


def pyproject_optional_dists(txt: str) -> set[str]:
    """Distribution names under [project.optional-dependencies] (tomllib when available, else a section scan)."""
    out: set[str] = set()
    try:
        import tomllib  # py3.11+
        data = tomllib.loads(txt)
        groups = (data.get("project") or {}).get("optional-dependencies") or {}
        for reqs in groups.values():
            for r in reqs:
                out.add(re.split(r"[<>=!~\[; ]", r.strip())[0].lower())
        return out
    except ImportError:
        pass
    sec = re.search(r"^\[project\.optional-dependencies\][^\n]*\n(.*?)(?=^\[|\Z)", txt, re.M | re.S)
    if sec:
        for m in re.finditer(r'"([A-Za-z0-9_.\-]+)[^"]*"', sec.group(1)):
            out.add(m.group(1).lower())
    return out


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


def py_files(*dirs, root=None):
    for d in dirs:
        base = os.path.join(root or ROOT, d)
        if not os.path.isdir(base):
            continue
        for dp, dn, fns in os.walk(base):
            dn[:] = [x for x in dn if x not in ("__pycache__", "node_modules")]
            for fn in fns:
                if fn.endswith(".py"):
                    yield os.path.join(dp, fn)


def copyleft_hits(root=None):
    """Scan om/ and src/ under root for in-process imports of GPL/AGPL modules (any scope, any import form)."""
    root = root or ROOT
    hits, n = [], 0
    for path in py_files("om", "src", root=root):
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
                    hits.append(f"{os.path.relpath(path, root)}:{node.lineno} {nm}")
    return hits, n


@check("isolation: no GPL/AGPL module imported in om/ or src/")
def _():
    hits, n = copyleft_hits()
    assert not hits, hits
    return f"{n} files scanned"


REPO_TEARDOWN_PREFIXES = ("deck-", "excel-", "grid-", "research-")


def is_repo_teardown(path: str) -> bool:
    """A note is exempt only if it has no 'repo:' line in its first 40 lines AND is not named deck-/excel-/grid-/research-."""
    name = os.path.basename(path)
    if name.startswith(REPO_TEARDOWN_PREFIXES):
        return True
    with open(path, encoding="utf-8") as f:
        head = [next(f, "") for _ in range(40)]
    return any(re.match(r"^\W*repo\W*:", ln, re.I) for ln in head)


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
        if "summary" in name or not is_repo_teardown(p):
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


# ---------------------------------------------------------------- import ledger coverage
FIRST_PARTY = {"om", "src", "tests", "scripts"}
# (relative path, import name) pairs allowed to import a skip/isolated_service module. Kept minimal on purpose.
# D-S1-02: om/recalc.py may import LibreOffice's MPL-2.0 pyuno client bridge (uno, com.sun.star), but only lazily:
# every such import must sit inside a function body or a try/except, never at module top level.
ISOLATED_ALLOW: set[tuple[str, str]] = {("om/recalc.py", "uno"), ("om/recalc.py", "com")}
# Well-known import-name != project-name pairs, used before the substring fallback.
IMPORT_ALIASES = {"pil": "pillow", "bidi": "python-bidi", "pptx": "python-pptx", "yaml": "pyyaml",
                  "pdfminer": "pdfminer", "fontTools".lower(): "fonttools", "bs4": "beautifulsoup"}


def first_party_names(root=None):
    root = root or ROOT
    names = set(FIRST_PARTY)
    for fn in os.listdir(root):
        if fn.endswith(".py"):
            names.add(fn[:-3])
        elif os.path.isdir(os.path.join(root, fn)) and os.path.exists(os.path.join(root, fn, "__init__.py")):
            names.add(fn)
    return names


def _guarded_lines(tree):
    """Line numbers of nodes that sit inside a function body or a try/except (i.e. not module top level)."""
    guarded = set()

    def visit(node, inside):
        for child in ast.iter_child_nodes(node):
            g = inside or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Try))
            if hasattr(child, "lineno") and g:
                guarded.add((child.lineno, child.col_offset))
            visit(child, g)

    visit(tree, False)
    return guarded


def third_party_imports(root=None, with_scope=False):
    """{top-level name: [file:line, ...]} from every import form, including nested, try/except and import_module.

    With with_scope=True each entry is (file:line, guarded) where guarded means inside a function or try/except."""
    root = root or ROOT
    fp = first_party_names(root)
    found: dict[str, list] = {}
    files = list(py_files("om", "src", "scripts", root=root))
    top = os.path.join(root, "open_multiples.py")
    if os.path.exists(top):
        files.append(top)
    for path in files:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, path)
        guarded = _guarded_lines(tree)
        rel = os.path.relpath(path, root)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    names = [node.module]
            elif isinstance(node, ast.Call):
                fn = node.func
                fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if fname in ("import_module", "__import__") and node.args \
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    names = [node.args[0].value]
            for nm in names:
                t = nm.split(".")[0]
                if t and t not in sys.stdlib_module_names and t not in fp:
                    loc = f"{rel}:{node.lineno}"
                    entry = (loc, (node.lineno, node.col_offset) in guarded) if with_scope else loc
                    found.setdefault(t, []).append(entry)
    return found


def import_map_table():
    """Parse the 'Import-name -> ledger row map' section of docs/ledger-notes.md (arrow lines or a markdown table)."""
    p = os.path.join(ROOT, "docs", "ledger-notes.md")
    out: dict[str, str] = {}
    if not os.path.exists(p):
        return out
    txt = open(p, encoding="utf-8").read()
    m = re.search(r"^#+[^\n]*import-name[^\n]*\n(.*?)(?=^#+\s|\Z)", txt, re.I | re.M | re.S)
    if not m:
        return out
    for ln in m.group(1).splitlines():
        ln = ln.strip()
        if re.match(r"^\|[\s:|-]+\|?$", ln):
            continue
        if ln.startswith("|"):
            cells = [c.strip(" `*") for c in ln.strip("|").split("|")]
            if len(cells) >= 2 and cells[0].lower() not in ("import", "import name", "import-name", "name"):
                out[cells[0].lower()] = cells[1].lower()
            continue
        a = re.match(r"^[-*]?\s*[`*]*([A-Za-z0-9_.\-]+)[`*]*\s*(?:→|->)\s*[`*]*([A-Za-z0-9_.\-/]+)", ln)
        if a:
            out[a.group(1).lower()] = a.group(2).lower()
    return out


def isolated_violations(found, rows, table):
    """Return (unmapped, bad_dec). found is third_party_imports(with_scope=True). An allow-listed pair is
    permitted only when every such import in that file is inside a function body or try/except."""
    unmapped, bad_dec, n_mapped = [], [], 0
    for name in sorted(found):
        key = name.lower()
        if key in table:
            target = table[key]
            matched = [r for r in rows
                       if r[0].lower() == target or r[0].lower().split("/")[-1] == target.split("/")[-1]]
        else:
            needle = IMPORT_ALIASES.get(key, key)
            matched = [r for r in rows if needle in r[0].lower()]
        if not matched:
            unmapped.append(f"{name} ({', '.join(loc for loc, _ in found[name][:3])})")
            continue
        n_mapped += 1
        for r in matched:
            if r[3] in ("skip", "isolated_service"):
                for loc, guarded in found[name]:
                    path = loc.rsplit(":", 1)[0].replace(os.sep, "/")
                    if (path, name) not in ISOLATED_ALLOW:
                        bad_dec.append(f"{name} -> {r[0]} is {r[3]} ({loc})")
                    elif not guarded:
                        bad_dec.append(f"{name} -> {r[0]} imported at module level ({loc}); "
                                       "allow-listed imports must be inside a function or try/except")
    return unmapped, bad_dec, n_mapped


@check("imports: every third-party import (AST, incl. nested/try/import_module) maps to a ledger row")
def _():
    found = third_party_imports(with_scope=True)
    rows = [tuple(x.strip() for x in r) for r in ledger_rows()]
    table = import_map_table()
    unmapped, bad_dec, n_mapped = isolated_violations(found, rows, table)
    assert not unmapped, "no ledger row for: " + "; ".join(unmapped)
    assert not bad_dec, "skip/isolated_service module imported: " + "; ".join(bad_dec[:8])
    return f"{len(found)} third-party names, {n_mapped} mapped, table entries {len(table)}"


@check("self-test: scanners flag module-level fitz and unguarded uno, accept lazy uno")
def _():
    import tempfile
    rows = [tuple(x.strip() for x in r) for r in ledger_rows()]
    table = import_map_table()

    def tree(files):
        d = tempfile.mkdtemp(prefix="s1selftest_")
        for rel, body in files.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8").write(body)
        return d

    # (a) module-level import fitz under a fake om/ copy is flagged by the copyleft scanner.
    d = tree({"om/__init__.py": "", "om/pdfbad.py": "import fitz\n"})
    hits, _n = copyleft_hits(d)
    assert any("fitz" in h for h in hits), f"copyleft scanner missed module-level fitz: {hits}"
    # fitz is also rejected by the ledger import check (unmapped, or mapped to a skip/isolated row).
    unm, bad, _m = isolated_violations(third_party_imports(d, True), rows, table)
    assert any("fitz" in x or "pymupdf" in x.lower() for x in unm + bad), f"fitz not flagged by import check: {unm} {bad}"
    # (b) module-level import uno in om/recalc.py still fails.
    d = tree({"om/__init__.py": "", "om/recalc.py": "import uno\n"})
    _u, bad, _m = isolated_violations(third_party_imports(d, True), rows, table)
    assert any("module level" in b for b in bad), f"module-level uno not flagged: {bad}"
    # (c) function-level and try/except imports in om/recalc.py pass.
    d = tree({"om/__init__.py": "", "om/recalc.py":
              "def f():\n    import uno\n    from com.sun.star.beans import PropertyValue\n"
              "try:\n    import uno as u2\nexcept ImportError:\n    u2 = None\n"})
    _u, bad, _m = isolated_violations(third_party_imports(d, True), rows, table)
    assert not bad, f"lazy uno wrongly flagged: {bad}"
    # (d) the same lazy import in any other file still fails.
    d = tree({"om/__init__.py": "", "om/other.py": "def f():\n    import uno\n"})
    _u, bad, _m = isolated_violations(third_party_imports(d, True), rows, table)
    assert any("uno" in b for b in bad), f"uno in non-allowed file not flagged: {bad}"
    return "4 scenarios"


def main() -> int:
    w = max(len(n) for n, _, _ in RESULTS)
    fails = sum(not ok for _, ok, _ in RESULTS)
    for n, ok, d in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {n.ljust(w)}  {d}")
    print(f"\nS1 gate: {len(RESULTS) - fails}/{len(RESULTS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
