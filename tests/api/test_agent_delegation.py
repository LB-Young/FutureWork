"""Verify XiaoWei delegates only after its model requests the delegation tool."""

from uuid import uuid4

from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.home import ensure_home
from futurework.integrations.model_gateway.types import ModelResult, ToolCall
from futurework.integrations.model_gateway.gateway import ModelGateway
from futurework.runtime.agent_executor import AgentRuntime
from futurework.runtime.tool_approvals import ToolApprovalStore
from futurework.database import utc_now


def test_assistant_chooses_delegation_tool(tmp_path, monkeypatch):
    calls = []

    async def model_reply(self, request):
        calls.append(request)
        system = request.messages[0]["content"]
        if "你的名字是小未" in system:
            if any(message.get("role") == "tool" for message in request.messages):
                return ModelResult("已经让专家完成，结果已保存。")
            return ModelResult(tool_calls=[ToolCall("delegate-1", "delegate_task",
                                                    {"request": "请做竞品分析"})])
        return ModelResult("竞品分析初稿已完成")

    monkeypatch.setattr(ModelGateway, "generate", model_reply)
    home = ensure_home(tmp_path / "home")
    client = TestClient(create_app(home))
    created = client.post("/api/v1/agents", json={"name": "竞品专家", "role": "竞品分析",
                    "capabilities": {"analysis.competitor": 0.95}})
    assert created.status_code == 201
    response = client.post("/api/v1/conversations/assistant/messages",
                           json={"client_message_id": str(uuid4()), "body": "请做竞品分析"})
    assert response.status_code == 202
    assert response.json()["task_id"]
    task = client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "completed"
    assert task["steps"]
    assert len(calls) >= 3
    messages = client.get("/api/v1/conversations/assistant/messages").json()
    assert messages[-1]["text"] == "已经让专家完成，结果已保存。"


def test_delegation_does_not_create_a_friend_implicitly(tmp_path, monkeypatch):
    async def model_reply(self, request):
        if any(message.get("role") == "tool" for message in request.messages):
            return ModelResult("还没有合适好友，需要先配置。")
        return ModelResult(tool_calls=[ToolCall("delegate-1", "delegate_task",
                                                {"request": "请做竞品分析"})])

    monkeypatch.setattr(ModelGateway, "generate", model_reply)
    client = TestClient(create_app(ensure_home(tmp_path / "home")))
    before = len(client.get("/api/v1/agents").json())
    response = client.post("/api/v1/conversations/assistant/messages",
                           json={"client_message_id": str(uuid4()), "body": "请做竞品分析"})
    assert response.json()["task_id"] is None
    assert len(client.get("/api/v1/agents").json()) == before


def test_assistant_creates_approved_friend_then_delegates(tmp_path, monkeypatch):
    async def approve(self, approval_id):
        with self.database.transaction() as connection:
            connection.execute("UPDATE approvals SET status='approved', decided_at=? WHERE id=?",
                               (utc_now(), approval_id))
        return True

    async def model_reply(self, request):
        if "你的名字是小未" not in request.messages[0]["content"]:
            return ModelResult("分析已完成")
        tool_outputs = [message for message in request.messages if message.get("role") == "tool"]
        if not tool_outputs:
            return ModelResult(tool_calls=[ToolCall("find", "delegate_task", {"request": "请做竞品分析"})])
        if len(tool_outputs) == 1:
            assert "no_matching_friend" in tool_outputs[-1]["content"]
            return ModelResult(tool_calls=[ToolCall("create", "friend_create", {
                "name": "竞品专家", "role": "竞品分析", "model": "default_fast",
                "tools": ["read"], "skills": [], "capabilities": {"analysis.competitor": 0.95}})])
        if len(tool_outputs) == 2:
            assert "竞品专家" in tool_outputs[-1]["content"]
            return ModelResult(tool_calls=[ToolCall("assign", "delegate_task", {"request": "请做竞品分析"})])
        return ModelResult("专家已完成分析")

    monkeypatch.setattr(ToolApprovalStore, "wait", approve)
    monkeypatch.setattr(ModelGateway, "generate", model_reply)
    client = TestClient(create_app(ensure_home(tmp_path / "home")))
    response = client.post("/api/v1/conversations/assistant/messages",
                           json={"client_message_id": str(uuid4()), "body": "请做竞品分析"})
    assert response.status_code == 202
    assert client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()["status"] == "completed"
    assert any(agent["name"] == "竞品专家" for agent in client.get("/api/v1/agents").json())


def test_assistant_can_answer_without_planning(tmp_path, monkeypatch):
    async def model_reply(self, request):
        return ModelResult("直接答复")

    monkeypatch.setattr(ModelGateway, "generate", model_reply)
    client = TestClient(create_app(ensure_home(tmp_path / "home")))
    response = client.post("/api/v1/conversations/assistant/messages",
                           json={"client_message_id": str(uuid4()), "body": "你好"})
    assert response.status_code == 202
    assert response.json()["task_id"] is None
    assert client.get("/api/v1/conversations/assistant/messages").json()[-1]["text"] == "直接答复"


def test_assistant_can_delegate_to_a_team(tmp_path, monkeypatch):
    home = ensure_home(tmp_path / "home")
    client = TestClient(create_app(home))
    group = client.post("/api/v1/groups", json={
        "name": "测试协作", "member_ids": ["image"], "mode": "swarm"}).json()

    async def model_reply(self, request):
        system = request.messages[0]["content"]
        if "你的名字是小未" in system:
            if any(message.get("role") == "tool" for message in request.messages):
                return ModelResult("群任务已完成")
            return ModelResult(tool_calls=[ToolCall("delegate-team", "delegate_task", {
                "request": "请讨论一张海报", "target_kind": "group", "target_id": group["id"]})])
        return ModelResult("群成员完成海报建议")

    monkeypatch.setattr(ModelGateway, "generate", model_reply)
    response = client.post("/api/v1/conversations/assistant/messages",
                           json={"client_message_id": str(uuid4()), "body": "让群讨论海报"})
    assert response.status_code == 202
    assert client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()["status"] == "completed"
    group_messages = client.get(f"/api/v1/conversations/{group['id']}/messages").json()
    assert group_messages[-1]["text"] == "群成员完成海报建议"


def test_failed_team_delegation_stays_failed(tmp_path, monkeypatch):
    """A team error message must not count as a completed delegation."""
    client = TestClient(create_app(ensure_home(tmp_path / "home")))
    group = client.post("/api/v1/groups", json={
        "name": "失败群", "member_ids": ["image"], "mode": "swarm"}).json()

    async def model_reply(self, request):
        if "你的名字是小未" in request.messages[0]["content"]:
            if any(message.get("role") == "tool" for message in request.messages):
                return ModelResult("群任务失败，请检查配置。")
            return ModelResult(tool_calls=[ToolCall("delegate-team", "delegate_task", {
                "request": "请处理任务", "target_kind": "group", "target_id": group["id"]})])
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ModelGateway, "generate", model_reply)
    response = client.post("/api/v1/conversations/assistant/messages",
                           json={"client_message_id": str(uuid4()), "body": "让群处理任务"})
    assert response.status_code == 202
    task = client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "failed"
