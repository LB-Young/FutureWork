"""Verify a task routes by conversation and repeats cannot rerun an Agent."""

from uuid import uuid4

from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.runtime.agent_executor import AgentResponse
from futurework.runtime.run_params import RunParams
from futurework.runtime.task_factory import TaskFactory, TaskKind
from tests.support import sample_home


def test_factory_routes_assistant_and_friend_through_one_agent_kind():
    factory = TaskFactory()
    cases = [
        ({"id": "assistant", "kind": "assistant", "name": "小未"}, TaskKind.AGENT_CHAT),
        ({"id": "research", "kind": "agent", "name": "知知"}, TaskKind.AGENT_CHAT),
        ({"id": "ideas", "kind": "group", "name": "灵感", "mode": "swarm"}, TaskKind.GROUP_SWARM),
        ({"id": "launch", "kind": "group", "name": "发布", "mode": "controlled"}, TaskKind.GROUP_CONTROLLED),
    ]
    for target, expected in cases:
        params = RunParams.from_http(target, "  开始处理  ", str(uuid4()))
        task = factory.create(params)
        assert params.message == "开始处理"
        assert task.params is params
        assert task.kind is expected
        assert task.id


def test_duplicate_assistant_request_runs_agent_once(tmp_path, monkeypatch):
    calls = []

    async def respond(self, agent, history, scope=None):
        calls.append(agent["id"])
        return AgentResponse("你好")

    monkeypatch.setattr("futurework.model.AgentRuntime.respond_with_result", respond)
    client = TestClient(create_app(sample_home(tmp_path / "home")))
    payload = {"client_message_id": str(uuid4()), "body": "你好"}
    first = client.post("/api/v1/conversations/assistant/messages", json=payload)
    second = client.post("/api/v1/conversations/assistant/messages", json=payload)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert calls == ["assistant"]
    assert len(client.get("/api/v1/conversations/assistant/messages").json()) == 2
    assert client.post("/api/v1/conversations/research/messages", json=payload).status_code == 409
    assert client.post("/api/v1/conversations/assistant/messages", json={**payload, "body": "不同内容"}).status_code == 409
