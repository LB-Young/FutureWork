"""Verify MCP stdio discovery and calls against a deterministic local server."""

import asyncio
import json
import sys

import pytest

from futurework.extension_system.mcp_client import MCPClient
from futurework.config import load_config
from futurework.home import ensure_home
from futurework.runtime.tool_dispatch import ToolRegistry


def test_mcp_stdio_tool_roundtrip(tmp_path):
    """The client initializes, lists, validates, and calls an advertised tool."""
    (tmp_path / "workspace").mkdir()
    root = tmp_path / "abilities" / "mcp" / "sample"
    root.mkdir(parents=True)
    script = root / "server.py"
    script.write_text('''import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "sample", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object"}}]}
    else:
        result = {"content": [{"type": "text", "text": request["params"]["arguments"]["message"]}]}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
''')
    (root / "manifest.toml").write_text(f'id="sample"\nenabled=true\ncommand="{sys.executable}"\nargs=["{script}"]\n', encoding="utf-8")
    client = MCPClient(tmp_path, {"timeout_seconds": 2, "max_output_chars": 12000, "shutdown_timeout_seconds": 1, "protocol_version": "2025-03-26"})
    tools = asyncio.run(client.list_tools("sample"))
    assert tools[0]["name"] == "echo"
    result = asyncio.run(client.call_tool("sample", "echo", {"message": "hello"}))
    assert json.loads(result)["content"][0]["text"] == "hello"
    with pytest.raises(PermissionError):
        asyncio.run(client.call_tool("sample", "unknown", {}))
    config = load_config(ensure_home(tmp_path))
    config["agent_extensions"]["research"] = {"mcp": ["sample"]}
    registry = ToolRegistry("research", ["mcp_list", "mcp_call"], config)
    listed = asyncio.run(registry.execute("mcp_list", {"server_id": "sample"}))
    assert listed.success and json.loads(listed.content)[0]["name"] == "echo"
    denied = asyncio.run(registry.execute("mcp_call", {"server_id": "other", "tool_name": "echo", "arguments": {}}))
    assert not denied.success
