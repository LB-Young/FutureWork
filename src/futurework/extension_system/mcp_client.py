"""Run user-enabled MCP stdio servers and call only their advertised tools."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tomllib
from pathlib import Path

from futurework.integrations.model_gateway.credentials import _local_env


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class MCPClient:
    """Own one MCP server connection per list or tool call."""

    def __init__(self, home: Path, settings: dict) -> None:
        self.home = home
        self.settings = settings

    def _manifest(self, server_id: str) -> dict:
        if not SAFE_ID.fullmatch(server_id):
            raise ValueError("invalid MCP server ID")
        candidates = [self.home / "abilities" / "mcp" / server_id / "manifest.toml",
                      self.home / "mcp" / f"{server_id}.toml"]
        for path in candidates:
            if path.is_file():
                if not path.resolve().is_relative_to(self.home.resolve()):
                    raise ValueError("MCP manifest path escapes user home")
                with path.open("rb") as source:
                    manifest = tomllib.load(source)
                if manifest.get("id") != server_id or manifest.get("enabled") is not True:
                    raise ValueError("MCP server is disabled or has an invalid ID")
                if not isinstance(manifest.get("command"), str) or not manifest["command"]:
                    raise ValueError("MCP server command is required")
                if not isinstance(manifest.get("args", []), list) or any(not isinstance(arg, str) for arg in manifest.get("args", [])):
                    raise ValueError("invalid MCP server arguments")
                return manifest
        raise ValueError("MCP server not found")

    async def _session(self, server_id: str, tool_name: str = "", arguments: dict | None = None) -> object:
        manifest = self._manifest(server_id)
        env = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}}
        for name in manifest.get("env", []):
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError("invalid MCP environment reference")
            value = os.environ.get(name) or _local_env(name)
            if value:
                env[name] = value
        process = await asyncio.create_subprocess_exec(manifest["command"], *manifest.get("args", []),
                                                       cwd=self.home / "workspace", env=env,
                                                       stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.DEVNULL)
        async def request(identifier: int, method: str, params: dict) -> dict:
            encoded = json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}).encode() + b"\n"
            process.stdin.write(encoded)
            await process.stdin.drain()
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), self.settings["timeout_seconds"])
                if not line or len(line) > self.settings["max_output_chars"]:
                    raise RuntimeError("MCP server closed or returned excessive output")
                data = json.loads(line)
                if data.get("id") != identifier:
                    continue
                if "error" in data:
                    raise RuntimeError("MCP server returned a JSON-RPC error")
                return data.get("result", {})
        try:
            await request(1, "initialize", {"protocolVersion": self.settings["protocol_version"],
                                            "capabilities": {}, "clientInfo": {"name": "FutureWork", "version": "0.1.0"}})
            process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            await process.stdin.drain()
            listing = await request(2, "tools/list", {})
            tools = listing.get("tools", [])
            if not isinstance(tools, list):
                raise RuntimeError("MCP server returned invalid tool list")
            if not tool_name:
                return tools
            if tool_name not in {item.get("name") for item in tools if isinstance(item, dict)}:
                raise PermissionError("MCP tool is not advertised by server")
            result = await request(3, "tools/call", {"name": tool_name, "arguments": arguments or {}})
            return result
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), self.settings["shutdown_timeout_seconds"])
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

    async def list_tools(self, server_id: str) -> list[dict]:
        """Discover tool descriptions from one enabled server."""
        return await self._session(server_id)

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict) -> str:
        """Validate the advertised tool name, execute it, and return bounded text."""
        if not isinstance(arguments, dict):
            raise ValueError("MCP arguments must be an object")
        result = await self._session(server_id, tool_name, arguments)
        return json.dumps(result, ensure_ascii=False)[:self.settings["max_output_chars"]]
