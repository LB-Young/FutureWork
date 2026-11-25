"""Assemble the local Agent Team API, workflows, and packaged web application."""

import asyncio
import base64
import binascii
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from futurework.config import WEB_DIRECTORY, database_path, load_config
from futurework.abilities.tools.schedule import ScheduleStore
from futurework.database import Database
from futurework.config_store.writer import ConfigStore
from futurework.contexts.store import MemoryStore
from futurework.home import ensure_home
from futurework.model import AgentRuntime
from futurework.runtime.tool_approvals import ToolApprovalStore
from futurework.runtime.run_params import RunParams
from futurework.runtime.task_runtime import RequestConflict, TaskRuntime
from futurework.services.agent_service import AgentService, AgentServiceError
from futurework.services.group_service import GroupService, GroupServiceError
from futurework.services.message_service import MessageService
from futurework.workers.task_worker import TaskRecoveryWorker
from futurework.extension_system.workflow_runner import WorkflowRunner
from futurework.contexts.types import ScopeKey


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


class ImageUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    media_type: str
    data_base64: str


class VideoUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    media_type: str
    data_base64: str


class WorkflowInput(BaseModel):
    input: str = Field(min_length=1)


def create_app(home: str | Path | None = None, db_path: str | Path | None = None) -> FastAPI:
    user_home = ensure_home(home)
    config = load_config(user_home)
    config_store = ConfigStore(user_home)
    database = Database(database_path(config, user_home, Path(db_path) if db_path else None))
    database.initialize(config)
    memory_store = MemoryStore(user_home, config["memory"], config["ui"]["assistant_name"])
    memory_store.ensure_profiles()
    with database.transaction() as connection:
        memory_store.sync(connection)
    database.journal = memory_store
    app = FastAPI(title="FutureWork API", version="0.1.0")
    app.state.config = config
    app.state.database = database
    app.state.memory_store = memory_store
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
    agent_service = AgentService(database, config, config_store, message_service, memory_store)
    group_service = GroupService(database, config, config_store, memory_store)

    @app.exception_handler(AgentServiceError)
    @app.exception_handler(GroupServiceError)
    async def service_error(request: Request, error: AgentServiceError | GroupServiceError):
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})

    agent_runtime = AgentRuntime(config, memory_store=memory_store,
                                 approval_store=ToolApprovalStore(database, message_service, config))
    task_runtime = TaskRuntime(database=database, config=config, config_store=config_store,
                               message_service=message_service, agent_service=agent_service,
                               agent_runtime=agent_runtime)
    recovery_worker = TaskRecoveryWorker(database, config, message_service, task_runtime)
    workflow_runner = WorkflowRunner(user_home, config["workflow"])
    scheduler = ScheduleStore(user_home, config["schedule"])

    async def scheduled_request(job: dict) -> None:
        target = {"id": "assistant", "kind": "assistant", "name": config["ui"]["assistant_name"]}
        params = RunParams.from_http(target, job["prompt"], f"schedule:{job['id']}:{job['last_run_at']}")
        await task_runtime.handle(params, lambda task: asyncio.create_task(task_runtime.execute_assigned(task)))

    async def schedule_loop() -> None:
        while True:
            await scheduler.run_due(scheduled_request)
            await asyncio.sleep(config["schedule"]["poll_seconds"])

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        schedule_task = asyncio.create_task(schedule_loop())
        recovery_task = asyncio.create_task(recovery_worker.recover())
        try:
            yield
        finally:
            schedule_task.cancel()
            recovery_task.cancel()
            with suppress(asyncio.CancelledError):
                await schedule_task
            with suppress(asyncio.CancelledError):
                await recovery_task

    app.router.lifespan_context = lifespan

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

    @app.post("/api/v1/workflows/{workflow_id}/runs", status_code=201)
    async def run_workflow(workflow_id: str, body: WorkflowInput):
        """Execute a bounded declarative workflow through existing Agent runtimes."""
        async def execute_step(agent_id: str, prompt: str) -> str:
            agent = database.agent(agent_id)
            if not agent or agent["status"] != "active":
                raise ValueError(f"workflow Agent {agent_id} is unavailable")
            answer = await agent_runtime.respond(agent, [{"from": "me", "text": prompt}], ScopeKey("agent", agent_id))
            with database.transaction() as connection:
                message_service.insert(connection, agent_id, "system", "Workflow", prompt)
                message_service.insert(connection, agent_id, "agent", agent["name"], answer)
            return answer
        try:
            return await workflow_runner.run(workflow_id, body.input, execute_step)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

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

    @app.post("/api/v1/images", status_code=201)
    def upload_image(body: ImageUpload):
        """Store a small image in the user workspace for visual model tools."""
        allowed = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
        if body.media_type not in allowed or len(body.data_base64) > config["media"]["max_image_bytes"] * 2:
            raise HTTPException(422, "不支持的图片类型或文件过大")
        try:
            content = base64.b64decode(body.data_base64, validate=True)
        except binascii.Error as error:
            raise HTTPException(422, "图片编码无效") from error
        if not content or len(content) > config["media"]["max_image_bytes"]:
            raise HTTPException(422, "图片为空或超出大小限制")
        signatures = {"image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
                      "image/jpeg": content.startswith(b"\xff\xd8\xff"),
                      "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
                      "image/gif": content.startswith((b"GIF87a", b"GIF89a"))}
        if not signatures[body.media_type]:
            raise HTTPException(422, "图片内容与声明的类型不符")
        target = user_home / "workspace" / "uploads" / f"{uuid4().hex}{allowed[body.media_type]}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {"path": str(target.relative_to(user_home / "workspace"))}

    @app.post("/api/v1/videos", status_code=201)
    def upload_video(body: VideoUpload):
        """Store a bounded local video for keyframe analysis or editing."""
        allowed = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
        if body.media_type not in allowed or len(body.data_base64) > config["media"]["max_video_bytes"] * 2:
            raise HTTPException(422, "不支持的视频类型或文件过大")
        try:
            content = base64.b64decode(body.data_base64, validate=True)
        except binascii.Error as error:
            raise HTTPException(422, "视频编码无效") from error
        if not content or len(content) > config["media"]["max_video_bytes"]:
            raise HTTPException(422, "视频为空或超出大小限制")
        valid = content.startswith(b"\x1a\x45\xdf\xa3") if body.media_type == "video/webm" else content[4:8] == b"ftyp"
        if not valid:
            raise HTTPException(422, "视频内容与声明的类型不符")
        target = user_home / "workspace" / "uploads" / f"{uuid4().hex}{allowed[body.media_type]}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return {"path": str(target.relative_to(user_home / "workspace"))}

    @app.get("/api/v1/artifacts/{kind}/{filename}")
    def artifact(kind: str, filename: str):
        """Expose only generated media and edited output files to the local UI."""
        if kind not in {"media", "outputs"} or filename != Path(filename).name or not filename:
            raise HTTPException(404, "artifact not found")
        root = user_home / "data" / "media" if kind == "media" else user_home / "workspace" / "outputs"
        path = (root / filename).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise HTTPException(404, "artifact not found")
        return FileResponse(path, filename=filename, content_disposition_type="inline")

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
