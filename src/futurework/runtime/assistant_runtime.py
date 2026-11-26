"""Distinguish personal assistant conversation from delegated task requests."""

import httpx

from futurework.runtime.task_factory import Task


def assistant_profile(config: dict) -> dict:
    """Use XiaoWei's own model alias while retaining the assistant scope."""
    assistant = config["assistant"]
    return {"id": "assistant", "name": assistant["name"], "role": assistant["role"],
            "model": assistant["model"]["id"], "tools": assistant.get("tools", [])}


class AssistantRuntime:
    """Own XiaoWei's classification and delegated step execution."""

    def __init__(self, database, config: dict, message_service, agent_runtime) -> None:
        self.database = database
        self.config = config
        self.message_service = message_service
        self.agent_runtime = agent_runtime

    async def classify(self, text: str, history: list[dict]) -> str:
        """Return chat or task; bound the classifier to the assistant conversation."""
        lowered = text.casefold()
        routing = self.config["assistant_routing"]
        if (any(term.casefold() in lowered for term in routing["skill_terms"]) and
                any(term.casefold() in lowered for term in routing["skill_creation_terms"])):
            return "chat"
        instruction = (
            "判断用户最新消息是普通聊天还是希望你分派 Agent 完成交付任务。"
            "闲聊、问候、解释性问题返回 CHAT；需要产出、调查、设计、编码、整理或计划的请求返回 TASK。"
            "只输出 CHAT 或 TASK。\n用户消息：" + text
        )
        try:
            answer = await self.agent_runtime.respond(assistant_profile(self.config), history + [{"from": "me", "text": instruction}])
        except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError):
            task_words = ("请", "帮我", "设计", "编写", "整理", "分析", "计划", "调研", "开发", "创建")
            return "task" if any(word in text for word in task_words) else "chat"
        return "chat" if answer.strip().upper().startswith("CHAT") else "task"


    async def execute_assigned(self, run_task: Task) -> None:
        """Run assigned steps, persist each result, and return a summary to XiaoWei."""
        task_id = run_task.id
        with self.database.transaction() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task or task["status"] != "assigned":
                return
            run_task.status = "running"
            steps = [dict(row) for row in connection.execute("SELECT * FROM task_steps WHERE task_id=? ORDER BY rowid", (task_id,))]
            connection.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
            self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "running"})
        outputs = []
        for step in steps:
            agent = self.database.agent(step["agent_id"])
            if not agent or agent["version"] != step["agent_version"]:
                error_text = f"{step['title']} 未执行：Agent 配置已变化，请重新分派任务。"
                with self.database.transaction() as connection:
                    connection.execute("UPDATE task_steps SET status='failed' WHERE id=?", (step["id"],))
                    connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
                    self.message_service.insert(connection, "assistant", "agent", self.config["ui"]["assistant_name"], error_text, task_id=task_id)
                    self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "failed"})
                run_task.status = "failed"
                return
            with self.database.transaction() as connection:
                connection.execute("UPDATE task_steps SET status='running' WHERE id=?", (step["id"],))
                self.database.emit(connection, "task_step.updated", {"task_id": task_id, "step_id": step["id"], "status": "running"})
            prompt = f"{self.config['execution']['step_instruction']}\n总任务：{task['request']}\n你的子任务：{step['title']}"
            try:
                output = await self.agent_runtime.respond(agent, [{"from": "me", "text": prompt}])
            except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
                with self.database.transaction() as connection:
                    connection.execute("UPDATE task_steps SET status='failed' WHERE id=?", (step["id"],))
                    connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
                    self.message_service.insert(connection, "assistant", "agent", self.config["ui"]["assistant_name"],
                                   f"{step['title']} 执行失败：{type(error).__name__}。请检查模型配置后重试。", task_id=task_id)
                    self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "failed"})
                run_task.status = "failed"
                return
            outputs.append((agent["name"], step["title"], output))
            with self.database.transaction() as connection:
                connection.execute("UPDATE task_steps SET status='completed' WHERE id=?", (step["id"],))
                self.message_service.insert(connection, agent["id"], "agent", agent["name"], output, task_id=task_id)
                self.database.emit(connection, "task_step.updated", {"task_id": task_id, "step_id": step["id"], "status": "completed"})
        summary = "任务初稿已完成。\n" + "\n\n".join(f"【{title} · {name}】\n{output}" for name, title, output in outputs)
        with self.database.transaction() as connection:
            connection.execute("UPDATE tasks SET status='completed' WHERE id=?", (task_id,))
            self.message_service.insert(connection, "assistant", "agent", self.config["ui"]["assistant_name"], summary, task_id=task_id)
            self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "completed"})
        run_task.status = "completed"
