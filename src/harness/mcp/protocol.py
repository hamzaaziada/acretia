"""JSON-RPC 2.0 framing + MCP constants. One JSON message per line (newline-delimited), max 8 MiB."""
from __future__ import annotations

import json

PROTOCOL_VERSION = "2025-06-18"
MAX_MESSAGE_BYTES = 8 * 1024 * 1024

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


class ProtocolError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def error_response(id_, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


def result_response(id_, result) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, ensure_ascii=False, separators=(",", ":"), default=str) + "\n").encode("utf-8")


def decode(line: bytes | str):
    """Parse one line. Raises ProtocolError(-32700) on bad JSON/oversize; returns the parsed object."""
    if isinstance(line, str):
        line = line.encode("utf-8")
    if len(line) > MAX_MESSAGE_BYTES:
        raise ProtocolError(PARSE_ERROR, f"message exceeds {MAX_MESSAGE_BYTES} bytes")
    try:
        return json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError(PARSE_ERROR, f"parse error: {e}") from None


def read_line(stream) -> bytes | None:
    """Read one newline-terminated frame from a binary stream. None at EOF. Oversize frames are drained and
    reported as a ProtocolError so the stream stays in sync."""
    line = stream.readline(MAX_MESSAGE_BYTES + 2)
    if not line:
        return None
    if len(line) > MAX_MESSAGE_BYTES and not line.endswith(b"\n"):
        while True:  # drain the rest of the oversize frame
            rest = stream.readline(65536)
            if not rest or rest.endswith(b"\n"):
                break
        raise ProtocolError(PARSE_ERROR, f"message exceeds {MAX_MESSAGE_BYTES} bytes")
    return line


def validate_request(msg) -> tuple[object, str, dict, bool]:
    """Return (id, method, params, is_notification) or raise ProtocolError(-32600/-32602)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        raise ProtocolError(INVALID_REQUEST, "invalid request: expected a JSON-RPC 2.0 object")
    method = msg.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError(INVALID_REQUEST, "invalid request: method must be a non-empty string")
    id_ = msg.get("id")
    if "id" in msg and (isinstance(id_, bool) or not isinstance(id_, (str, int, float)) ):
        raise ProtocolError(INVALID_REQUEST, "invalid request: id must be a string or number")
    params = msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ProtocolError(INVALID_PARAMS, "invalid params: must be an object")
    return id_, method, params, "id" not in msg
