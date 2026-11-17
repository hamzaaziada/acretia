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

# pip distribution -> ledger repo. A value without '/' is matched EXACTLY against the repo *name* component
# (last path segment, parenthetical suffix dropped, case-insensitive, '-'/'_' equivalent). A value with '/' is
# matched against the full owner/name id. Never a substring match (F1: 'anthropic' must not hit 'anthropics/skills').
DIST_TO_REPO = {"python-pptx": "scanny/python-pptx", "pptx": "scanny/python-pptx", "fonttools": "fonttools/fonttools",
                "pillow": "python-pillow/Pillow", "arabic-reshaper": "mpcabd/python-arabic-reshaper",
                "python-bidi": "MeirKriheli/python-bidi", "duckdb": "duckdb/duckdb", "docling": "docling-project/docling",
                "edgartools": "dgunning/edgartools", "financetoolkit": "JerBouma/FinanceToolkit",
                "crawl4ai": "unclecode/crawl4ai", "openpyxl": "openpyxl/openpyxl", "pdfplumber": "jsvine/pdfplumber",
                "pypdfium2": "pypdfium2-team/pypdfium2", "pdfminer.six": "pdfminer/pdfminer.six",
                "anthropic": "anthropics/anthropic-sdk-python", "gpt-researcher": "assafelovic/gpt-researcher",
                "unstructured": "Unstructured-IO/unstructured", "mcp": "modelcontextprotocol/python-sdk",
                "formulon": "libraz/formulon", "pyyaml": "yaml/pyyaml", "lxml": "lxml/lxml",
                "xlsxwriter": "jmcnamara/XlsxWriter", "pypdf": "py-pdf/pypdf", "psycopg": "psycopg/psycopg",
                "pymupdf": "pymupdf/PyMuPDF", "fitz": "pymupdf/PyMuPDF"}


def norm(s: str) -> str:
    return s.strip().lower().replace("_", "-")


def repo_id(repo: str) -> str:
    """Normalised full id of a ledger repo cell: parenthetical suffix dropped, e.g. 'facebook/react (react@18)'."""
    return norm(re.sub(r"\s*\(.*\)\s*$", "", repo.strip()))


def repo_name(repo: str) -> str:
    """Normalised repo *name* component (last path segment)."""
    return repo_id(repo).rstrip("/").split("/")[-1]


def row_matches(target: str, rows) -> list:
    """Ledger rows matching target exactly: 'owner/name' -> full id (or same name under a different host path),
    bare 'name' -> repo name component. Never substring."""
    t = norm(target)
    if "/" in t:
        return [r for r in rows if repo_id(r[0]) == t or repo_id(r[0]).endswith("/" + t)]
    return [r for r in rows if repo_name(r[0]) == t]


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


def _notes_map(heading_re, skip_headers):
    """Parse a '<heading>' section of docs/ledger-notes.md (arrow lines or a markdown table) into {lhs: rhs}."""
    p = os.path.join(ROOT, "docs", "ledger-notes.md")
    out: dict[str, str] = {}
    if not os.path.exists(p):
        return out
    txt = open(p, encoding="utf-8").read()
    m = re.search(r"^#+[^\n]*" + heading_re + r"[^\n]*\n(.*?)(?=^#+\s|\Z)", txt, re.I | re.M | re.S)
    if not m:
        return out
    for ln in m.group(1).splitlines():
        ln = ln.strip()
        if re.match(r"^\|[\s:|-]+\|?$", ln):
            continue
        if ln.startswith("|"):
            cells = [c.strip(" `*") for c in ln.strip("|").split("|")]
            if len(cells) >= 2 and cells[0].lower() not in skip_headers:
                out[norm(cells[0])] = cells[1].split()[0].lower() if cells[1] else ""
            continue
        a = re.match(r"^[-*]?\s*[`*]*([A-Za-z0-9_.\-]+)[`*]*\s*(?:→|->)\s*[`*]*([A-Za-z0-9_.\-/]+)", ln)
        if a:
            out[norm(a.group(1))] = a.group(2).lower()
    return {k: v for k, v in out.items() if v}


def import_map_table():
    """'Import-name -> ledger row map' section of docs/ledger-notes.md."""
    return _notes_map(r"import-name", ("import", "import name", "import-name", "import_name", "name"))


def dist_map_table():
    """Optional 'Distribution -> ledger row map' section of docs/ledger-notes.md."""
    return _notes_map(r"distribution", ("distribution", "dist", "package", "pip", "name"))


def dist_target(dist, dist_table):
    d = norm(dist)
    return dist_table.get(d) or {norm(k): v for k, v in DIST_TO_REPO.items()}.get(d) or d


