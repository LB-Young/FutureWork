"""Assemble the local Agent Team API, workflows, and packaged web application."""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from futurework.algorithm import assign_steps, plan_steps
from futurework.config import WEB_DIRECTORY, database_path, load_config
from futurework.database import Database, decode_agent, utc_now
from futurework.config_store.writer import ConfigStore
from futurework.home import ensure_home
from futurework.runtime.group_runtime import run_group_reply
from futurework.runtime.direct_runtime import run_direct_reply
from futurework.runtime.assistant_runtime import assistant_profile, classify_message, execute_assigned_task
from futurework.model import respond


def new_id() -> str:
    return str(uuid4())


class MessageInput(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1)


class AgentInput(BaseModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)


class AgentPatch(BaseModel):
    expected_version: int
    model: str
    tools: list[str]
    approval: bool


class DecisionInput(BaseModel):
    decision: str


class GroupInput(BaseModel):
    name: str = Field(min_length=1)
    member_ids: list[str] = Field(min_length=1)
    mode: str = "controlled"


class ReadInput(BaseModel):
    message_id: str


def create_app(home: str | Path | None = None, db_path: str | Path | None = None) -> FastAPI:
    user_home = ensure_home(home)
    config = load_config(user_home)
    config_store = ConfigStore(user_home)
    database = Database(database_path(config, user_home, Path(db_path) if db_path else None))
    database.initialize(config)
    app = FastAPI(title="FutureWork API", version="0.1.0")
    app.state.config = config
    app.state.database = database
    app.state.home = user_home

    def get_conversation(conversation_id: str) -> dict:
        if conversation_id == "assistant":
            return {"id": "assistant", "name": config["ui"]["assistant_name"], "kind": "assistant"}
        agent = database.agent(conversation_id)
        if agent and agent["status"] == "active":
            return {**agent, "kind": "agent"}
        group = database.group(conversation_id)
        if group and group["status"] == "active":
            return {**group, "kind": "group"}
        raise HTTPException(404, "conversation not found")

    def insert_message(connection, conversation_id: str, sender_kind: str, speaker: str,
                       text: str, client_message_id: str | None = None,
                       approval_id: str | None = None, task_id: str | None = None) -> dict:
        message = {
            "id": new_id(), "conversation_id": conversation_id, "sender_kind": sender_kind,
            "speaker": speaker, "text": text, "client_message_id": client_message_id,
            "approval_id": approval_id, "task_id": task_id, "created_at": utc_now(),
        }
        connection.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(message.values())
        )
        database.emit(connection, "message.created", {"conversation_id": conversation_id, "message_id": message["id"]})
        return message

    def make_agent(connection, write_config, name: str, role: str, capability: str) -> dict:
        if connection.execute("SELECT COUNT(*) FROM agents WHERE status='active'").fetchone()[0] >= config["limits"]["max_agents"]:
            raise HTTPException(409, "agent limit reached")
        base_name = name.strip()
        unique_name = base_name
        suffix = 2
        while connection.execute("SELECT 1 FROM agents WHERE name=?", (unique_name,)).fetchone():
            unique_name = f"{base_name} {suffix}"
            suffix += 1
        agent = {
            "id": new_id(), "name": unique_name, "role": role.strip(), "icon": unique_name[0],
            "color": config["ui"]["default_agent_color"], "ink": config["ui"]["default_agent_ink"],
            "model": config["model"]["default_model"], "tools": list(config["permissions"]["safe_default_tools"]),
            "capabilities": {capability: config["matching"]["auto_agent_proficiency"]},
            "approval": True, "version": 1, "status": "active",
        }
        database.insert_agent(connection, agent)
        write_config("agents", agent)
        database.emit(connection, "agent.created", {"agent_id": agent["id"]})
        return agent

    def apply_agent_patch(connection, write_config, agent_id: str, proposal: dict):
        current = connection.execute("SELECT version FROM agents WHERE id=?", (agent_id,)).fetchone()
        if not current or current["version"] != proposal["expected_version"]:
            raise HTTPException(409, "agent configuration has changed")
        connection.execute(
            "UPDATE agents SET model=?, tools=?, approval=?, version=version+1 WHERE id=?",
            (proposal["model"], json.dumps(proposal["tools"], ensure_ascii=False), int(proposal["approval"]), agent_id),
        )
        row = connection.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        write_config("agents", decode_agent(row))
        database.emit(connection, "agent.updated", {"agent_id": agent_id})

    async def execute_task(task_id: str):
        await execute_assigned_task(task_id, database, config, insert_message, respond)

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "model_provider": config["model"]["provider"]}

    @app.get("/api/v1/bootstrap")
    def bootstrap():
        pending_approval_count = len(database.inbox(config, "approvals"))
        return {
            "agents": database.agents(), "groups": database.groups(),
            "ui": config["ui"], "models": config["model"]["available_models"],
            "tools": config["permissions"]["available_tools"],
            "model_provider": config["model"]["provider"],
            "pending_approval_count": pending_approval_count,
            "extensions": config["installed_extensions"],
        }

    @app.get("/api/v1/extensions")
    def extensions():
        return config["installed_extensions"]

    @app.get("/api/v1/agents")
    def agents():
        return database.agents()

    @app.get("/api/v1/agents/{agent_id}")
    def agent(agent_id: str):
        result = database.agent(agent_id)
        if not result:
            raise HTTPException(404, "agent not found")
        return result

    @app.post("/api/v1/agents", status_code=201)
    def create_agent(body: AgentInput):
        if not body.name.strip() or not body.role.strip() or len(body.name.strip()) > config["limits"]["max_agent_name_chars"] or len(body.role.strip()) > config["limits"]["max_agent_role_chars"]:
            raise HTTPException(422, "agent name or role is too long")
        rules = plan_steps(body.role, config)
        capability = rules[0]["capability"]
        with config_store.batch() as write_config:
            with database.transaction() as connection:
                created = make_agent(connection, write_config, body.name, body.role, capability)
                insert_message(connection, created["id"], "agent", created["name"], f"你好，我是{created['name']}。我的职责是{created['role']}。")
        return created

    @app.patch("/api/v1/agents/{agent_id}")
    def patch_agent(agent_id: str, body: AgentPatch):
        existing = database.agent(agent_id)
        if not existing:
            raise HTTPException(404, "agent not found")
        if body.model not in config["model"]["available_models"]:
            raise HTTPException(422, "model is not available")
        if len(body.tools) != len(set(body.tools)) or not set(body.tools).issubset(config["permissions"]["available_tools"]):
            raise HTTPException(422, "unknown or duplicate tool")
        proposal = body.model_dump()
        if existing["version"] != body.expected_version:
            raise HTTPException(409, "agent configuration has changed")
        added = set(body.tools) - set(existing["tools"])
        high_risk = added.intersection(config["permissions"]["approval_required_tools"]) or (existing["approval"] and not body.approval)
        if high_risk:
            approval_id = new_id()
            description = f"将 {existing['name']} 的权限更新为：{', '.join(body.tools) or '无工具'}；模型：{body.model}；关键操作审批：{'开启' if body.approval else '关闭'}"
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=config["limits"]["approval_ttl_hours"])).isoformat()
            with database.transaction() as connection:
                connection.execute(
                    "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL)",
                    (approval_id, agent_id, agent_id, description, json.dumps(proposal, ensure_ascii=False), expires_at, utc_now()),
                )
                insert_message(connection, agent_id, "system", "系统", description, approval_id=approval_id)
                database.emit(connection, "approval.created", {"approval_id": approval_id, "conversation_id": agent_id})
            return {"status": "pending_approval", "approval_id": approval_id}
        with config_store.batch() as write_config:
            with database.transaction() as connection:
                apply_agent_patch(connection, write_config, agent_id, proposal)
        return {"status": "updated", "agent": database.agent(agent_id)}

    @app.get("/api/v1/conversations")
    def conversations():
        return [{"id": "assistant", "kind": "assistant", "name": config["ui"]["assistant_name"]}] + [
            {"id": item["id"], "kind": "agent", "name": item["name"]} for item in database.agents()
        ] + [{"id": item["id"], "kind": "group", "name": item["name"]} for item in database.groups()]

    @app.post("/api/v1/groups", status_code=201)
    def create_group(body: GroupInput):
        members = list(dict.fromkeys(body.member_ids))
        if not body.name.strip() or len(body.name.strip()) > config["limits"]["max_group_name_chars"] or len(members) > config["limits"]["max_group_members"]:
            raise HTTPException(422, "invalid group name or member count")
        if body.mode not in {"swarm", "controlled"}:
            raise HTTPException(422, "invalid group mode")
        if any(not database.agent(member) or database.agent(member)["status"] != "active" for member in members):
            raise HTTPException(422, "group contains unknown agent")
        group_id = new_id()
        names = [database.agent(member)["name"] for member in members]
        group = {"id": group_id, "name": body.name.strip(), "role": "、".join(names), "icon": body.name.strip()[0],
                 "color": config["ui"]["default_agent_color"], "ink": config["ui"]["default_agent_ink"], "members": members, "status": "active", "mode": body.mode}
        with config_store.batch() as write_config:
            with database.transaction() as connection:
                connection.execute("INSERT INTO groups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (group_id, group["name"], group["role"], group["icon"], group["color"], group["ink"], json.dumps(members), utc_now(), "active", body.mode))
                write_config("teams", group)
                database.emit(connection, "group.created", {"group_id": group_id})
        return group

    @app.get("/api/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str):
        get_conversation(conversation_id)
        return database.messages(conversation_id, config["server"]["message_history_limit"])

    @app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202)
    async def send_message(conversation_id: str, body: MessageInput, background_tasks: BackgroundTasks):
        conversation = get_conversation(conversation_id)
        text = body.body.strip()
        if not text or len(text) > config["limits"]["max_message_chars"]:
            raise HTTPException(422, "message is empty or too long")
        if conversation["kind"] == "assistant":
            with database.transaction() as connection:
                duplicate = connection.execute("SELECT id, task_id, conversation_id FROM messages WHERE client_message_id=?", (body.client_message_id,)).fetchone()
                if duplicate:
                    if duplicate["conversation_id"] != conversation_id:
                        raise HTTPException(409, "client message ID already used in another conversation")
                    return {"message_id": duplicate["id"], "task_id": duplicate["task_id"], "status": "accepted"}
            history = database.messages("assistant", config["server"]["message_history_limit"])
            if await classify_message(text, history, config) == "chat":
                with database.transaction() as connection:
                    user_message = insert_message(connection, "assistant", "user", "你", text, body.client_message_id)
                try:
                    reply = await respond(assistant_profile(config), database.messages("assistant", config["server"]["message_history_limit"]), config)
                except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
                    reply = f"模型暂时不可用：{type(error).__name__}。消息已保存，请检查模型配置。"
                with database.transaction() as connection:
                    insert_message(connection, "assistant", "agent", config["ui"]["assistant_name"], reply)
                return {"message_id": user_message["id"], "task_id": None, "status": "accepted"}
            task_id = new_id()
            with config_store.batch() as write_config, database.transaction() as connection:
                duplicate = connection.execute("SELECT id, task_id, conversation_id FROM messages WHERE client_message_id=?", (body.client_message_id,)).fetchone()
                if duplicate:
                    if duplicate["conversation_id"] != conversation_id:
                        raise HTTPException(409, "client message ID already used in another conversation")
                    return {"message_id": duplicate["id"], "task_id": duplicate["task_id"], "status": "accepted"}
                live_agents = [decode_agent(row) for row in connection.execute("SELECT * FROM agents WHERE status='active'")]
                assignments = assign_steps(text, live_agents, config)
                user_message = insert_message(connection, conversation_id, "user", "你", text, body.client_message_id, task_id=task_id)
                created_names = []
                assigned_names = []
                connection.execute("INSERT INTO tasks VALUES (?, ?, ?, 'assigned', ?)", (task_id, conversation_id, text, utc_now()))
                for assignment in assignments:
                    agent_id = assignment.agent_id
                    if not agent_id:
                        created = make_agent(connection, write_config, assignment.suggested_name, assignment.suggested_role, assignment.capability)
                        agent_id = created["id"]
                        created_names.append(created["name"])
                        insert_message(connection, agent_id, "agent", created["name"], f"你好，我是{created['name']}。已准备好承担{assignment.title}。")
                    agent_row = connection.execute("SELECT name FROM agents WHERE id=?", (agent_id,)).fetchone()
                    agent_name = agent_row["name"]
                    assigned_names.append(f"{assignment.title} → {agent_name}")
                    version = connection.execute("SELECT version FROM agents WHERE id=?", (agent_id,)).fetchone()["version"]
                    connection.execute("INSERT INTO task_steps VALUES (?, ?, ?, ?, ?, 'assigned', ?)",
                                       (new_id(), task_id, agent_id, assignment.capability, assignment.title, version))
                    insert_message(connection, agent_id, "system", "小未", f"新任务已分派：{assignment.title}。来源：{text}", task_id=task_id)
                summary = "已拆解并分派任务：" + "；".join(assigned_names) + "。"
                if created_names:
                    summary += " 新建 Agent：" + "、".join(created_names) + "。已按最小权限配置。"
                if config["model"]["provider"] == "mock":
                    summary += " 当前为本地演示模型，任务停在已分派状态；配置真实模型后可生成初稿。"
                else:
                    summary += " Agent 正在生成初稿；外部工具尚未接入。"
                insert_message(connection, "assistant", "agent", config["ui"]["assistant_name"], summary, task_id=task_id)
                database.emit(connection, "task.updated", {"task_id": task_id, "status": "assigned"})
            if config["model"]["provider"] != "mock" and config["execution"]["run_assigned_steps_with_model"]:
                background_tasks.add_task(execute_task, task_id)
            return {"message_id": user_message["id"], "task_id": task_id, "status": "accepted"}
        with database.transaction() as connection:
            duplicate = connection.execute("SELECT id, task_id, conversation_id FROM messages WHERE client_message_id=?", (body.client_message_id,)).fetchone()
            if duplicate:
                if duplicate["conversation_id"] != conversation_id:
                    raise HTTPException(409, "client message ID already used in another conversation")
                return {"message_id": duplicate["id"], "task_id": duplicate["task_id"], "status": "accepted"}
            user_message = insert_message(connection, conversation_id, "user", "你", text, body.client_message_id)
        if conversation["kind"] == "group":
            await run_group_reply(conversation, text, database, config, insert_message)
            return {"message_id": user_message["id"], "task_id": None, "status": "accepted"}
        await run_direct_reply(conversation, database, config, insert_message, respond)
        return {"message_id": user_message["id"], "task_id": None, "status": "accepted"}

    @app.post("/api/v1/conversations/{conversation_id}/read")
    def mark_read(conversation_id: str, body: ReadInput):
        get_conversation(conversation_id)
        with database.transaction() as connection:
            requested = connection.execute("SELECT rowid FROM messages WHERE id=? AND conversation_id=?", (body.message_id, conversation_id)).fetchone()
            if not requested:
                raise HTTPException(404, "message not found")
            current = connection.execute("SELECT messages.rowid FROM read_marks JOIN messages ON messages.id=read_marks.message_id WHERE read_marks.conversation_id=?", (conversation_id,)).fetchone()
            if current and current["rowid"] >= requested["rowid"]:
                return {"status": "ok"}
            connection.execute("INSERT INTO read_marks VALUES (?, ?) ON CONFLICT(conversation_id) DO UPDATE SET message_id=excluded.message_id",
                               (conversation_id, body.message_id))
            database.emit(connection, "inbox.updated", {"conversation_id": conversation_id})
        return {"status": "ok"}

    @app.get("/api/v1/inbox")
    def inbox(view: str = "recent"):
        if view not in {"recent", "all", "approvals"}:
            raise HTTPException(422, "invalid inbox view")
        return database.inbox(config, view)

    @app.get("/api/v1/approvals")
    def approvals():
        with database.transaction() as connection:
            rows = connection.execute("SELECT * FROM approvals WHERE status='pending' AND expires_at>? ORDER BY created_at DESC", (utc_now(),)).fetchall()
            return [dict(row) | {"proposal": json.loads(row["proposal"])} for row in rows]

    @app.post("/api/v1/approvals/{approval_id}/decision")
    def decide(approval_id: str, body: DecisionInput):
        if body.decision not in {"approve", "reject"}:
            raise HTTPException(422, "invalid decision")
        with config_store.batch() as write_config, database.transaction() as connection:
            row = connection.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not row:
                raise HTTPException(404, "approval not found")
            if row["status"] != "pending" or row["expires_at"] <= utc_now():
                raise HTTPException(409, "approval is no longer pending")
            if body.decision == "approve":
                apply_agent_patch(connection, write_config, row["agent_id"], json.loads(row["proposal"]))
            status = "approved" if body.decision == "approve" else "rejected"
            connection.execute("UPDATE approvals SET status=?, decided_at=? WHERE id=? AND status='pending'", (status, utc_now(), approval_id))
            insert_message(connection, row["conversation_id"], "system", "系统", "配置审批已通过。" if status == "approved" else "配置审批已拒绝。")
            database.emit(connection, "approval.resolved", {"approval_id": approval_id, "conversation_id": row["conversation_id"], "status": status})
        return {"id": approval_id, "status": status}

    @app.get("/api/v1/tasks/{task_id}")
    def task(task_id: str):
        with database.transaction() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise HTTPException(404, "task not found")
            steps = [dict(item) for item in connection.execute("SELECT * FROM task_steps WHERE task_id=?", (task_id,))]
            return {**dict(row), "steps": steps}

    @app.get("/api/v1/events")
    async def events(request: Request, after: int = 0):
        async def stream():
            sequence = max(0, after)
            idle = 0.0
            while not await request.is_disconnected():
                found = database.events_after(sequence, config["server"]["event_batch_size"])
                for event in found:
                    sequence = event["sequence"]
                    yield f"id: {sequence}\nevent: {event['type']}\ndata: {event['payload']}\n\n"
                if found:
                    idle = 0.0
                else:
                    idle += config["server"]["event_poll_seconds"]
                    if idle >= config["server"]["event_heartbeat_seconds"]:
                        yield ": heartbeat\n\n"
                        idle = 0.0
                await asyncio.sleep(config["server"]["event_poll_seconds"])
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=str(WEB_DIRECTORY), html=True), name="frontend")
    return app
