"""Verify transient failures retry at the right layer and terminal failures stop."""

from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.integrations.model_gateway.gateway import ModelGateway
from futurework.integrations.model_gateway.types import ModelResult
from futurework.runtime.agent_executor import AgentResponse, AgentRuntime


def _send(client, target, text):
    return client.post(f"/api/v1/conversations/{target}/messages",
                       json={"client_message_id": str(uuid4()), "body": text})


def test_task_retries_transient_agent_failure(tmp_path, monkeypatch):
    attempts = []

    async def respond(self, agent, history, scope=None):
        attempts.append(agent["id"])
        if len(attempts) == 1:
            raise httpx.ConnectError("temporary")
        return AgentResponse("恢复成功")

    monkeypatch.setattr(AgentRuntime, "respond_with_result", respond)
    client = TestClient(create_app(tmp_path))
    assert _send(client, "assistant", "你好").status_code == 202
    assert attempts == ["assistant", "assistant"]
    assert client.get("/api/v1/conversations/assistant/messages").json()[-1]["text"] == "恢复成功"


def test_task_does_not_retry_terminal_error(tmp_path, monkeypatch):
    attempts = []

    async def respond(self, agent, history, scope=None):
        attempts.append(agent["id"])
        raise ValueError("bad configuration")

    monkeypatch.setattr(AgentRuntime, "respond_with_result", respond)
    client = TestClient(create_app(tmp_path))
    result = _send(client, "assistant", "你好")
    assert result.json()["status"] == "failed"
    assert attempts == ["assistant"]


def test_agent_model_retries_transient_before_tools(tmp_path, monkeypatch):
    attempts = []

    async def generate(self, request):
        attempts.append(request.alias)
        if len(attempts) == 1:
            raise httpx.ConnectError("temporary")
        return ModelResult("模型恢复")

    monkeypatch.setattr(ModelGateway, "generate", generate)
    client = TestClient(create_app(tmp_path))
    assert _send(client, "assistant", "你好").status_code == 202
    assert len(attempts) == 2
    assert client.get("/api/v1/conversations/assistant/messages").json()[-1]["text"] == "模型恢复"