def missing_dists(dists, rows, dist_table):
    return [d for d in sorted(dists) if not row_matches(dist_target(d, dist_table), rows)]


@check("ledger: every declared dependency has a ledger row (exact repo-name match, no substrings)")
def _():
    rows = [tuple(x.strip() for x in r) for r in ledger_rows()]
    dists = declared_dists()
    missing = missing_dists(dists, rows, dist_map_table())
    assert not missing, f"no ledger row (exact name match) for: {missing}"
    return f"{len(dists)} declared deps"


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
# Well-known import-name != project-name pairs, used after the ledger-notes map and before DIST_TO_REPO.
# Values follow row_matches(): 'owner/name' = full id, bare name = exact repo-name component.
IMPORT_ALIASES = {"pil": "python-pillow/Pillow", "bidi": "MeirKriheli/python-bidi", "pptx": "scanny/python-pptx",
                  "yaml": "yaml/pyyaml", "pdfminer": "pdfminer/pdfminer.six", "fonttools": "fonttools/fonttools",
                  "bs4": "beautifulsoup", "fitz": "pymupdf/PyMuPDF", "pymupdf": "pymupdf/PyMuPDF",
                  "uno": "LibreOffice/core", "com": "LibreOffice/core", "edgar": "dgunning/edgartools",
                  "arabic_reshaper": "mpcabd/python-arabic-reshaper", "docling_core": "docling-project/docling-core",
                  "docling_parse": "docling-project/docling-parse", "pypdfium2": "pypdfium2-team/pypdfium2"}


def _namespace_dirs(root):
    """Top-level dirs (not hidden, not reference/) holding at least one .py anywhere under them (PEP 420 namespaces)."""
    out = []
    for fn in sorted(os.listdir(root)):
        full = os.path.join(root, fn)
        if fn.startswith(".") or fn == "reference" or not os.path.isdir(full):
            continue
        if any(True for _ in py_files(fn, root=root)):
            out.append(fn)
    return out


def first_party_collisions(root=None, rows=None):
    """Auto-detected first-party dir names that shadow a stdlib module or a ledger-row repo name."""
    root = root or ROOT
    if rows is None:
        rows = [tuple(x.strip() for x in r) for r in ledger_rows()]
    return [d for d in _namespace_dirs(root)
            if d not in FIRST_PARTY and (d in sys.stdlib_module_names or row_matches(d, rows))]


def first_party_names(root=None, rows=None):
    root = root or ROOT
    names = set(FIRST_PARTY)
    for fn in os.listdir(root):
        if fn.endswith(".py"):
            names.add(fn[:-3])
        elif os.path.isdir(os.path.join(root, fn)) and os.path.exists(os.path.join(root, fn, "__init__.py")):
            names.add(fn)
    bad = set(first_party_collisions(root, rows))
    names |= {d for d in _namespace_dirs(root) if d not in bad}
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


def isolated_violations(found, rows, table):
    """Return (unmapped, bad_dec). found is third_party_imports(with_scope=True). An allow-listed pair is
    permitted only when every such import in that file is inside a function body or try/except."""
    unmapped, bad_dec, n_mapped = [], [], 0
    for name in sorted(found):
        key = norm(name)
        target = table.get(key) or {norm(k): v for k, v in IMPORT_ALIASES.items()}.get(key) \
            or {norm(k): v for k, v in DIST_TO_REPO.items()}.get(key) or key
        matched = row_matches(target, rows)
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


@check("first-party dirs: no namespace dir shadows a stdlib module or a ledger-row repo name")
def _():
    bad = first_party_collisions()
    assert not bad, "first-party directory name collides with stdlib/ledger module: " + ", ".join(bad)
    return f"{len(_namespace_dirs(ROOT))} namespace/first-party dirs, 0 collisions"


