"""Verify local model aliases and explicit friend/Team creation tools."""

import asyncio
import json
import tomllib

import httpx
from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.config_store.writer import ConfigStore
from futurework.contexts.types import ScopeKey
from futurework.home import ensure_home
from futurework.integrations.model_gateway.gateway import ModelGateway
from futurework.integrations.model_gateway.types import ModelRequest
from futurework.integrations.model_gateway.adapters import openai_chat
from futurework.runtime.tool_dispatch import ToolRegistry
from futurework.services.agent_service import AgentService
from futurework.services.group_service import GroupService
from futurework.services.message_service import MessageService


def test_friends_can_use_distinct_local_model_servers(tmp_path, monkeypatch):
    home = ensure_home(tmp_path / "home")
    with (home / "models.toml").open("a", encoding="utf-8") as output:
        output.write('''
[providers.ollama_second]
adapter = "openai_chat"
base_url = "http://127.0.0.1:11435/v1"
allow_no_key = true

[providers.vllm_second]
adapter = "openai_chat"
base_url = "http://127.0.0.1:8011/v1"
allow_no_key = true

[models.ollama_second]
provider = "ollama_second"
remote_id = "qwen3:8b"
supports_tools = true

[models.vllm_second]
provider = "vllm_second"
remote_id = "local-code"
supports_tools = true
''')
    app = create_app(home)
    client = TestClient(app)
    friend_a = client.post("/api/v1/agents", json={
        "name": "本地甲", "role": "总结", "model": "ollama_second",
        "tools": ["read"], "skills": ["skill-creator"],
        "capabilities": {"writing.summary": 0.9}})
    friend_b = client.post("/api/v1/agents", json={
        "name": "本地乙", "role": "编码", "model": "vllm_second",
        "tools": [], "skills": [], "capabilities": {"engineering.code": 0.95}})
    assert friend_a.status_code == friend_b.status_code == 201
    assert friend_a.json()["model"] == "ollama_second"
    assert friend_b.json()["model"] == "vllm_second"
    with (home / "agents" / f"{friend_a.json()['id']}.toml").open("rb") as source:
        assert tomllib.load(source)["extensions"]["skills"] == ["skill-creator"]
    gateway = ModelGateway(app.state.config)
    assert gateway.client_for("ollama_second").provider["base_url"].endswith(":11435/v1")
    assert gateway.client_for("vllm_second").provider["base_url"].endswith(":8011/v1")
    calls = []

    def respond(request):
        calls.append((str(request.url), json.loads(request.content)["model"]))
        return httpx.Response(200, json={"choices": [{"message": {"content": "收到"}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(openai_chat.httpx, "AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    for alias in (friend_a.json()["model"], friend_b.json()["model"]):
        assert asyncio.run(gateway.generate(ModelRequest(alias, [{"role": "user", "content": "你好"}], []))).text == "收到"
    assert calls == [("http://127.0.0.1:11435/v1/chat/completions", "qwen3:8b"),
                     ("http://127.0.0.1:8011/v1/chat/completions", "local-code")]
    assert {friend_a.json()["id"], friend_b.json()["id"]}.issubset({
        item["id"] for item in TestClient(create_app(home)).get("/api/v1/agents").json()})


def test_creation_tools_are_separate_from_delegation(tmp_path):
    home = ensure_home(tmp_path / "home")
    app = create_app(home)
    config = app.state.config
    database = app.state.database
    messages = MessageService(database)
    writer = ConfigStore(home)
    agent_service = AgentService(database, config, writer, messages, app.state.memory_store)
    group_service = GroupService(database, config, writer, app.state.memory_store)
    registry = ToolRegistry("assistant", ["friend_create", "team_create"], config,
                            scope=ScopeKey("assistant", "assistant"),
                            agent_service=agent_service, group_service=group_service)
    created = asyncio.run(registry.execute("friend_create", {
        "name": "新研究员", "role": "竞品分析", "model": "default_fast", "tools": ["read"],
        "skills": [], "capabilities": {"analysis.competitor": 0.95}}))
    assert created.success
    friend_id = json.loads(created.content)["id"]
    team = asyncio.run(registry.execute("team_create", {
        "name": "研究群", "member_ids": [friend_id], "mode": "swarm"}))
    assert team.success
    team_id = json.loads(team.content)["id"]
    assert database.group(team_id)["members"] == [friend_id]
    with (home / "teams" / f"{team_id}.toml").open("rb") as source:
        assert tomllib.load(source)["mode"] == "swarm"
    other = ToolRegistry("image", ["friend_create"], config,
                         scope=ScopeKey("agent", "image"), agent_service=agent_service)
    assert not asyncio.run(other.execute("friend_create", {
        "name": "禁止", "role": "禁止", "model": "default_fast", "tools": [], "skills": []})).success
