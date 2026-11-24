"""Run a complete assistant task through the DeepSeek adapter with fake HTTP responses."""

import json
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.home import ensure_home
from futurework.integrations.model_gateway.adapters import openai_chat


def test_assistant_task_calls_deepseek_and_persists_result(tmp_path, monkeypatch):
    calls = []

    def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        is_classifier = any("只输出 CHAT 或 TASK" in item["content"] for item in payload["messages"])
        answer = "TASK" if is_classifier else "竞品分析初稿已完成"
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(openai_chat.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    client = TestClient(create_app(ensure_home(tmp_path / "home")))
    response = client.post("/api/v1/conversations/assistant/messages", json={
        "client_message_id": str(uuid4()), "body": "请做竞品分析",
    })
    assert response.status_code == 202
    task = client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "completed"
    assert len(calls) >= 2
    assert all(call["model"] == "deepseek-chat" for call in calls)
    messages = client.get("/api/v1/conversations/assistant/messages").json()
    assert "竞品分析初稿已完成" in messages[-1]["text"]
