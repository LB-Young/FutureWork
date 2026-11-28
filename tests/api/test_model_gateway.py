"""Verify DeepSeek requests use the configured alias and environment credential."""

import asyncio
import json

import httpx

from futurework.config import load_config
from futurework.home import ensure_home
from futurework.model import respond
from futurework.integrations.model_gateway.adapters import openai_chat
from futurework.integrations.model_gateway.gateway import ModelGateway
from futurework.integrations.model_gateway.types import ModelRequest, ModelResult


def test_deepseek_adapter_uses_environment_and_never_needs_a_file_key(tmp_path, monkeypatch):
    home = ensure_home(tmp_path / "home")
    config = load_config(home)
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "已完成"}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(openai_chat.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    agent = {"id": "research", "name": "知知", "role": "研究", "model": "default_fast"}
    answer = asyncio.run(respond(agent, [{"from": "me", "text": "你好"}], config))
    assert answer == "已完成"
    assert seen[0].url == "https://api.deepseek.com/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer test-only-key"
    assert json.loads(seen[0].content)["model"] == "deepseek-flash"


def test_gateway_retries_a_transient_deepseek_response(tmp_path, monkeypatch):
    config = load_config(ensure_home(tmp_path / "home"))
    config["model"]["retry_backoff_seconds"] = 0.001
    attempts = []

    def handle(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "已恢复"}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(openai_chat.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    agent = {"id": "research", "name": "知知", "role": "研究", "model": "default_fast"}
    assert asyncio.run(respond(agent, [{"from": "me", "text": "你好"}], config)) == "已恢复"
    assert len(attempts) == 2


def test_gateway_reuses_an_adapter_for_the_same_model_alias(tmp_path):
    config = load_config(ensure_home(tmp_path / "home"))
    instances = []

    class FakeAdapter:
        def __init__(self, provider, model, options):
            instances.append(self)

        async def generate(self, request):
            return ModelResult(text=request.alias)

    gateway = ModelGateway(config, adapters={"openai_chat": FakeAdapter})
    request = ModelRequest(alias="default_fast", messages=[{"role": "user", "content": "你好"}])
    assert asyncio.run(gateway.generate(request)).text == "default_fast"
    assert asyncio.run(gateway.generate(request)).text == "default_fast"
    assert len(instances) == 1
