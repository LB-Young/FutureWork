"""Verify provider tool round trips and the built-in permission boundary."""

import asyncio
import json

import httpx

from futurework.config import load_config
from futurework.home import ensure_home
from futurework.integrations.model_gateway.adapters import anthropic, openai_chat
from futurework.model import respond
from futurework.runtime.tool_dispatch import ToolRegistry, ToolRequest, execute


def test_openai_compatible_tool_round_trip(tmp_path, monkeypatch):
    config = load_config(ensure_home(tmp_path / "home"))
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": '{"expression":"2+3"}'}}
            ]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "结果是 5"}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(openai_chat.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    agent = {"id": "research", "name": "知知", "role": "研究", "model": "default_fast", "tools": ["calculator"]}
    answer = asyncio.run(respond(agent, [{"from": "me", "text": "2+3?"}], config))
    assert answer == "结果是 5"
    assert requests[0]["tools"][0]["function"]["name"] == "calculator"
    assert requests[1]["messages"][-1] == {"role": "tool", "tool_call_id": "call_1", "content": "5"}


def test_model_requested_write_changes_workspace_file(tmp_path, monkeypatch):
    config = load_config(ensure_home(tmp_path / "home"))
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
                {"id": "call_write", "type": "function", "function": {"name": "write",
                 "arguments": '{"file_path":"report.txt","content":"done"}'}}
            ]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "已写入报告"}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(openai_chat.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    agent = {"id": "code", "name": "阿码", "role": "开发", "model": "default_fast", "tools": ["write"]}
    assert asyncio.run(respond(agent, [{"from": "me", "text": "写一份报告"}], config)) == "已写入报告"
    assert (config["home"] / "workspace" / "report.txt").read_text() == "done"
    assert requests[0]["tools"][0]["function"]["name"] == "write"


def test_tool_grants_and_workspace_boundary(tmp_path):
    config = load_config(ensure_home(tmp_path / "home"))
    workspace = config["home"] / "workspace"
    (workspace / "note.txt").write_text("safe text", encoding="utf-8")
    (workspace / "outside.txt").symlink_to(config["home"] / "app.toml")
    denied = execute(ToolRequest("research", "read_file", {"path": "note.txt"}), ["calculator"], config)
    assert not denied.success
    assert execute(ToolRequest("research", "read_file", {"path": "note.txt"}), ["read_file"], config).content == "safe text"
    assert not execute(ToolRequest("research", "read_file", {"path": "../app.toml"}), ["read_file"], config).success
    assert not execute(ToolRequest("research", "read_file", {"path": "outside.txt"}), ["read_file"], config).success


def test_tool_registry_rejects_another_agents_request(tmp_path):
    config = load_config(ensure_home(tmp_path / "home"))
    registry = ToolRegistry("research", ("calculator",), config)
    assert [item["function"]["name"] for item in registry.schemas()] == ["calculator"]
    result = registry.execute_sync(ToolRequest("code", "calculator", {"expression": "2+3"}))
    assert not result.success


def test_local_model_catalog_and_no_key(tmp_path, monkeypatch):
    config = load_config(ensure_home(tmp_path / "home"))
    assert {"mimo_default", "zhipu_glm", "ollama_local", "vllm_local", "claude_default"}.issubset(config["models"]["models"])
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "本地回复"}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(openai_chat.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    agent = {"id": "research", "name": "知知", "role": "研究", "model": "ollama_local"}
    assert asyncio.run(respond(agent, [{"from": "me", "text": "你好"}], config)) == "本地回复"
    assert seen[0].url == "http://127.0.0.1:11434/v1/chat/completions"
    assert "authorization" not in seen[0].headers


def test_vllm_local_uses_its_configured_port_without_cloud_key(tmp_path, monkeypatch):
    config = load_config(ensure_home(tmp_path / "home"))
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "vLLM 回复"}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(openai_chat.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    agent = {"id": "assistant", "name": "小未", "role": "助理", "model": "vllm_local"}
    assert asyncio.run(respond(agent, [{"from": "me", "text": "你好"}], config)) == "vLLM 回复"
    assert seen[0].url == "http://127.0.0.1:8001/v1/chat/completions"
    assert json.loads(seen[0].content)["model"] == "Qwen/Qwen2.5-7B-Instruct"
    assert "authorization" not in seen[0].headers


def test_anthropic_tool_result_is_translated(tmp_path, monkeypatch):
    config = load_config(ensure_home(tmp_path / "home"))
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "tool_1", "name": "calculator",
                                                        "input": {"expression": "4*7"}}]})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "28"}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(anthropic.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-key")
    agent = {"id": "research", "name": "知知", "role": "研究", "model": "claude_default", "tools": ["calculator"]}
    assert asyncio.run(respond(agent, [{"from": "me", "text": "4*7?"}], config)) == "28"
    assert seen[0]["tools"][0]["name"] == "calculator"
    assert seen[1]["messages"][-1]["content"][0]["content"] == "28"
