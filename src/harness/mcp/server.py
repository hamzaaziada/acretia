"""MCPServer: serves a ToolRegistry over MCP JSON-RPC (stdio or in-process)."""
from __future__ import annotations

import json
import sys

from ..evidence import EvidenceBundle
from ..router import ToolError
from . import protocol as P


class ToolFailure(Exception):
    """A tool ran and failed (reported as isError result, not a protocol error)."""


class MCPServer:
    def __init__(self, name: str, registry, evidence_path=None, version: str = "0.1.0"):
        self.name, self.version, self.registry = name, version, registry
        self.evidence = EvidenceBundle(evidence_path) if evidence_path else None
        self.initialized = False

    # -------------------------------------------------------------------------------------------- dispatch
    def handle(self, message) -> dict | None:
        """Handle one decoded message; returns the response dict, or None for notifications."""
        if isinstance(message, list):
            return P.error_response(None, P.INVALID_REQUEST, "batch requests are not supported")
        id_ = message.get("id") if isinstance(message, dict) else None
        try:
            id_, method, params, is_note = P.validate_request(message)
            if is_note:
                return None  # notifications (initialized, cancelled, ...) never execute anything
            return P.result_response(id_, self._dispatch(method, params))
        except P.ProtocolError as e:
            return P.error_response(id_ if isinstance(id_, (str, int, float)) else None, e.code, e.message, e.data)
        except Exception as e:  # never crash the loop
            return P.error_response(id_ if isinstance(id_, (str, int, float)) else None, P.INTERNAL_ERROR,
                                    f"internal error: {type(e).__name__}")

    def _dispatch(self, method: str, params: dict):
        if method == "initialize":
            self.initialized = True
            return {"protocolVersion": P.PROTOCOL_VERSION, "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.name, "version": self.version}}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.registry.list()}
        if method == "tools/call":
            return self._call(params)
        raise P.ProtocolError(P.METHOD_NOT_FOUND, f"method not found: {method}")

    def _call(self, params: dict):
        name, args = params.get("name"), params.get("arguments")
        if not isinstance(name, str) or not name:
            raise P.ProtocolError(P.INVALID_PARAMS, "invalid params: name must be a string")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise P.ProtocolError(P.INVALID_PARAMS, "invalid params: arguments must be an object")
        try:
            out = self.registry.call(name, args)
            is_error = False
        except ToolError as e:
            msg = str(e)
            if msg.startswith(("unknown tool", "invalid arguments")):
                raise P.ProtocolError(P.INVALID_PARAMS, msg) from None
            out, is_error = {"error": msg}, True
        except ToolFailure as e:
            out, is_error = {"error": str(e)}, True
        except Exception as e:
            out, is_error = {"error": f"{type(e).__name__}: {e}"}, True
        try:
            text = json.dumps(out, ensure_ascii=False, default=str)
            out = json.loads(text)  # normalise to plain JSON
        except (TypeError, ValueError):
            text = json.dumps({"error": "tool result not serialisable"})
            out, is_error = json.loads(text), True
        self._record(name, args, out)
        res = {"content": [{"type": "text", "text": text}], "isError": is_error}
        if isinstance(out, dict):
            res["structuredContent"] = out
        else:
            res["structuredContent"] = {"result": out}
        return res

    def _record(self, name, args, out):
        if not self.evidence:
            return
        src = args.get("doc_id") if isinstance(args.get("doc_id"), str) and args.get("doc_id") else name
        self.evidence.append(name, args, source=src, output=out)

    # -------------------------------------------------------------------------------------------- stdio
    def serve_stdio(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        try:
            while True:
                try:
                    line = P.read_line(stdin)
                    if line is None:
                        break
                    if not line.strip():
                        continue
                    msg = P.decode(line)
                except P.ProtocolError as e:
                    resp = P.error_response(None, e.code, e.message)
                else:
                    resp = self.handle(msg)
                if resp is not None:
                    stdout.write(P.encode(resp))
                    stdout.flush()
        finally:
            self.close()

    def close(self) -> None:
        if self.evidence:
            self.evidence.close()
