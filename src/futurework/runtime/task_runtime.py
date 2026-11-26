"""Persist one inbound turn and route it to an Agent or Team loop."""

from __future__ import annotations

from futurework.runtime.team_runtime import TeamRuntime
from futurework.runtime.errors import retry_operation
from futurework.runtime.run_params import RunParams
from futurework.runtime.task_factory import Task, TaskFactory, TaskKind, TaskResult


class RequestConflict(Exception):
    """A client message ID already belongs to another conversation."""


class TaskRuntime:
    """Own idempotency, task lifecycle, routing, and replay-safe task recovery."""

    def __init__(self, *, database, config: dict, config_store, message_service,
                 agent_service, agent_runtime) -> None:
        self.database = database
        self.config = config
        self.message_service = message_service
        self.factory = TaskFactory()
        self.agent = agent_runtime
        self.team = TeamRuntime(database, config, message_service, agent_runtime)

    def _duplicate(self, connection, params: RunParams) -> TaskResult | None:
        """Return the original result for a repeated client message ID."""
        row = connection.execute(
            "SELECT id, task_id, conversation_id, text FROM messages WHERE client_message_id=?",
            (params.client_message_id,),
        ).fetchone()
        if row is None:
            return None
        if row["conversation_id"] != params.conversation_id or row["text"] != params.message:
            raise RequestConflict("client message ID already used with different content")
        return TaskResult(message_id=row["id"], task_id=row["task_id"])

    async def handle(self, params: RunParams) -> TaskResult:
        """Build a task from the target alone, without intent classification."""
        with self.database.transaction() as connection:
            duplicate = self._duplicate(connection, params)
            if duplicate:
                return duplicate
        return await self.run(self.factory.create(params))

    async def run(self, task: Task) -> TaskResult:
        """Commit the user turn, then delegate execution to a typed Runtime."""
        params = task.params
        with self.database.transaction() as connection:
            duplicate = self._duplicate(connection, params)
            if duplicate:
                return duplicate
            user_message = self.message_service.insert(
                connection, params.conversation_id, "user", "你",
                params.message, params.client_message_id)
        task.status = "running"
        try:
            if task.kind is TaskKind.AGENT_CHAT:
                response = await retry_operation(
                    lambda: self.agent.handle_conversation(task, self.database, self.message_service),
                    self.config["retry"]["task_retry"])
                task_id = response.task_id
                if task_id:
                    with self.database.transaction() as connection:
                        connection.execute("UPDATE messages SET task_id=? WHERE id=?",
                                           (task_id, user_message["id"]))
            elif task.kind in {TaskKind.GROUP_SWARM, TaskKind.GROUP_CONTROLLED}:
                await self.team.run(task)
                task_id = None
            else:
                raise ValueError(f"unsupported task kind: {task.kind}")
        except Exception as error:
            task.status = "failed"
            with self.database.transaction() as connection:
                self.message_service.insert(
                    connection, params.conversation_id, "system", "系统",
                    f"执行失败：{type(error).__name__}。消息已保存；请检查配置或稍后重试。")
            return TaskResult(message_id=user_message["id"], status="failed")
        task.status = "completed"
        return TaskResult(message_id=user_message["id"], task_id=task_id)
