"""Exercise assistant dispatch, config writes, approvals, and both Team modes."""

import asyncio
import json
import tomllib
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from futurework.api.app import create_app
from tests.support import sample_home
from futurework.integrations.model_gateway.gateway import ModelGateway
from futurework.integrations.model_gateway.types import ModelResult, ToolCall
from futurework.runtime.agent_executor import AgentResponse
from futurework.runtime.tool_dispatch import ToolRegistry
from futurework.contexts.types import ScopeKey


def send(client, conversation_id, body):
    """Submit one idempotent user message to a conversation."""
    return client.post(f"/api/v1/conversations/{conversation_id}/messages",
                       json={"client_message_id": str(uuid4()), "body": body})


def test_assistant_dispatch_and_agent_file_survive_restart(tmp_path, monkeypatch):
    async def fake_generate(self, request):
        system = request.messages[0]["content"]
        if "你的名字是小未" in system:
            if any(message.get("role") == "tool" for message in request.messages):
                return ModelResult("专家已经完成。")
            return ModelResult(tool_calls=[ToolCall("delegate", "delegate_task",
                                                    {"request": "请做竞品分析"})])
        return ModelResult("竞品分析初稿已完成")

    monkeypatch.setattr(ModelGateway, "generate", fake_generate)
    home = sample_home(tmp_path / "home")
    client = TestClient(create_app(home))
    created_response = client.post("/api/v1/agents", json={"name": "竞品专家", "role": "竞品分析",
                                   "capabilities": {"analysis.competitor": 0.95}})
    assert created_response.status_code == 201
    response = send(client, "assistant", "请做竞品分析")
    assert response.status_code == 202
    task = client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "completed"
    created = created_response.json()
    with (home / "agents" / f"{created['id']}.toml").open("rb") as source:
        assert tomllib.load(source)["model"]["id"] == "default_fast"
    assert any(item["id"] == created["id"] for item in TestClient(create_app(home)).get("/api/v1/agents").json())


def test_assistant_chat_stays_in_its_own_conversation(tmp_path, monkeypatch):
    async def fake_respond(self, agent, history, scope=None):
        return AgentResponse("你好，我是小未。")

    monkeypatch.setattr("futurework.model.AgentRuntime.respond_with_result", fake_respond)
    client = TestClient(create_app(sample_home(tmp_path / "home")))
    response = send(client, "assistant", "你好")
    assert response.status_code == 202
    assert response.json()["task_id"] is None
    messages = client.get("/api/v1/conversations/assistant/messages").json()
    assert [item["speaker"] for item in messages] == ["你", "小未"]


def test_assistant_directory_tool_reads_current_friends_and_teams(tmp_path, monkeypatch):
    seen = []

    async def fake_generate(self, request):
        if request.messages[-1]["role"] == "tool":
            directory = json.loads(request.messages[-1]["content"])
            seen.append(directory)
            return ModelResult("团队有小未和数据专家，数据组包含数据专家。")
        assert "team_directory" in {tool["function"]["name"] for tool in request.tools}
        assert "当前团队 Agent 好友" not in request.messages[0]["content"]
        return ModelResult(tool_calls=[ToolCall("directory-1", "team_directory", {})])

    monkeypatch.setattr(ModelGateway, "generate", fake_generate)
    client = TestClient(create_app(sample_home(tmp_path / "home")))
    friend = client.post("/api/v1/agents", json={"name": "数据专家", "role": "分析数据"}).json()
    client.post("/api/v1/groups", json={"name": "数据组", "member_ids": [friend["id"]], "mode": "swarm"})
    assert send(client, "assistant", "团队有哪些人").status_code == 202
    assert any(item["name"] == "数据专家" for item in seen[0]["friends"])
    assert any(team["name"] == "数据组" and team["members"][0]["name"] == "数据专家"
               for team in seen[0]["teams"])
    assert seen[0]["assistant"]["name"] == "小未"

    registry = ToolRegistry("image", ["team_directory"], client.app.state.config,
                            scope=ScopeKey("agent", "image"),
                            agent_service=SimpleNamespace(database=client.app.state.database,
                                                          config=client.app.state.config))
    assert not asyncio.run(registry.execute("team_directory", {})).success


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
        if agent["id"] == "assistant":
            return "小未汇报结果" if "汇报本轮" in history[-1]["text"] else '{"action":"delegate","agent_id":"design"}'
        return f"{agent['name']} 的回复"

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
    assert speakers == ["你", "小未", "小绘", "小未"]


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
    decisions = []
    async def fake_respond(self, agent, history, scope=None):
        if agent["id"] == "assistant":
            if "汇报本轮" in history[-1]["text"]:
                return "任务已汇总"
            decisions.append([item["speaker"] for item in history if "speaker" in item])
            return ('{"action":"delegate","agent_id":"design"}' if len(decisions) == 1
                    else '{"action":"delegate","agent_id":"write"}')
        return f"{agent['name']} 已完成"

    monkeypatch.setattr("futurework.model.AgentRuntime.respond", fake_respond)
    client = TestClient(create_app(sample_home(tmp_path / "home")))
    response = client.post("/api/v1/groups", json={"name": "联合发布", "member_ids": ["design", "write"], "mode": "controlled"})
    group_id = response.json()["id"]
    assert send(client, group_id, "请设计并写发布文案").status_code == 202
    speakers = [item["speaker"] for item in client.get(f"/api/v1/conversations/{group_id}/messages").json()]
    assert speakers == ["你", "小未", "小绘", "小未", "言言", "小未"]
    assert len(decisions) == 2
    assert "小绘" in decisions[1]


def test_assistant_settings_follow_friend_approval_flow(tmp_path):
    home = sample_home(tmp_path / "home")
    client = TestClient(create_app(home))
    assistant = client.get("/api/v1/agents/assistant").json()
    assert client.get("/api/v1/bootstrap").json()["assistant"]["id"] == "assistant"
    assert "delegate_task" in assistant["tools"]
    proposal = {"expected_version": assistant["version"], "model": "default_fast",
                "tools": [*assistant["tools"], "write"], "approval": True}
    pending = client.patch("/api/v1/agents/assistant", json=proposal).json()
    assert pending["status"] == "pending_approval"
    assert "write" not in client.get("/api/v1/agents/assistant").json()["tools"]
    assert client.post(f"/api/v1/approvals/{pending['approval_id']}/decision", json={"decision": "approve"}).status_code == 200
    updated = client.get("/api/v1/agents/assistant").json()
    assert "write" in updated["tools"] and updated["version"] == assistant["version"] + 1
    with (home / "agents" / "assistant.toml").open("rb") as source:
        assert tomllib.load(source)["version"] == updated["version"]
    assert "write" in TestClient(create_app(home)).get("/api/v1/agents/assistant").json()["tools"]
    revised = client.patch("/api/v1/agents/assistant", json={
        "expected_version": updated["version"], "model": updated["model"],
        "tools": [tool for tool in updated["tools"] if tool != "delegate_task"], "approval": True})
    assert revised.json()["status"] == "updated"
    assert "delegate_task" not in client.get("/api/v1/agents/assistant").json()["tools"]
