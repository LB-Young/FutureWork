"""Distinguish personal assistant conversation from delegated task requests."""

import httpx

from futurework.model import respond


def assistant_profile(config: dict) -> dict:
    """Use XiaoWei's own model alias while retaining the assistant scope."""
    assistant = config["assistant"]
    return {"id": "assistant", "name": assistant["name"], "role": assistant["role"],
            "model": assistant["model"]["id"], "tools": assistant.get("tools", [])}


async def classify_message(text: str, history: list[dict], config: dict) -> str:
    """Return chat or task; bound the classifier to the assistant conversation."""
    instruction = (
        "判断用户最新消息是普通聊天还是希望你分派 Agent 完成交付任务。"
        "闲聊、问候、解释性问题返回 CHAT；需要产出、调查、设计、编码、整理或计划的请求返回 TASK。"
        "只输出 CHAT 或 TASK。\n用户消息：" + text
    )
    try:
        answer = await respond(assistant_profile(config), history + [{"from": "me", "text": instruction}], config)
    except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError):
        task_words = ("请", "帮我", "设计", "编写", "整理", "分析", "计划", "调研", "开发", "创建")
        return "task" if any(word in text for word in task_words) else "chat"
    return "chat" if answer.strip().upper().startswith("CHAT") else "task"


async def execute_assigned_task(task_id: str, database, config: dict, insert_message, model_respond) -> None:
    """Run assigned steps, persist each result, and return a summary to XiaoWei."""
    with database.transaction() as connection:
        task = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task or task["status"] != "assigned":
            return
        steps = [dict(row) for row in connection.execute("SELECT * FROM task_steps WHERE task_id=? ORDER BY rowid", (task_id,))]
        connection.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
        database.emit(connection, "task.updated", {"task_id": task_id, "status": "running"})
    outputs = []
    for step in steps:
        agent = database.agent(step["agent_id"])
        if not agent or agent["version"] != step["agent_version"]:
            error_text = f"{step['title']} 未执行：Agent 配置已变化，请重新分派任务。"
            with database.transaction() as connection:
                connection.execute("UPDATE task_steps SET status='failed' WHERE id=?", (step["id"],))
                connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
                insert_message(connection, "assistant", "agent", config["ui"]["assistant_name"], error_text, task_id=task_id)
                database.emit(connection, "task.updated", {"task_id": task_id, "status": "failed"})
            return
        with database.transaction() as connection:
            connection.execute("UPDATE task_steps SET status='running' WHERE id=?", (step["id"],))
            database.emit(connection, "task_step.updated", {"task_id": task_id, "step_id": step["id"], "status": "running"})
        prompt = f"{config['execution']['step_instruction']}\n总任务：{task['request']}\n你的子任务：{step['title']}"
        try:
            output = await model_respond(agent, [{"from": "me", "text": prompt}], config)
        except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            with database.transaction() as connection:
                connection.execute("UPDATE task_steps SET status='failed' WHERE id=?", (step["id"],))
                connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
                insert_message(connection, "assistant", "agent", config["ui"]["assistant_name"],
                               f"{step['title']} 执行失败：{type(error).__name__}。请检查模型配置后重试。", task_id=task_id)
                database.emit(connection, "task.updated", {"task_id": task_id, "status": "failed"})
            return
        outputs.append((agent["name"], step["title"], output))
        with database.transaction() as connection:
            connection.execute("UPDATE task_steps SET status='completed' WHERE id=?", (step["id"],))
            insert_message(connection, agent["id"], "agent", agent["name"], output, task_id=task_id)
            database.emit(connection, "task_step.updated", {"task_id": task_id, "step_id": step["id"], "status": "completed"})
    summary = "任务初稿已完成。\n" + "\n\n".join(f"【{title} · {name}】\n{output}" for name, title, output in outputs)
    with database.transaction() as connection:
        connection.execute("UPDATE tasks SET status='completed' WHERE id=?", (task_id,))
        insert_message(connection, "assistant", "agent", config["ui"]["assistant_name"], summary, task_id=task_id)
        database.emit(connection, "task.updated", {"task_id": task_id, "status": "completed"})
