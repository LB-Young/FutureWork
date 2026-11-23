from uuid import uuid4
import tomllib

from fastapi.testclient import TestClient

from futurework.app import create_app
from futurework.config import DEFAULT_CONFIG


def client(tmp_path):
    return TestClient(create_app(home=tmp_path / "home"))


def send(test_client, conversation_id, text, message_id=None):
    return test_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_message_id": message_id or str(uuid4()), "body": text},
    )


def test_assistant_dispatch_persists_and_deduplicates(tmp_path):
    test_client = client(tmp_path)
    message_id = str(uuid4())
    first = send(test_client, "assistant", "请设计界面并写发布文案", message_id)
    assert first.status_code == 202
    task_id = first.json()["task_id"]
    task = test_client.get(f"/api/v1/tasks/{task_id}").json()
    assert len(task["steps"]) == 2
    assert {step["agent_id"] for step in task["steps"]} == {"design", "write"}
    repeated = send(test_client, "assistant", "请设计界面并写发布文案", message_id)
    assert repeated.json() == first.json()
    assert len(test_client.get("/api/v1/conversations/assistant/messages").json()) == 2
    assert test_client.get("/api/v1/inbox?view=all").json()[0]["id"] in {"design", "write"}
    restarted = client(tmp_path)
    assert len(restarted.get("/api/v1/conversations/assistant/messages").json()) == 2


def test_missing_capability_creates_agent_with_safe_defaults(tmp_path):
    test_client = client(tmp_path)
    response = send(test_client, "assistant", "请做竞品分析")
    assert response.status_code == 202
    created = [agent for agent in test_client.get("/api/v1/agents").json() if "analysis.competitor" in agent["capabilities"]]
    assert len(created) == 1
    assert created[0]["tools"] == []
    assert created[0]["approval"] is True
    task = test_client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()
    assert task["steps"][0]["agent_id"] == created[0]["id"]
    with (tmp_path / "home" / "agents" / f"{created[0]['id']}.toml").open("rb") as source:
        assert tomllib.load(source)["capabilities"]["analysis.competitor"] > 0
    assert any(agent["id"] == created[0]["id"] for agent in client(tmp_path).get("/api/v1/agents").json())


def test_permission_expansion_requires_approval_and_is_single_use(tmp_path):
    test_client = client(tmp_path)
    original = test_client.get("/api/v1/agents/code").json()
    proposal = {"expected_version": original["version"], "model": original["model"],
                "tools": ["代码执行"], "approval": True}
    response = test_client.patch("/api/v1/agents/code", json=proposal)
    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"
    assert test_client.get("/api/v1/agents/code").json()["tools"] == []
    assert test_client.get("/api/v1/inbox?view=approvals").json()[0]["id"] == "code"
    approval_id = response.json()["approval_id"]
    decided = test_client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"})
    assert decided.status_code == 200
    updated = test_client.get("/api/v1/agents/code").json()
    assert updated["tools"] == ["代码执行"]
    assert updated["version"] == original["version"] + 1
    with (tmp_path / "home" / "agents" / "code.toml").open("rb") as source:
        assert tomllib.load(source)["tools"] == ["代码执行"]
    assert test_client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}).status_code == 409
    assert test_client.get("/api/v1/inbox?view=approvals").json() == []


def test_group_routing_and_read_mark(tmp_path):
    test_client = client(tmp_path)
    new_group = test_client.post("/api/v1/groups", json={"name": "界面评审", "member_ids": ["design", "write"]})
    assert new_group.status_code == 201
    group_id = new_group.json()["id"]
    with (tmp_path / "home" / "teams" / f"{group_id}.toml").open("rb") as source:
        assert tomllib.load(source)["members"] == ["design", "write"]
    response = send(test_client, group_id, "@小绘 请看看新界面")
    assert response.status_code == 202
    messages = test_client.get(f"/api/v1/conversations/{group_id}/messages").json()
    assert messages[-1]["speaker"] == "小绘"
    assert "本地演示模型" in messages[-1]["text"]
    assert test_client.post(f"/api/v1/conversations/{group_id}/read", json={"message_id": messages[-1]["id"]}).status_code == 200
    inbox = test_client.get("/api/v1/inbox?view=all").json()
    assert next(item for item in inbox if item["id"] == group_id)["unread"] is False


def test_configured_model_completes_assigned_task(tmp_path, monkeypatch):
    config_text = DEFAULT_CONFIG.read_text()
    config_path = tmp_path / "app.toml"
    config_path.write_text(config_text.replace('provider = "mock"', 'provider = "openai_compatible"'))

    async def fake_response(agent, history, config):
        return f"{agent['name']} 的可交付初稿"

    monkeypatch.setattr("futurework.app.respond", fake_response)
    test_client = TestClient(create_app(config_path=config_path, home=tmp_path / "home"))
    response = send(test_client, "assistant", "设计一个界面")
    task = test_client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "completed"
    assert task["steps"][0]["status"] == "completed"
    assistant_messages = test_client.get("/api/v1/conversations/assistant/messages").json()
    assert "可交付初稿" in assistant_messages[-1]["text"]


def test_agent_limit_rolls_back_assistant_request(tmp_path):
    config_text = DEFAULT_CONFIG.read_text()
    config_path = tmp_path / "app.toml"
    config_path.write_text(config_text.replace("max_agents = 30", "max_agents = 5"))
    test_client = TestClient(create_app(config_path=config_path, home=tmp_path / "home"))
    response = send(test_client, "assistant", "请做竞品分析")
    assert response.status_code == 409
    assert test_client.get("/api/v1/conversations/assistant/messages").json() == []
    assert len(test_client.get("/api/v1/agents").json()) == 5


def test_user_agent_file_is_authoritative_after_restart(tmp_path):
    test_client = client(tmp_path)
    path = tmp_path / "home" / "agents" / "code.toml"
    path.write_text(path.read_text().replace('role = "开发与自动化"', 'role = "Python 工程"\n# 手工备注'))
    restarted = client(tmp_path)
    assert restarted.get("/api/v1/agents/code").json()["role"] == "Python 工程"
    current = restarted.get("/api/v1/agents/code").json()
    patched = restarted.patch("/api/v1/agents/code", json={
        "expected_version": current["version"], "model": current["model"],
        "tools": [], "approval": True,
    })
    assert patched.status_code == 200
    assert "# 手工备注" in path.read_text()
    assert test_client.get("/api/v1/agents/code").json()["role"] == "Python 工程"
