"""Run one Agent friend's direct conversation using only that conversation history."""

import httpx

from futurework.contexts.types import ScopeKey
from futurework.runtime.task_factory import Task


class DirectChatRuntime:
    """Own the Agent's private conversation and model dependency."""

    def __init__(self, database, config: dict, message_service, agent_runtime) -> None:
        self.database = database
        self.config = config
        self.message_service = message_service
        self.agent_runtime = agent_runtime

    async def run(self, task: Task) -> None:
        """Generate and persist a reply using only this Agent's history."""
        agent = task.params.target.record
        history = self.database.messages(agent["id"], self.config["server"]["message_history_limit"])
        try:
            reply = await self.agent_runtime.respond(agent, history, ScopeKey("agent", agent["id"]))
        except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            reply = f"模型暂时不可用：{type(error).__name__}。消息已保存，请稍后重试。"
        with self.database.transaction() as connection:
            self.message_service.insert(connection, agent["id"], "agent", agent["name"], reply)
