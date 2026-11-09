"""
Core · MCP client
=================
Connects VDX to Model Context Protocol servers over stdio, so any MCP server
(filesystem, Notion, Slack, databases…) adds tools without writing a connector.

Servers are configured in ``data/mcp.json``, in the same format as Claude
Desktop::

    {"mcpServers": {"fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/Documents"]}}}

Each server's tools are exposed as ``<server>__<tool>``. Tools that don't declare
themselves read-only ask the user for approval before running.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from config.settings import project_root
from core import approvals

logger = logging.getLogger(__name__)

CONFIG = project_root() / "data" / "mcp.json"
PROTOCOL = "2025-06-18"
_EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin"), str(Path.home() / ".cargo/bin")]


class MCPServer:
    """One stdio MCP server process."""

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        self.name, self.cfg = name, cfg
        self.proc: subprocess.Popen[str] | None = None
        self.tools: list[dict[str, Any]] = []
        self.error = ""
        self._id = 0
        self._waiting: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ── JSON-RPC ─────────────────────────────────────────────────────

    def start(self) -> None:
        env = {**os.environ, **{k: str(v) for k, v in (self.cfg.get("env") or {}).items()}}
        parts = env.get("PATH", "").split(os.pathsep)
        env["PATH"] = os.pathsep.join(parts + [p for p in _EXTRA_PATH if p not in parts])
        cmd = [self.cfg["command"], *[os.path.expanduser(str(a)) for a in self.cfg.get("args") or []]]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1, env=env, cwd=self.cfg.get("cwd") or None)
        threading.Thread(target=self._read, name=f"mcp-{self.name}", daemon=True).start()
        threading.Thread(target=self._drain_stderr, name=f"mcp-{self.name}-err", daemon=True).start()
        self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                    "clientInfo": {"name": "vdx-openagent", "version": "1"}}, timeout=60)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools: list[dict[str, Any]] = []
        cursor = None
        while True:
            res = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=30)
            tools += res.get("tools") or []
            cursor = res.get("nextCursor")
            if not cursor:
                break
        self.tools = tools

    def _send(self, msg: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin or self.proc.poll() is not None:
            raise RuntimeError(f"MCP server '{self.name}' is not running")
        with self._lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def _read(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                slot = self._waiting.get(msg["id"])
                if slot:
                    slot["msg"] = msg
                    slot["event"].set()
            elif "id" in msg and "method" in msg:  # server → client request we don't support (sampling, roots…)
                try:
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported"}})
                except Exception:
                    pass
        for slot in list(self._waiting.values()):  # process ended: wake every waiter
            slot["event"].set()

    def _drain_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            logger.debug("[mcp %s] %s", self.name, line.rstrip())

    def request(self, method: str, params: dict[str, Any], timeout: float = 120) -> dict[str, Any]:
        with self._lock:
            self._id += 1
            rid = self._id
        slot: dict[str, Any] = {"event": threading.Event(), "msg": None}
        self._waiting[rid] = slot
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            if not slot["event"].wait(timeout):
                raise RuntimeError(f"MCP server '{self.name}' did not answer {method} in {timeout:.0f}s")
            msg = slot["msg"]
            if msg is None:
                raise RuntimeError(f"MCP server '{self.name}' stopped")
            if "error" in msg:
                raise RuntimeError(msg["error"].get("message") or str(msg["error"]))
            return msg.get("result") or {}
        finally:
            self._waiting.pop(rid, None)

    def call(self, tool: str, args: dict[str, Any]) -> str:
        try:
            res = self.request("tools/call", {"name": tool, "arguments": args})
        except Exception as exc:
            return f"Error: {exc}"
        parts = []
        for item in res.get("content") or []:
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif item.get("type") == "resource":
                parts.append(str((item.get("resource") or {}).get("text", "")))
            else:
                parts.append(f"[{item.get('type')} content]")
        if not parts and res.get("structuredContent") is not None:
            parts.append(json.dumps(res["structuredContent"], ensure_ascii=False))
        text = "\n".join(parts).strip() or "(no output)"
        return f"Error: {text}" if res.get("isError") else text

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


_servers: dict[str, MCPServer] = {}


def tool_name(server: str, tool: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"{server}__{tool}")[:64]


def read_config() -> str:
    return CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else '{\n  "mcpServers": {}\n}\n'


def write_config(text: str) -> None:
    data = json.loads(text)  # raises ValueError on bad JSON
    if not isinstance(data.get("mcpServers", {}), dict):
        raise ValueError('"mcpServers" must be an object')
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def start_all() -> None:
    """(Re)start every configured server in the background."""
    stop_all()
    try:
        cfg = json.loads(read_config()).get("mcpServers") or {}
    except ValueError as exc:
        logger.error("data/mcp.json is not valid JSON: %s", exc)
        return
    for name, sc in cfg.items():
        if sc.get("disabled") or not sc.get("command"):
            continue
        srv = _servers[name] = MCPServer(name, sc)

        def boot(s: MCPServer = srv) -> None:
            try:
                s.start()
                for t in s.tools:
                    if not (t.get("annotations") or {}).get("readOnlyHint"):
                        approvals.register(tool_name(s.name, t["name"]), f"{s.name}: {t.get('title') or t['name']}")
                logger.info("MCP server %s ready with %d tools", s.name, len(s.tools))
            except Exception as exc:
                s.error = str(exc)
                logger.warning("MCP server %s failed: %s", s.name, exc)

        threading.Thread(target=boot, name=f"mcp-boot-{name}", daemon=True).start()


def stop_all() -> None:
    for s in _servers.values():
        s.stop()
    _servers.clear()


def servers() -> list[MCPServer]:
    return list(_servers.values())


def status() -> list[dict[str, Any]]:
    return [{"name": s.name, "running": bool(s.proc and s.proc.poll() is None and s.tools),
             "tools": [t["name"] for t in s.tools], "error": s.error} for s in _servers.values()]
