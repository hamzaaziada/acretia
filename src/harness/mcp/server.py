"""MCPServer: serves a ToolRegistry over MCP JSON-RPC (stdio or in-process)."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from ..evidence import EvidenceBundle, check_custody
from ..router import ToolError
from . import protocol as P


class ToolFailure(Exception):
    """A tool ran and failed (reported as isError result, not a protocol error). `data` adds structured fields
    (for example {"code": "xlsx_limit_exceeded"}) to the error result."""

    def __init__(self, message="", data=None):
        super().__init__(message)
        self.data = dict(data or {})


class MCPServer:
    def __init__(self, name: str, registry, evidence_path=None, version: str = "0.1.0"):
        self.name, self.version, self.registry = name, version, registry
        self.evidence = None
        if evidence_path:
            check_custody(Path(evidence_path).parent)       # N3: refuse to start with an unsafe evidence key
            self.evidence = EvidenceBundle(evidence_path, repair=True)     # F20: resume past a torn tail
        self.anchor = None          # last Anchor dict sealed by this server (evidence/seal or close)
        self.seal_error = None
        self.initialized = False
        self.max_concurrency = 4
        self._ev_lock = threading.Lock()

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
        if method == "evidence/seal":
            return self._seal_rpc()
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
            out, is_error = {"error": str(e), **e.data}, True
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
        with self._ev_lock:
            self.evidence.append(name, args, source=src, output=out)

    # -------------------------------------------------------------------------------------------- stdio
    def serve_stdio(self, stdin=None, stdout=None) -> None:
        """Read frames serially; run tools/call on a small worker pool (cap 4) so ping and the rest keep answering
        while a slow tool runs. Writes are serialised by a lock."""
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        wlock = threading.Lock()
        pool = ThreadPoolExecutor(max_workers=self.max_concurrency, thread_name_prefix="mcp-call")

        def write(resp):
            if resp is not None:
                with wlock:
                    stdout.write(P.encode(resp))
                    stdout.flush()

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
                    write(P.error_response(None, e.code, e.message))
                    continue
                if isinstance(msg, dict) and msg.get("method") == "tools/call" and "id" in msg:
                    pool.submit(lambda m=msg: write(self.handle(m)))
                else:
                    write(self.handle(msg))
        finally:
            pool.shutdown(wait=True)
            self.close()

    def seal_evidence(self) -> dict | None:
        """Sign the evidence bundle's current head into the anchor log (F4/N3) and return the Anchor dict
        (None when this server records no evidence). Safe to call repeatedly; each call adds a higher ``seq``."""
        if not self.evidence:
            return None
        with self._ev_lock:
            self.anchor = self.evidence.seal().as_dict()
        return self.anchor

    def _seal_rpc(self) -> dict:
        if not self.evidence:
            raise P.ProtocolError(P.INVALID_REQUEST, "this server records no evidence; nothing to seal")
        try:
            return {"anchor": self.seal_evidence(), "evidence_head": self.evidence.head_hash()}
        except Exception as e:
            raise P.ProtocolError(P.INTERNAL_ERROR, f"evidence seal failed: {type(e).__name__}: {e}") from None

    def close(self) -> None:
        """Seal the evidence bundle (so a later truncation is detectable), then close it. Idempotent; a seal failure
        is kept in ``seal_error`` and reported on stderr instead of raising out of shutdown."""
        if self.evidence:
            if not self.evidence._fh.closed:
                try:
                    self.seal_evidence()
                except Exception as e:      # noqa: BLE001
                    self.seal_error = f"{type(e).__name__}: {e}"
                    print(f"mcp server {self.name}: evidence seal failed: {self.seal_error}", file=sys.stderr)
            self.evidence.close()
