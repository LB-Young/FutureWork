"""Verify the installed app can complete an assistant chat using only Ollama."""

from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.home import ensure_home
from futurework.integrations.model_gateway.adapters import openai_chat


def test_assistant_chat_uses_local_ollama_without_cloud_key(tmp_path, monkeypatch):
    home = ensure_home(tmp_path / "home")
    assistant = home / "agents" / "assistant.toml"
    assistant.write_text(assistant.read_text().replace('id = "default_fast"', 'id = "ollama_local"'))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    requests = []

    def handle(request):
        requests.append(request)
        answer = "你好，我是小未。"
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(openai_chat.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    client = TestClient(create_app(home))
    response = client.post("/api/v1/conversations/assistant/messages", json={
        "client_message_id": str(uuid4()), "body": "你好",
    })
    assert response.status_code == 202
    assert client.get("/api/v1/conversations/assistant/messages").json()[-1]["text"] == "你好，我是小未。"
    assert len(requests) == 1
    assert all(str(request.url) == "http://127.0.0.1:11434/v1/chat/completions" for request in requests)
    assert all("authorization" not in request.headers for request in requests)
