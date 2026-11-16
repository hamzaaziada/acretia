"""MCPClient: talks to a spawned stdio MCP server (list argv, no shell) or an in-process MCPServer."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading

from . import protocol as P


class MCPError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class MCPClient:
    def __init__(self, timeout: float = 30):
        self.timeout = timeout
        self._proc = None
        self._server = None
        self._id = 0
        self._q: queue.Queue = queue.Queue()
        self.server_info: dict = {}

    @classmethod
    def spawn(cls, argv, env=None, timeout: float = 30, cwd=None) -> "MCPClient":
        if isinstance(argv, str) or not argv:
            raise MCPError("argv must be a non-empty list (no shell)")
        c = cls(timeout)
        full_env = dict(os.environ)
        full_env.update(env or {})
        try:
            c._proc = subprocess.Popen([str(a) for a in argv], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, env=full_env, cwd=cwd, shell=False)
        except OSError as e:
            raise MCPError(f"cannot start MCP server: {e}") from None
        threading.Thread(target=c._pump, daemon=True).start()
        return c

    @classmethod
    def inprocess(cls, server, timeout: float = 30) -> "MCPClient":
        c = cls(timeout)
        c._server = server
        return c

    def _pump(self):
        try:
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    break
                self._q.put(line)
        finally:
            self._q.put(None)

    # ---------------------------------------------------------------------------------------------- rpc
    def _send(self, msg: dict):
        try:
            self._proc.stdin.write(P.encode(msg))
            self._proc.stdin.flush()
        except (OSError, ValueError):
            raise MCPError(f"MCP server exited (code {self._proc.poll()}) before the request was sent") from None

    def _request(self, method: str, params: dict | None = None):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        if self._server is not None:
            resp = self._server.handle(json.loads(json.dumps(msg)))
        else:
            self._send(msg)
            resp = self._await(self._id)
        if "error" in resp:
            e = resp["error"]
            raise MCPError(f"{method}: {e.get('message')}", e.get("code"))
        return resp["result"]

    def _await(self, id_):
        while True:
            try:
                line = self._q.get(timeout=self.timeout)
            except queue.Empty:
                self.close()
                raise MCPError(f"MCP server timed out after {self.timeout}s") from None
            if line is None:
                self._q.put(None)
                raise MCPError(f"MCP server exited unexpectedly (code {self._proc.poll()})")
            try:
                resp = P.decode(line)
            except P.ProtocolError:
                continue
            if isinstance(resp, dict) and resp.get("id") == id_:
                return resp

    def _notify(self, method: str):
        msg = {"jsonrpc": "2.0", "method": method}
        if self._server is not None:
            self._server.handle(msg)
        else:
            self._send(msg)

    # ---------------------------------------------------------------------------------------------- api
    def initialize(self) -> dict:
        res = self._request("initialize", {"protocolVersion": P.PROTOCOL_VERSION, "capabilities": {},
                                           "clientInfo": {"name": "acretia-harness", "version": "0.1.0"}})
        self.server_info = res.get("serverInfo", {})
        self._notify("notifications/initialized")
        return res

    def list_tools(self) -> list:
        return self._request("tools/list", {})["tools"]

    def call_tool(self, name: str, args: dict | None = None) -> dict:
        """Returns the structured result; raises MCPError if the tool reported isError."""
        res = self._request("tools/call", {"name": name, "arguments": args or {}})
        if res.get("isError"):
            raise MCPError(f"tool {name} failed: " + (res.get("content") or [{}])[0].get("text", ""))
        return res.get("structuredContent", {})

    def ping(self) -> bool:
        return self._request("ping", {}) == {}

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            return
        p = self._proc
        if p is None:
            return
        try:
            p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        try:
            p.stdout.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
