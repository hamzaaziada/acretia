#!/usr/bin/env python3
"""Stdlib-only secret scanner (S7.5a).

Scans git-tracked files (or the paths given) for high-signal secret patterns.
Prints file:line and the pattern name with the value masked (first 4 chars only).
Exit 0 when clean, 1 on findings.

Suppress a line with an inline `# secret-scan: allow` marker. Obviously fake values
under tests/fixtures/** (containing fake/test/dummy/example) and the AWS documentation
example keys are allowed.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOW_MARKER = "secret-scan: allow"
MAX_BYTES = 2_000_000
AWS_DOC_KEYS = ("AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
FAKE_WORDS = ("fake", "test", "dummy", "example")
# Obvious placeholders in the value itself (any file). "test" only counts inside tests/fixtures/**.
PLACEHOLDERS = ("fake", "dummy", "example", "placeholder", "changeme", "123456", "abcdef", "xxxx", "your_", "your-")
ENV_OK = (".env.example", ".env.sample", ".env.template", ".env.dist")
NB = r"(?<![A-Za-z0-9_-])"  # not preceded by an identifier char: "task-requiring" must not match sk-

# (name, regex, group holding the secret, min entropy or None)
PATTERNS = [
    ("aws-access-key-id", re.compile(NB + r"(AKIA[0-9A-Z]{16})(?![A-Za-z0-9])"), 1, None),
    ("aws-secret-key", re.compile(r"(?i)aws[\w .-]{0,30}?(?:secret|private)[\w .-]{0,20}?[:=]\s*[\"']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])"), 1, 3.5),
    ("github-token", re.compile(NB + r"((?:gh[pous]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255}))"), 1, None),
    ("slack-token", re.compile(NB + r"(xox[abprs]-[A-Za-z0-9-]{10,})"), 1, None),
    ("stripe-key", re.compile(NB + r"((?:sk|rk)_live_[A-Za-z0-9]{16,})"), 1, None),
    ("anthropic-key", re.compile(NB + r"(sk-ant-[A-Za-z0-9_-]{20,})"), 1, None),
    ("openai-style-key", re.compile(NB + r"(sk-(?!ant-)[A-Za-z0-9_-]{20,})"), 1, 3.5),
    ("google-api-key", re.compile(NB + r"(AIza[0-9A-Za-z_-]{35})(?![0-9A-Za-z_-])"), 1, None),
    ("private-key-block", re.compile(r"(-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----)"), 1, None),
    ("generic-secret-assignment", re.compile(
        r"(?i)(?:api[_-]?key|secret|token|passw(?:or)?d)[\w-]*[\"']?\s*[:=]\s*[\"']([^\"'\s]{12,})[\"']"), 1, 3.5),
]


def entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def mask(s: str) -> str:
    return s[:4] + "*" * min(max(len(s) - 4, 0), 12)


def _is_fixture(rel: str) -> bool:
    return rel.replace(os.sep, "/").startswith("tests/fixtures/")


def scan_text(rel: str, text: str):
    """Yield (lineno, pattern_name, masked_value) findings for one file's text."""
    fixture = _is_fixture(rel)
    for i, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARKER in line or len(line) > 5000:
            continue
        for name, rx, grp, min_ent in PATTERNS:
            for m in rx.finditer(line):
                val = m.group(grp)
                if any(k in val for k in AWS_DOC_KEYS):
                    continue
                if fixture and any(w in line.lower() for w in FAKE_WORDS):
                    continue
                low = val.lower()
                if any(w in low for w in PLACEHOLDERS) or (name == "generic-secret-assignment" and re.fullmatch(r"[A-Z][A-Z0-9_]+", val)):
                    continue  # placeholder, or an ENV_VAR_NAME rather than a value
                if min_ent is not None and entropy(val) < min_ent:
                    continue
                if name == "openai-style-key" and not re.search(r"\d", val):
                    continue
                yield i, name, mask(val)


def is_env_file(rel: str) -> bool:
    base = os.path.basename(rel)
    return (base == ".env" or base.startswith(".env.")) and base not in ENV_OK


def scan_file(path: str, rel: str):
    out = []
    if is_env_file(rel):
        out.append((1, "env-file-committed", "(file)"))
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return out
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return out
    if b"\0" in raw[:8192]:
        return out
    out.extend(scan_text(rel, raw.decode("utf-8", "replace")))
    return out


def tracked_files(root: str):
    r = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True)
    if r.returncode != 0:
        return None
    return [p for p in r.stdout.decode().split("\0") if p]


def walk(paths, root):
    for p in paths:
        ap = p if os.path.isabs(p) else os.path.join(root, p)
        if os.path.isdir(ap):
            for dp, dn, fs in os.walk(ap):
                dn[:] = [d for d in dn if d not in (".git", "__pycache__", "node_modules", ".venv")]
                for f in fs:
                    yield os.path.join(dp, f)
        else:
            yield ap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", help="files/dirs to scan (default: git ls-files)")
    ap.add_argument("--all-history", default="false", choices=["true", "false"],
                    help="true scans every commit's added lines via git log -p (slow)")
    ap.add_argument("--root", default=ROOT)
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    findings = []
    if a.paths:
        files = list(walk(a.paths, root))
    else:
        tr = tracked_files(root)
        files = [os.path.join(root, p) for p in tr] if tr is not None else list(walk(["."], root))
    n = 0
    for f in files:
        if not os.path.isfile(f):
            continue
        n += 1
        rel = os.path.relpath(f, root)
        for ln, name, masked in scan_file(f, rel):
            findings.append((rel, ln, name, masked))
    if a.all_history == "true":
        r = subprocess.run(["git", "log", "-p", "--all", "--no-color", "-U0"], cwd=root, capture_output=True)
        cur = "?"
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            if line.startswith("+++ b/"):
                cur = line[6:]
            elif line.startswith("+") and not line.startswith("+++"):
                for ln, name, masked in scan_text(cur, line[1:]):
                    findings.append((cur + " (history)", 0, name, masked))
    for rel, ln, name, masked in sorted(set(findings)):
        print(f"{rel}:{ln}: {name}: {masked}")
    print(f"secret_scan: {n} files scanned, {len(set(findings))} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
