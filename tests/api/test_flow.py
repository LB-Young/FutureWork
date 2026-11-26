"""Exercise assistant dispatch, config writes, approvals, and both Team modes."""

import tomllib
from uuid import uuid4

from fastapi.testclient import TestClient

from futurework.api.app import create_app
from tests.support import sample_home


def send(client, conversation_id, body):
    """Submit one idempotent user message to a conversation."""
    return client.post(f"/api/v1/conversations/{conversation_id}/messages",
                       json={"client_message_id": str(uuid4()), "body": body})


def test_assistant_dispatch_and_agent_file_survive_restart(tmp_path, monkeypatch):
    async def fake_respond(self, agent, history, scope=None):
        return f"{agent['name']} 已处理"

    monkeypatch.setattr("futurework.model.AgentRuntime.respond", fake_respond)
    home = sample_home(tmp_path / "home")
    client = TestClient(create_app(home))
    response = send(client, "assistant", "请做竞品分析")
    assert response.status_code == 202
    task = client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "completed"
    created = next(item for item in client.get("/api/v1/agents").json() if "analysis.competitor" in item["capabilities"])
    with (home / "agents" / f"{created['id']}.toml").open("rb") as source:
        assert tomllib.load(source)["model"]["id"] == "default_fast"
    assert any(item["id"] == created["id"] for item in TestClient(create_app(home)).get("/api/v1/agents").json())


def test_assistant_chat_stays_in_its_own_conversation(tmp_path, monkeypatch):
    async def chat_mode(self, text, history):
        return "chat"

    async def fake_respond(self, agent, history, scope=None):
        return "你好，我是小未。"

    monkeypatch.setattr("futurework.runtime.assistant_runtime.AssistantRuntime.classify", chat_mode)
    monkeypatch.setattr("futurework.model.AgentRuntime.respond", fake_respond)
    client = TestClient(create_app(sample_home(tmp_path / "home")))
    response = send(client, "assistant", "你好")
    assert response.status_code == 202
    assert response.json()["task_id"] is None
    messages = client.get("/api/v1/conversations/assistant/messages").json()
    assert [item["speaker"] for item in messages] == ["你", "小未"]


def test_approval_updates_agent_toml(tmp_path):
    home = sample_home(tmp_path / "home")
    client = TestClient(create_app(home))
    original = client.get("/api/v1/agents/code").json()
    proposal = {"expected_version": original["version"], "model": "default_fast",
                "tools": ["write"], "approval": True}
    pending = client.patch("/api/v1/agents/code", json=proposal)
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending_approval"
    decision = client.post(f"/api/v1/approvals/{pending.json()['approval_id']}/decision", json={"decision": "approve"})
    assert decision.status_code == 200
    with (home / "agents" / "code.toml").open("rb") as source:
        assert tomllib.load(source)["tools"] == ["write"]


def test_swarm_and_controlled_group_replies(tmp_path, monkeypatch):
    async def fake_respond(self, agent, history, scope=None):
        return "design" if agent["id"] == "assistant" else f"{agent['name']} 的回复"

    monkeypatch.setattr("futurework.model.AgentRuntime.respond", fake_respond)
    home = sample_home(tmp_path / "home")
    client = TestClient(create_app(home))
    swarm = client.post("/api/v1/groups", json={"name": "自由讨论", "member_ids": ["design", "write"], "mode": "swarm"})
    assert swarm.status_code == 201
    swarm_id = swarm.json()["id"]
    assert send(client, swarm_id, "一起想想").status_code == 202
    speakers = [item["speaker"] for item in client.get(f"/api/v1/conversations/{swarm_id}/messages").json()]
    assert speakers == ["你", "小绘", "言言"]
    controlled = client.post("/api/v1/groups", json={"name": "中控讨论", "member_ids": ["design", "write"], "mode": "controlled"})
    assert controlled.status_code == 201
    controlled_id = controlled.json()["id"]
    assert send(client, controlled_id, "请安排设计").status_code == 202
    speakers = [item["speaker"] for item in client.get(f"/api/v1/conversations/{controlled_id}/messages").json()]
    assert speakers == ["你", "小未", "小绘"]


def test_installed_web_page_and_bootstrap_are_served(tmp_path):
    client = TestClient(create_app(sample_home(tmp_path / "home")))
    assert "FutureWork" in client.get("/").text
    assert "Live Agent Team client" in client.get("/app.js").text
    bootstrap = client.get("/api/v1/bootstrap").json()
    assert bootstrap["model_provider"] == "registry"
    assert "default_fast" in bootstrap["models"]


def test_manual_agent_edit_reloads_without_mixing_private_chats(tmp_path, monkeypatch):
    async def fake_respond(self, agent, history, scope=None):
        assert all(item["conversation_id"] == agent["id"] for item in history)
        return f"{agent['name']} 知道这条私聊"

    monkeypatch.setattr("futurework.model.AgentRuntime.respond", fake_respond)
    home = sample_home(tmp_path / "home")
    first = TestClient(create_app(home))
    assert send(first, "research", "只告诉知知的秘密").status_code == 202
    assert first.get("/api/v1/conversations/code/messages").json() == []
    path = home / "agents" / "research.toml"
    path.write_text(path.read_text().replace('role = "研究与洞察"', 'role = "专项研究"'))
    restarted = TestClient(create_app(home))
    assert restarted.get("/api/v1/agents/research").json()["role"] == "专项研究"
    assert len(restarted.get("/api/v1/conversations/research/messages").json()) == 2


def test_controlled_group_can_assign_two_members_and_summarize(tmp_path, monkeypatch):
    async def fake_respond(self, agent, history, scope=None):
        if agent["id"] == "assistant":
            return "任务已汇总" if "简要汇总" in history[-1]["text"] else '{"agent_ids":["design","write"]}'
        return f"{agent['name']} 已完成"

    monkeypatch.setattr("futurework.model.AgentRuntime.respond", fake_respond)
    client = TestClient(create_app(sample_home(tmp_path / "home")))
    response = client.post("/api/v1/groups", json={"name": "联合发布", "member_ids": ["design", "write"], "mode": "controlled"})
    group_id = response.json()["id"]
    assert send(client, group_id, "请设计并写发布文案").status_code == 202
    speakers = [item["speaker"] for item in client.get(f"/api/v1/conversations/{group_id}/messages").json()]
    assert speakers == ["你", "小未", "小绘", "言言", "小未"]
