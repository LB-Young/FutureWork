"""Recover persisted delegated tasks after a service restart without replaying uncertain calls."""



class TaskRecoveryWorker:
    """Mark legacy unfinished assignments uncertain instead of replaying side effects."""

    def __init__(self, database, config: dict, message_service, task_runtime) -> None:
        self.database = database
        self.config = config
        self.message_service = message_service
        self.task_runtime = task_runtime

    async def recover(self) -> None:
        """Run once on startup; old queued and running steps may have side effects."""
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
        for row in assigned:
            with self.database.transaction() as connection:
                connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (row["id"],))
                self.message_service.insert(connection, "assistant", "system", "系统",
                                            "旧版本分派任务未确认执行状态，已停止自动重放；请检查产物后重新发起。",
                                            task_id=row["id"])
                self.database.emit(connection, "task.updated", {"task_id": row["id"], "status": "failed"})
