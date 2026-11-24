"""Assemble the local Agent Team API, workflows, and packaged web application."""

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from futurework.config import WEB_DIRECTORY, database_path, load_config
from futurework.database import Database
from futurework.config_store.writer import ConfigStore
from futurework.home import ensure_home
from futurework.model import AgentRuntime
from futurework.runtime.run_params import RunParams
from futurework.runtime.task_runtime import RequestConflict, TaskRuntime
from futurework.services.agent_service import AgentService, AgentServiceError
from futurework.services.group_service import GroupService, GroupServiceError
from futurework.services.message_service import MessageService


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

    message_service = MessageService(database)
    agent_service = AgentService(database, config, config_store, message_service)
    group_service = GroupService(database, config, config_store)

    @app.exception_handler(AgentServiceError)
    @app.exception_handler(GroupServiceError)
    async def service_error(request: Request, error: AgentServiceError | GroupServiceError):
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})

    agent_runtime = AgentRuntime(config)
    task_runtime = TaskRuntime(database=database, config=config, config_store=config_store,
                               message_service=message_service, agent_service=agent_service,
                               agent_runtime=agent_runtime)

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
        return agent_service.create_agent(body.name, body.role)

    @app.patch("/api/v1/agents/{agent_id}")
    def patch_agent(agent_id: str, body: AgentPatch):
        return agent_service.patch_agent(agent_id, body.model_dump())

    @app.get("/api/v1/conversations")
    def conversations():
        return [{"id": "assistant", "kind": "assistant", "name": config["ui"]["assistant_name"]}] + [
            {"id": item["id"], "kind": "agent", "name": item["name"]} for item in database.agents()
        ] + [{"id": item["id"], "kind": "group", "name": item["name"]} for item in database.groups()]

    @app.post("/api/v1/groups", status_code=201)
    def create_group(body: GroupInput):
        return group_service.create(body.name, body.member_ids, body.mode)

    @app.get("/api/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str):
        get_conversation(conversation_id)
        return database.messages(conversation_id, config["server"]["message_history_limit"])

    @app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202)
    async def send_message(conversation_id: str, body: MessageInput, background_tasks: BackgroundTasks):
        conversation = get_conversation(conversation_id)
        params = RunParams.from_http(conversation, body.body, body.client_message_id)
        if not params.message or len(params.message) > config["limits"]["max_message_chars"]:
            raise HTTPException(422, "message is empty or too long")
        try:
            result = await task_runtime.handle(
                params, lambda task: background_tasks.add_task(task_runtime.execute_assigned, task))
        except RequestConflict as error:
            raise HTTPException(409, str(error)) from error
        return result.as_response()

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
        return agent_service.pending_approvals()

    @app.post("/api/v1/approvals/{approval_id}/decision")
    def decide(approval_id: str, body: DecisionInput):
        return agent_service.decide_approval(approval_id, body.decision)

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
