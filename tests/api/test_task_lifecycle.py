"""Verify normalized RunParams become one typed Task before execution."""

from uuid import uuid4

from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.home import ensure_home
from futurework.runtime.run_params import RunParams
from futurework.runtime.task_factory import TaskFactory, TaskKind


def test_factory_routes_every_conversation_execution_type():
    factory = TaskFactory()
    cases = [
        ({"id": "assistant", "kind": "assistant", "name": "小未"}, "chat", TaskKind.ASSISTANT_CHAT),
        ({"id": "assistant", "kind": "assistant", "name": "小未"}, "task", TaskKind.ASSISTANT_DELEGATION),
        ({"id": "research", "kind": "agent", "name": "知知"}, None, TaskKind.AGENT_CHAT),
        ({"id": "ideas", "kind": "group", "name": "灵感", "mode": "swarm"}, None, TaskKind.GROUP_SWARM),
        ({"id": "launch", "kind": "group", "name": "发布", "mode": "controlled"}, None, TaskKind.GROUP_CONTROLLED),
    ]
    for target, intent, expected in cases:
        params = RunParams.from_http(target, "  开始处理  ", str(uuid4()))
        task = factory.create(params, assistant_intent=intent)
        assert params.message == "开始处理"
        assert task.params is params
        assert task.kind is expected
        assert task.id


def test_duplicate_assistant_request_does_not_reclassify_or_reexecute(tmp_path, monkeypatch):
    calls = {"classify": 0, "respond": 0}

    async def classify(self, text, history):
        calls["classify"] += 1
        return "chat"

    async def respond(self, agent, history):
        calls["respond"] += 1
        return "你好"

    monkeypatch.setattr("futurework.runtime.assistant_runtime.AssistantRuntime.classify", classify)
    monkeypatch.setattr("futurework.model.AgentRuntime.respond", respond)
    client = TestClient(create_app(ensure_home(tmp_path / "home")))
    payload = {"client_message_id": str(uuid4()), "body": "你好"}
    first = client.post("/api/v1/conversations/assistant/messages", json=payload)
    second = client.post("/api/v1/conversations/assistant/messages", json=payload)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert calls == {"classify": 1, "respond": 1}
    assert len(client.get("/api/v1/conversations/assistant/messages").json()) == 2
    assert client.post("/api/v1/conversations/research/messages", json=payload).status_code == 409


def test_duplicate_delegation_reuses_persisted_task(tmp_path, monkeypatch):
    calls = {"classify": 0}

    async def classify(self, text, history):
        calls["classify"] += 1
        return "task"

    async def respond(self, agent, history):
        return "初稿已完成"

    monkeypatch.setattr("futurework.runtime.assistant_runtime.AssistantRuntime.classify", classify)
    monkeypatch.setattr("futurework.model.AgentRuntime.respond", respond)
    client = TestClient(create_app(ensure_home(tmp_path / "home")))
    payload = {"client_message_id": str(uuid4()), "body": "请做竞品分析"}
    first = client.post("/api/v1/conversations/assistant/messages", json=payload)
    second = client.post("/api/v1/conversations/assistant/messages", json=payload)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert first.json()["task_id"]
    assert calls["classify"] == 1
    assert len(client.get("/api/v1/conversations/assistant/messages").json()) == 3
