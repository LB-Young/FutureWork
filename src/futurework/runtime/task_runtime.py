"""Route typed conversation tasks to assistant, friend, or group execution."""

from __future__ import annotations

import httpx
from collections.abc import Callable
from uuid import uuid4

from futurework.algorithm import assign_steps
from futurework.database import decode_agent, utc_now
from futurework.runtime.assistant_runtime import assistant_profile, execute_assigned_task
from futurework.runtime.direct_runtime import run_direct_reply
from futurework.runtime.group_runtime import run_group_reply
from futurework.runtime.run_params import RunParams
from futurework.runtime.task_factory import Task, TaskFactory, TaskKind, TaskResult


class RequestConflict(Exception):
    """A client message ID already belongs to another conversation."""


class TaskRuntime:
    """Handle one normalized request and dispatch the resulting Task by kind."""

    def __init__(self, *, database, config: dict, config_store, insert_message,
                 make_agent, classify_message, model_respond) -> None:
        self.database = database
        self.config = config
        self.config_store = config_store
        self.insert_message = insert_message
        self.make_agent = make_agent
        self.classify_message = classify_message
        self.model_respond = model_respond
        self.factory = TaskFactory()

    def _duplicate(self, connection, params: RunParams) -> TaskResult | None:
        """Preserve client-message idempotency and reject cross-session reuse."""
        row = connection.execute(
            "SELECT id, task_id, conversation_id FROM messages WHERE client_message_id=?",
            (params.client_message_id,),
        ).fetchone()
        if not row:
            return None
        if row["conversation_id"] != params.conversation_id:
            raise RequestConflict("client message ID already used in another conversation")
        return TaskResult(message_id=row["id"], task_id=row["task_id"])

    async def handle(self, params: RunParams, schedule: Callable[[Task], None]) -> TaskResult:
        """Classify only new assistant requests, then build and run one Task."""
        with self.database.transaction() as connection:
            duplicate = self._duplicate(connection, params)
            if duplicate:
                return duplicate
        intent = None
        if params.target.kind == "assistant":
            history = self.database.messages(params.conversation_id, self.config["server"]["message_history_limit"])
            intent = await self.classify_message(params.message, history, self.config)
        task = self.factory.create(params, assistant_intent=intent)
        return await self.run(task, schedule)

    async def run(self, task: Task, schedule: Callable[[Task], None]) -> TaskResult:
        """Dispatch by task kind without reclassifying or rebuilding input."""
        task.status = "running"
        if task.kind is TaskKind.ASSISTANT_CHAT:
            result = await self._assistant_chat(task)
        elif task.kind is TaskKind.ASSISTANT_DELEGATION:
            result = self._delegate(task, schedule)
        elif task.kind in {TaskKind.GROUP_SWARM, TaskKind.GROUP_CONTROLLED, TaskKind.AGENT_CHAT}:
            result = await self._conversation_reply(task)
        else:
            raise ValueError(f"Unsupported task kind: {task.kind}")
        task.status = "assigned" if task.kind is TaskKind.ASSISTANT_DELEGATION else "completed"
        return result

    async def _assistant_chat(self, task: Task) -> TaskResult:
        """Save one assistant-scoped chat and its response."""
        params = task.params
        with self.database.transaction() as connection:
            duplicate = self._duplicate(connection, params)
            if duplicate:
                return duplicate
            user_message = self.insert_message(connection, params.conversation_id, "user", "你",
                                               params.message, params.client_message_id)
        try:
            history = self.database.messages(params.conversation_id, self.config["server"]["message_history_limit"])
            reply = await self.model_respond(assistant_profile(self.config), history, self.config)
        except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            reply = f"模型暂时不可用：{type(error).__name__}。消息已保存，请检查模型配置。"
        with self.database.transaction() as connection:
            self.insert_message(connection, params.conversation_id, "agent", self.config["ui"]["assistant_name"], reply)
        return TaskResult(message_id=user_message["id"])

    def _delegate(self, task: Task, schedule: Callable[[Task], None]) -> TaskResult:
        """Persist a planned delegation and queue the same Task object for execution."""
        params = task.params
        config = self.config
        with self.config_store.batch() as write_config, self.database.transaction() as connection:
            duplicate = self._duplicate(connection, params)
            if duplicate:
                return duplicate
            agents = [decode_agent(row) for row in connection.execute("SELECT * FROM agents WHERE status='active'")]
            assignments = assign_steps(params.message, agents, config)
            user_message = self.insert_message(connection, params.conversation_id, "user", "你",
                                               params.message, params.client_message_id, task_id=task.id)
            connection.execute("INSERT INTO tasks VALUES (?, ?, ?, 'assigned', ?)",
                               (task.id, params.conversation_id, params.message, utc_now()))
            created_names = []
            assigned_names = []
            for assignment in assignments:
                agent_id = assignment.agent_id
                if not agent_id:
                    created = self.make_agent(connection, write_config, assignment.suggested_name,
                                              assignment.suggested_role, assignment.capability)
                    agent_id = created["id"]
                    created_names.append(created["name"])
                    self.insert_message(connection, agent_id, "agent", created["name"],
                                        f"你好，我是{created['name']}。已准备好承担{assignment.title}。")
                agent_row = connection.execute("SELECT name, version FROM agents WHERE id=?", (agent_id,)).fetchone()
                assigned_names.append(f"{assignment.title} → {agent_row['name']}")
                connection.execute("INSERT INTO task_steps VALUES (?, ?, ?, ?, ?, 'assigned', ?)",
                                   (str(uuid4()), task.id,
                                    agent_id, assignment.capability, assignment.title, agent_row["version"]))
                self.insert_message(connection, agent_id, "system", "小未",
                                    f"新任务已分派：{assignment.title}。来源：{params.message}", task_id=task.id)
            summary = "已拆解并分派任务：" + "；".join(assigned_names) + "。"
            if created_names:
                summary += " 新建 Agent：" + "、".join(created_names) + "。已按最小权限配置。"
            if config["model"]["provider"] == "mock":
                summary += " 当前为本地演示模型，任务停在已分派状态；配置真实模型后可生成初稿。"
            else:
                summary += " Agent 正在生成初稿；已授权的工具可在执行中调用。"
            self.insert_message(connection, "assistant", "agent", config["ui"]["assistant_name"],
                                summary, task_id=task.id)
            self.database.emit(connection, "task.updated", {"task_id": task.id, "status": "assigned"})
        if config["model"]["provider"] != "mock" and config["execution"]["run_assigned_steps_with_model"]:
            schedule(task)
        return TaskResult(message_id=user_message["id"], task_id=task.id)

    async def execute_assigned(self, task: Task) -> None:
        """Continue the persisted delegation using its original Task identity."""
        await execute_assigned_task(task, self.database, self.config, self.insert_message, self.model_respond)

    async def _conversation_reply(self, task: Task) -> TaskResult:
        """Persist a user turn and invoke the matching friend or group runtime."""
        params = task.params
        with self.database.transaction() as connection:
            duplicate = self._duplicate(connection, params)
            if duplicate:
                return duplicate
            user_message = self.insert_message(connection, params.conversation_id, "user", "你",
                                               params.message, params.client_message_id)
        if task.kind in {TaskKind.GROUP_SWARM, TaskKind.GROUP_CONTROLLED}:
            await run_group_reply(task, self.database, self.config, self.insert_message)
        else:
            await run_direct_reply(task, self.database, self.config, self.insert_message, self.model_respond)
        return TaskResult(message_id=user_message["id"])