@check("self-test: namespace dir (no __init__.py, .py inside) is first-party; hidden/reference/.py-less dirs and collisions are not")
def _():
    import tempfile
    d = tempfile.mkdtemp(prefix="s1ns_")
    for rel in ("evals/corpus/a.py", "reference/x/b.py", ".hid/c.py", "docsonly/readme.md", "json/d.py", "fitzns/e.py"):
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write("x = 1\n" if rel.endswith(".py") else "x\n")
    rows = [("pymupdf/fitzns", "x", "MIT", "adopt", "r")]
    fp = first_party_names(d, rows)
    assert "evals" in fp, f"namespace dir not first-party: {fp}"
    assert not ({"reference", ".hid", "docsonly"} & fp), f"excluded dir treated as first-party: {fp}"
    assert first_party_collisions(d, rows) == ["fitzns", "json"], first_party_collisions(d, rows)
    assert not ({"json", "fitzns"} & fp), f"colliding dir wrongly first-party: {fp}"
    open(os.path.join(d, "om_x.py"), "w").write("import evals.corpus\n")
    os.makedirs(os.path.join(d, "om"), exist_ok=True)
    open(os.path.join(d, "om", "m.py"), "w").write("from evals.corpus import a\n")
    assert "evals" not in third_party_imports(d), "evals still reported as third-party"
    return "namespace rule + collision rule"


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
    assert any(x.startswith("fitz") for x in bad), f"fitz not reported as a skip/isolated violation: {unm} {bad}"
    assert any("skip" in x for x in bad if x.startswith("fitz")), f"fitz not mapped to the skip row: {bad}"
    # an import with no exact ledger mapping is reported as unmapped, not silently accepted.
    d = tree({"om/__init__.py": "", "om/x.py": "import totallyunknownpkg\nimport anthropic\n"})
    unm, _b, _m = isolated_violations(third_party_imports(d, True), rows, table)
    assert any(x.startswith("totallyunknownpkg") for x in unm), f"unknown import not unmapped: {unm}"
    assert not any(r[0] == "anthropics/skills" for r in row_matches(IMPORT_ALIASES.get("anthropic", "anthropic"), rows))
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
    return "4 scenarios + unmapped import"


@check("self-test: exact matching (anthropic does not match anthropics/skills; python-pptx matches scanny/python-pptx)")
def _():
    fake = [("anthropics/skills", "x", "Apache-2.0", "borrow_ideas", "r"),
            ("anthropics/financial-services", "x", "Apache-2.0", "borrow_ideas", "r"),
            ("scanny/python-pptx", "x", "MIT", "adopt", "r"),
            ("facebook/react (react@18.3.1)", "x", "MIT", "adopt", "r")]
    assert row_matches("anthropic", fake) == [], "bare 'anthropic' matched a longer repo name"
    assert missing_dists({"anthropic"}, fake, {}) == ["anthropic"], "anthropic dependency false-passed"
    assert missing_dists({"python-pptx", "pptx"}, fake, {}) == [], "python-pptx should match scanny/python-pptx"
    assert row_matches("skills", fake) and row_matches("React", fake), "exact name / parenthetical match broken"
    assert row_matches("anthropics", fake) == [], "owner component must not match"
    assert row_matches("python_pptx", fake), "'-'/'_' normalisation broken"
    return "5 assertions"


NOTICE_LICENCE = re.compile(r"APACHE|MPL|BSD|LGPL", re.I)
NOTICE_REASON = re.compile(r"attribution|notice", re.I)


def notice_required(rows):
    return [r for r in rows if r[3] == "adopt" and (NOTICE_LICENCE.search(r[2]) or NOTICE_REASON.search(r[4]))]


def notice_missing(rows, text):
    t = text.lower().replace("_", "-")
    return [r[0] for r in rows
            if not re.search(r"(?<![a-z0-9])" + re.escape(repo_name(r[0])) + r"(?![a-z0-9])", t)]


@check("notices: THIRD_PARTY_NOTICES.md exists and names every adopt row needing notice (Apache/MPL/BSD/LGPL/attribution/NOTICE)")
def _():
    p = os.path.join(ROOT, "THIRD_PARTY_NOTICES.md")
    assert os.path.exists(p), "THIRD_PARTY_NOTICES.md missing at repo root"
    rows = [tuple(x.strip() for x in r) for r in ledger_rows()]
    need = notice_required(rows)
    missing = notice_missing(need, open(p, encoding="utf-8").read())
    assert not missing, f"{len(missing)} of {len(need)} rows not named: {missing[:12]}"
    return f"{len(need)} rows named"


@check("self-test: notices check flags missing rows and rejects substring leaks")
def _():
    rows = [("a/foo-bar", "x", "Apache-2.0", "adopt", "r"), ("a/baz", "x", "MIT", "adopt", "must keep attribution line"),
            ("a/quux", "x", "MIT", "adopt", "plain"), ("a/skipped", "x", "BSD-3-Clause", "skip", "r")]
    need = notice_required(rows)
    assert [r[0] for r in need] == ["a/foo-bar", "a/baz"], need
    assert notice_missing(need, "Foo_Bar and nothing else") == ["a/baz"]
    assert notice_missing(need, "foo-bar baz") == []
    assert notice_missing(need, "foo-barista bazaar") == ["a/foo-bar", "a/baz"], "substring leak"
    return "ok"


def main() -> int:
    w = max(len(n) for n, _, _ in RESULTS)
    fails = sum(not ok for _, ok, _ in RESULTS)
    for n, ok, d in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {n.ljust(w)}  {d}")
    print(f"\nS1 gate: {len(RESULTS) - fails}/{len(RESULTS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
