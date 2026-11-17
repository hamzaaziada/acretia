"""Path confinement for engine servers: everything must resolve inside ACRETIA_MCP_ROOT (default cwd)."""
from __future__ import annotations

import os
from pathlib import Path


class PathError(ValueError):
    pass


def root() -> Path:
    return Path(os.path.realpath(os.environ.get("ACRETIA_MCP_ROOT") or os.getcwd()))


def resolve_in_root(p, *, must_exist: bool = True, suffixes: tuple | None = None) -> Path:
    if not isinstance(p, str) or not p or "\x00" in p:
        raise PathError("path must be a non-empty string")
    base = root()
    cand = Path(p)
    if not cand.is_absolute():
        cand = base / cand
    real = Path(os.path.realpath(cand))  # collapses '..' and follows symlinks
    try:
        real.relative_to(base)
    except ValueError:
        raise PathError(f"path escapes the allowed root: {p!r}") from None
    if must_exist and not real.is_file():
        raise PathError(f"no such file: {p!r}")
    if suffixes and real.suffix.lower() not in suffixes:
        raise PathError(f"unsupported file type {real.suffix!r}; expected one of {sorted(suffixes)}")
    return real
