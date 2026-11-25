"""Verify restart recovery distinguishes safe queued work from interrupted execution."""

import asyncio

from futurework.api.app import create_app
from futurework.database import utc_now
from futurework.services.message_service import MessageService
from futurework.workers.task_worker import TaskRecoveryWorker


def test_recovery_does_not_replay_running_steps(tmp_path):
    """An assigned task resumes; a running task is failed to avoid duplicate effects."""
    app = create_app(tmp_path)
    database = app.state.database
    config = app.state.config
    config["model"]["provider"] = "registry"
    with database.transaction() as connection:
        connection.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?)",
                           ("queued", "assistant", "测试任务", "assigned", utc_now()))
        connection.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?)",
                           ("in_progress", "assistant", "另一个任务", "running", utc_now()))
    class RecordingRuntime:
        def __init__(self):
            self.ids = []
        async def execute_assigned(self, task):
            self.ids.append(task.id)
    runtime = RecordingRuntime()
    worker = TaskRecoveryWorker(database, config, MessageService(database), runtime)
    asyncio.run(worker.recover())
    assert runtime.ids == ["queued"]
    with database.transaction() as connection:
        status = connection.execute("SELECT status FROM tasks WHERE id='in_progress'").fetchone()["status"]
    assert status == "failed"
