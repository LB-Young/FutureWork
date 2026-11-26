"""Verify entry adapters and a configured process friend run through real tasks."""

import sys
import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from futurework.adapters.api.app import create_app as create_api_app
from futurework.adapters.cli.chat import run as cli_chat
from futurework.adapters.web.app import create_app as create_web_app
from futurework.home import ensure_home
from futurework.integrations.agent_backends.base import AgentRequest
from futurework.integrations.agent_backends.subprocess_backend import SubprocessBackend


def configured_home(tmp_path):
    """Create one executable protocol-v1 Agent and its user-owned profile."""
    home = ensure_home(tmp_path / "home")
    script = home / "workspace" / "agent.py"
    script.write_text(
        '"""Return a scoped reply to a FutureWork process request."""\n'
        'import json, sys\n'
        'request = json.loads(sys.stdin.readline())\n'
        'print(json.dumps({"text": request["scope"]["type"] + ":" + request["message"]}))\n',
        encoding="utf-8",
    )
    (home / "agent_backends.toml").write_text(
        '[profiles.local]\nexecutable = "' + sys.executable + '"\n'
        'arguments = ["' + str(script) + '"]\n'
        'timeout_seconds = 10\n',
        encoding="utf-8",
    )
    (home / "agents" / "external.toml").write_text(
        'schema_version = 1\nid = "external"\nname = "外部伙伴"\n'
        'role = "完成指定请求"\nkind = "friend"\nstatus = "active"\n'
        '[capabilities]\n"coding.review" = 0.9\n'
        '[execution]\nkind = "process"\nprofile = "local"\n',
        encoding="utf-8",
    )
    return home


def test_external_friend_in_web_and_cli(tmp_path):
    home = configured_home(tmp_path)
    client = TestClient(create_web_app(home))
    assert client.get("/api/v1/agents/external/health").json()["ok"]
    response = client.post("/api/v1/conversations/external/messages",
                           json={"client_message_id": str(uuid4()), "body": "你好"})
    assert response.status_code == 202
    messages = client.get("/api/v1/conversations/external/messages").json()
    assert messages[-1]["text"] == "agent:你好"
    assert cli_chat(home, "external", "再见") == "agent:再见"


def test_headless_api_requires_key_and_uses_same_runtime(tmp_path, monkeypatch):
    home = configured_home(tmp_path)
    monkeypatch.setenv("FUTUREWORK_API_KEY", "local-test-token")
    client = TestClient(create_api_app(home))
    assert client.get("/").status_code == 401
    assert client.get("/api/v1/agents").status_code == 401
    headers = {"Authorization": "Bearer local-test-token"}
    assert client.get("/api/v1/agents", headers=headers).status_code == 200
    result = client.post("/api/v1/conversations/external/messages", headers=headers,
                         json={"client_message_id": str(uuid4()), "body": "API 请求"})
    assert result.status_code == 202
    assert client.get("/api/v1/conversations/external/messages", headers=headers).json()[-1]["text"] == "agent:API 请求"


def test_process_friend_uses_group_scope(tmp_path):
    home = configured_home(tmp_path)
    group = home / "teams" / "external_team.toml"
    group.write_text('schema_version = 1\nid = "external_team"\nname = "外部群"\n'
                     'mode = "swarm"\nmembers = ["external"]\n', encoding="utf-8")
    client = TestClient(create_web_app(home))
    response = client.post("/api/v1/conversations/external_team/messages",
                           json={"client_message_id": str(uuid4()), "body": "群里你好"})
    assert response.status_code == 202
    assert client.get("/api/v1/conversations/external_team/messages").json()[-1]["text"] == "group:群里你好"


def test_codex_and_openclaw_command_contracts(tmp_path):
    """Use executable fakes to verify the actual CLI arguments and response parsing."""
    cli = tmp_path / "fake-agent"
    cli.write_text(
        '#!' + sys.executable + '\n'
        '"""Emulate the Codex and OpenClaw command boundaries."""\n'
        'import json, pathlib, sys\n'
        'args = sys.argv[1:]\n'
        'if "--version" in args or args[:2] == ["config", "validate"]:\n    print("fake-1.0")\n'
        'elif args[0] == "exec":\n'
        '    pathlib.Path(args[args.index("-o") + 1]).write_text("Codex 完成")\n'
        'elif args[0] == "agent":\n'
        '    print(json.dumps({"result": {"payloads": [{"text": "OpenClaw 完成"}]}}))\n'
        'elif args[0] == "-p":\n'
        '    print(json.dumps({"result": "Claude Code 完成"}))\n',
        encoding="utf-8",
    )
    cli.chmod(0o700)
    request = AgentRequest("external", "伙伴", "回答问题", "agent", "external", "你好", ())
    profile = {"executable": str(cli), "workdir": str(tmp_path), "timeout_seconds": 5}
    codex = SubprocessBackend("codex_cli", profile)
    claw = SubprocessBackend("openclaw", profile)
    claude = SubprocessBackend("claude_code", profile)
    assert asyncio.run(codex.health())["ok"]
    assert asyncio.run(claw.health())["ok"]
    assert asyncio.run(claude.health())["ok"]
    assert asyncio.run(codex.run(request)) == "Codex 完成"
    assert asyncio.run(claw.run(request)) == "OpenClaw 完成"
    assert asyncio.run(claude.run(request)) == "Claude Code 完成"
