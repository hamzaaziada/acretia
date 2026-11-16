"""MCPClient: talks to a spawned stdio MCP server (list argv, no shell) or an in-process MCPServer."""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time

from . import protocol as P


class MCPError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


ENV_ALLOW = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "PYTHONPATH", "TMPDIR", "SYSTEMROOT", "ACRETIA_EVIDENCE_PATH"}
ENV_ALLOW_PREFIX = ("ACRETIA_MCP_", "ACRETIA_GRID_")
_SECRET_NAME = re.compile(r"(_API_KEY|_TOKEN|_SECRET|_PASSWORD|API_KEY|SECRET_KEY)$", re.I)


def child_env(extra=None, base=None) -> dict:
    """Minimal environment for a spawned MCP server: an allowlist of the parent env plus caller-supplied extras.
    Names that look like credentials (*_API_KEY, *_TOKEN, *_SECRET) never pass, even if supplied explicitly."""
    base = os.environ if base is None else base
    env = {k: v for k, v in base.items() if (k in ENV_ALLOW or k.startswith(ENV_ALLOW_PREFIX))}
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return {k: v for k, v in env.items() if not _SECRET_NAME.search(k)}


class _ChildGone(MCPError):
    """The child process is gone (internal; triggers one respawn)."""


class MCPClient:
    BACKOFF_S = 0.2

    def __init__(self, timeout: float = 30):
        self.timeout = timeout
        self._spawn_args = None
        self._initialized = False
        self.respawns = 0
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
        c._spawn_args = ([str(a) for a in argv], child_env(env), cwd)
        c._start()
        return c

    def _start(self):
        argv, env, cwd = self._spawn_args
        try:
            self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, env=env, cwd=cwd, shell=False)
        except OSError as e:
            raise MCPError(f"cannot start MCP server: {e}") from None
        self._q = queue.Queue()
        threading.Thread(target=self._pump, args=(self._proc, self._q), daemon=True).start()

    def _respawn(self):
        self.respawns += 1
        time.sleep(self.BACKOFF_S * min(self.respawns, 5))
        self.close()
        self._start()
        if self._initialized:
            self._rpc("initialize", {"protocolVersion": P.PROTOCOL_VERSION, "capabilities": {},
                                     "clientInfo": {"name": "acretia-harness", "version": "0.1.0"}})
            self._notify("notifications/initialized")

    @classmethod
    def inprocess(cls, server, timeout: float = 30) -> "MCPClient":
        c = cls(timeout)
        c._server = server
        return c

    @staticmethod
    def _pump(proc, q):
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                q.put(line)
        except (OSError, ValueError):
            pass
        finally:
            q.put(None)

    # ---------------------------------------------------------------------------------------------- rpc
    def _send(self, msg: dict):
        try:
            self._proc.stdin.write(P.encode(msg))
            self._proc.stdin.flush()
        except (OSError, ValueError):
            raise _ChildGone(f"MCP server exited (code {self._proc.poll()}) before the request was sent") from None

    def _request(self, method: str, params: dict | None = None):
        """One rpc; if the child died, respawn once (re-running initialize, with backoff) and retry the call."""
        if self._server is not None or self._spawn_args is None:
            return self._rpc(method, params)
        dead = self._proc is None or self._proc.poll() is not None
        try:
            if dead:
                raise _ChildGone("child not running")
            return self._rpc(method, params)
        except _ChildGone:
            self._respawn()  # at most one respawn per call; a second failure propagates
            return self._rpc(method, params)

    def _rpc(self, method: str, params: dict | None = None):
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
                raise _ChildGone(f"MCP server exited unexpectedly (code {self._proc.poll()})")
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
        self._initialized = True
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
