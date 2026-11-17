"""Deck version store (S3.12, parity #37, #39). Offline, stdlib + lxml.

Layout: ``<ACRETIA_DATA or ./data>/deck_versions/<deck_id>/``
  blobs/<sha256>.pptx   content-addressed deck bytes
  v0001.json ...        manifest: version, sha256, size, created, note, annotations, spec, parts {name: sha256}, rolled_back_to
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from lxml import etree

from om.deck import revise

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class VersionError(ValueError):
    pass


def _root(deck_id: str) -> Path:
    if not isinstance(deck_id, str) or not _ID.fullmatch(deck_id) or ".." in deck_id:
        raise VersionError(f"bad deck id {deck_id!r}")
    base = os.environ.get("ACRETIA_DATA")
    return (Path(base) if base else Path(__file__).resolve().parents[2] / "data") / "deck_versions" / deck_id


def _manifest(deck_id: str, n: int) -> dict:
    p = _root(deck_id) / f"v{int(n):04d}.json"
    if not p.exists():
        raise VersionError(f"deck {deck_id!r} has no version {n}")
    return json.loads(p.read_text(encoding="utf-8"))


def list_numbers(deck_id: str) -> list[int]:
    root = _root(deck_id)
    if not root.exists():
        return []
    return sorted(int(m.group(1)) for p in root.glob("v*.json") if (m := re.fullmatch(r"v(\d+)\.json", p.name)))


def _save(deck_id: str, data: bytes, spec, note: str, annotations, extra: dict | None = None) -> int:
    root = _root(deck_id)
    (root / "blobs").mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    blob = root / "blobs" / f"{sha}.pptx"
    if not blob.exists():
        tmp = blob.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, blob)
    _, files = revise.read_zip(data)
    doc = {"deck_id": deck_id, "sha256": sha, "size": len(data), "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "note": note or "", "annotations": [*(annotations or [])], "spec": spec,
           "parts": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}, **(extra or {})}
    n = max(list_numbers(deck_id), default=0) + 1
    while True:
        doc["version"] = n
        try:
            with open(root / f"v{n:04d}.json", "x", encoding="utf-8") as f:
                json.dump(doc, f, indent=1, sort_keys=True)
            return n
        except FileExistsError:
            n += 1


def save(deck_id: str, pptx_bytes: bytes, spec, *, note: str = "", annotations=None) -> int:
    return _save(deck_id, pptx_bytes, spec, note, annotations)


def list(deck_id: str) -> list[dict]:  # noqa: A001 - public API name
    out = []
    for n in list_numbers(deck_id):
        m = _manifest(deck_id, n)
        row = {k: m[k] for k in ("version", "sha256", "size", "created", "note", "annotations")}
        if "rolled_back_to" in m:
            row["rolled_back_to"] = m["rolled_back_to"]
        out.append(row)
    return out


def get(deck_id: str, n: int) -> bytes:
    m = _manifest(deck_id, n)
    data = (_root(deck_id) / "blobs" / f"{m['sha256']}.pptx").read_bytes()
    if hashlib.sha256(data).hexdigest() != m["sha256"]:
        raise VersionError(f"version {n} of {deck_id!r} is corrupt (sha256 mismatch)")
    return data


def get_spec(deck_id: str, n: int):
    return _manifest(deck_id, n)["spec"]


def rollback(deck_id: str, n: int) -> bytes:
    data = get(deck_id, n)
    _save(deck_id, data, get_spec(deck_id, n), f"rollback to v{n}", [], {"rolled_back_to": int(n)})
    return data


# ---------------------------------------------------------------- compare
def _shape_prints(files: dict, slide_part: str) -> dict[str, str]:
    root = etree.fromstring(files[slide_part])
    rels = {r["id"]: r for r in revise._rels(files, slide_part)}
    out: dict[str, str] = {}
    for c in root.iter(f"{{{_P}}}cNvPr"):
        shape = c.getparent().getparent()
        if etree.QName(shape).localname not in ("sp", "graphicFrame", "pic", "cxnSp"):
            continue
        h = hashlib.sha256(etree.tostring(shape, method="c14n"))
        for ch in shape.iter(f"{{{_C}}}chart"):
            r = rels.get(ch.get(f"{{{_R}}}id"))
            if r:
                h.update(files.get(revise._resolve(slide_part, r["target"]), b""))
        for bl in shape.iter(f"{{{_A}}}blip"):
            r = rels.get(bl.get(f"{{{_R}}}embed"))
            if r:
                h.update(files.get(revise._resolve(slide_part, r["target"]), b""))
        out[c.get("name")] = h.hexdigest()
    return out


def _slide_sig(files: dict, part: str) -> str:
    h = hashlib.sha256(files[part])
    for r in sorted(revise._rels(files, part), key=lambda r: r["id"]):
        if r["mode"] == "External" or r["kind"] in revise._SHARED:
            continue
        t = revise._resolve(part, r["target"])
        for p in [t, *revise.owned_parts(files, t)]:
            if p in files:
                h.update(files[p])
    return h.hexdigest()


def compare(deck_id: str, a: int, b: int) -> dict:
    fa, fb = revise.read_zip(get(deck_id, a))[1], revise.read_zip(get(deck_id, b))[1]
    sa, sb = revise.slide_parts(fa), revise.slide_parts(fb)
    changed, same, shapes = [], [], {}
    for i in range(max(len(sa), len(sb))):
        if i >= len(sa) or i >= len(sb):
            changed.append(i + 1)
            continue
        if _slide_sig(fa, sa[i]) == _slide_sig(fb, sb[i]):
            same.append(i + 1)
            continue
        changed.append(i + 1)
        pa, pb = _shape_prints(fa, sa[i]), _shape_prints(fb, sb[i])
        shapes[i + 1] = sorted(k for k in set(pa) | set(pb) if pa.get(k) != pb.get(k))
    ma, mb = _manifest(deck_id, a)["parts"], _manifest(deck_id, b)["parts"]
    return {"a": a, "b": b, "changed_slides": changed, "changed_shapes": shapes, "unchanged_slides": same,
            "changed_parts": sorted(k for k in set(ma) | set(mb) if ma.get(k) != mb.get(k))}
