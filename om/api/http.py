"""HTTP contract for the product API (SPEC §2.1): errors, routes, context, responses, SSE, uploads."""
from __future__ import annotations

import json as _json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

ROLE_ORDER = {"public": 0, "viewer": 1, "member": 2, "owner": 3}
SSE_KEEPALIVE = b": keep-alive\n\n"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, hint: str | None = None, headers: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.hint = status, code, message, hint
        self.headers = dict(headers or {})

    def body(self) -> dict:
        err = {"code": self.code, "message": self.message}
        if self.hint is not None:
            err["hint"] = self.hint
        return {"error": err}


_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _compile(pattern: str) -> re.Pattern:
    out, pos = [], 0
    for m in _PARAM.finditer(pattern):
        out.append(re.escape(pattern[pos:m.start()]))
        out.append(f"(?P<{m.group(1)}>[^/]+)")
        pos = m.end()
    out.append(re.escape(pattern[pos:]))
    return re.compile("^" + "".join(out) + "$")


@dataclass
class Route:
    method: str
    pattern: str
    handler: Callable[..., Any]
    role: str = "member"
    csrf: bool = True
    _rx: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        self.method = self.method.upper()
        self._rx = _compile(self.pattern)

    def match_path(self, path: str) -> dict | None:
        m = self._rx.match(path)
        return {k: urllib.parse.unquote(v) for k, v in m.groupdict().items()} if m else None

    def match(self, method: str, path: str) -> dict | None:
        if method.upper() != self.method:
            return None
        return self.match_path(path)


class Router:
    def __init__(self, routes):
        self.routes = list(routes)

    def resolve(self, method: str, path: str):
        allowed: list[str] = []
        for r in self.routes:
            params = r.match_path(path)
            if params is None:
                continue
            if r.method == method.upper():
                return r, params
            allowed.append(r.method)
        if allowed:
            allow = ", ".join(sorted(set(allowed)))
            raise ApiError(405, "method_not_allowed", f"{method.upper()} is not allowed on {path}.",
                           f"Use one of: {allow}.", headers={"Allow": allow})
        raise ApiError(404, "not_found", "No such endpoint.")


def _noop_audit(ctx, action, target, detail):
    return None


@dataclass(slots=True)
class RequestContext:
    method: str = "GET"
    path: str = "/"
    params: dict = field(default_factory=dict)
    query: dict = field(default_factory=dict)
    body: bytes = b""
    json: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)
    conn: Any = None
    blobs: Any = None
    data_dir: Path | None = None
    user: dict | None = None
    org_id: str | None = None
    role: str | None = None
    session_id: str | None = None
    _audit: Callable[..., Any] = _noop_audit

    def audit(self, action: str, target: str = "", detail: dict | None = None) -> None:
        self._audit(self, action, target, detail)

    def require(self, role: str) -> None:
        if ROLE_ORDER.get(self.role or "public", 0) < ROLE_ORDER[role]:
            raise ApiError(403, "forbidden", f"This action needs {role} access.",
                           f"Ask an owner of {self.org_id or 'your organization'} for {role} access.")


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/octet-stream"
    headers: dict | None = None


class SSE:
    def __init__(self, iterator, last_event_id=None):
        self.iterator = iterator
        self.last_event_id = last_event_id


def _json_bytes(obj) -> bytes:
    return _json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def render(result):
    """Normalise a handler return into (status, headers, body_bytes | SSE)."""
    if isinstance(result, SSE):
        return 200, {"Content-Type": "text/event-stream", "Cache-Control": "no-store", "X-Accel-Buffering": "no"}, result
    if isinstance(result, Response):
        h = {"Content-Type": result.content_type}
        h.update(result.headers or {})
        return result.status, h, bytes(result.body)
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
        return result[0], {"Content-Type": "application/json; charset=utf-8"}, _json_bytes(result[1])
    if isinstance(result, (dict, list)):
        return 200, {"Content-Type": "application/json; charset=utf-8"}, _json_bytes(result)
    if result is None:
        return 204, {}, b""
    raise TypeError(f"unsupported handler result: {type(result).__name__}")


def sse_format(event_id, event: str, data: dict) -> bytes:
    event = str(event).replace("\r", " ").replace("\n", " ")
    lines = []
    if event_id is not None:
        lines.append("id: " + str(event_id).replace("\r", " ").replace("\n", " "))
    lines.append("event: " + event)
    lines.append("data: " + _json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def parse_json(body: bytes, limit: int = 2_000_000):
    if len(body) > limit:
        raise ApiError(413, "too_large", f"The request body is larger than {limit} bytes.",
                       "Send less data, or upload large files as documents.")
    if not body or not body.strip():
        return None
    try:
        return _json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ApiError(400, "bad_json", "The request body is not valid JSON.",
                       "Send UTF-8 JSON with Content-Type: application/json.") from None


_BOUNDARY = re.compile(r'boundary=(?:"([^"]+)"|([^;\s]+))', re.I)
_CD_PARAM = re.compile(r'(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;\s]*))')


def parse_multipart(body: bytes, content_type: str, max_bytes: int):
    """Minimal RFC 7578 parser -> [(field_name, filename|None, content_type, bytes)]."""
    if len(body) > max_bytes:
        raise ApiError(413, "too_large", f"The upload is larger than {max_bytes} bytes.", "Split it into smaller uploads.")
    m = _BOUNDARY.search(content_type or "")
    if not m or not (m.group(1) or m.group(2)):
        raise ApiError(400, "bad_multipart", "The upload has no multipart boundary.",
                       "Send multipart/form-data with a boundary parameter.")
    delim = b"--" + (m.group(1) or m.group(2)).encode("latin-1")
    chunks = body.split(delim)
    out = []
    for chunk in chunks[1:]:
        if chunk.startswith(b"--"):
            break
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        head, sep, content = chunk.partition(b"\r\n\r\n")
        if not sep:
            raise ApiError(400, "bad_multipart", "Malformed multipart part.", "Re-send the upload.")
        if content.endswith(b"\r\n"):
            content = content[:-2]
        hdrs = {}
        for line in head.decode("utf-8", "replace").split("\r\n"):
            k, _, v = line.partition(":")
            hdrs[k.strip().lower()] = v.strip()
        disp = hdrs.get("content-disposition", "")
        params = {k.lower(): (a if a or not b else b).replace('\\"', '"') for k, a, b in _CD_PARAM.findall(disp)}
        name = params.get("name")
        if name is None:
            raise ApiError(400, "bad_multipart", "A multipart part has no field name.", "Re-send the upload.")
        out.append((name, params.get("filename"), hdrs.get("content-type", "text/plain"), content))
    return out


def sanitize_filename(name) -> str:
    s = str(name or "")
    s = re.split(r"[\\/]", s)[-1]
    s = re.sub(r"[^\w.\- ]", "_", s)
    s = re.sub(r"\.{2,}", ".", s)
    s = re.sub(r"_{2,}", "_", s)
    s = re.sub(r" {2,}", " ", s)
    s = s.strip(" .")
    s = s.lstrip(".")
    if len(s) > 180:
        stem, dot, ext = s.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            s = stem[: 180 - len(ext) - 1] + "." + ext
        else:
            s = s[:180]
        s = s.rstrip(" .")
    return s or "file"
