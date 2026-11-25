"""Recover persisted delegated tasks after a service restart without replaying uncertain calls."""

from futurework.runtime.run_params import RunParams
from futurework.runtime.task_factory import Task, TaskKind


class TaskRecoveryWorker:
    """Resume never-started assignments and expose interrupted work as failed."""

    def __init__(self, database, config: dict, message_service, task_runtime) -> None:
        self.database = database
        self.config = config
        self.message_service = message_service
        self.task_runtime = task_runtime

    async def recover(self) -> None:
        """Run once on startup; a running step may already have performed side effects."""
        if self.config["model"]["provider"] == "mock":
            return
        with self.database.transaction() as connection:
            running = [dict(row) for row in connection.execute("SELECT id FROM tasks WHERE status='running'")]
            assigned = [dict(row) for row in connection.execute("SELECT id, request FROM tasks WHERE status='assigned'")]
            if self.config["worker"]["mark_interrupted_failed"]:
                for row in running:
                    connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (row["id"],))
                    connection.execute("UPDATE task_steps SET status='failed' WHERE task_id=? AND status='running'", (row["id"],))
                    self.message_service.insert(connection, "assistant", "system", "系统",
                                                "服务重启打断了任务执行。为避免重复执行可能已生效的工具，本任务已标记失败；请检查已有产物后重新发起。",
                                                task_id=row["id"])
                    self.database.emit(connection, "task.updated", {"task_id": row["id"], "status": "failed"})
        if not self.config["worker"]["recover_assigned_on_startup"]:
            return
        for row in assigned:
            params = RunParams.from_http({"id": "assistant", "kind": "assistant",
                                          "name": self.config["ui"]["assistant_name"]},
                                         row["request"], f"recovery:{row['id']}")
            task = Task(id=row["id"], kind=TaskKind.ASSISTANT_DELEGATION, params=params)
            await self.task_runtime.execute_assigned(task)
