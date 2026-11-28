"""Select bounded Team members for Swarm replies without a central Agent."""

import httpx

from futurework.contexts.types import ScopeKey
from futurework.kinds import TEAM
from futurework.runtime.errors import retry_operation


class SwarmPolicy:
    """Select active group members without a central controller."""

    def responders(self, members: list[dict], text: str, limit: int) -> list[dict]:
        """Honor explicit mentions or let active members each take one turn."""
        active = [member for member in members if member and member["status"] == "active"]
        mentioned = [member for member in active if f"@{member['name']}" in text]
        return (mentioned or active)[:limit]


class SwarmRuntime:
    """Execute an independent, bounded reply loop for a Swarm group."""

    def __init__(self, database, config, message_service, agent_runtime) -> None:
        self.database, self.config = database, config
        self.message_service, self.agent_runtime = message_service, agent_runtime
        self.policy = SwarmPolicy()

    async def run(self, task) -> int:
        """Allow selected members to respond in sequence without a controller."""
        group = task.params.target.record
        settings = self.config["group_reply"].get(group["id"], {})
        limit = max(1, min(settings.get("max_responders_per_round", self.config["runtime"]["max_parallel_agents"]),
                           settings.get("max_total_model_calls", self.config["runtime"]["max_model_calls"])))
        members = [self.database.agent(member_id) for member_id in group["members"]]
        selected = self.policy.responders(members, task.params.message, limit)
        if not selected:
            raise RuntimeError("team has no active responders")
        completed = 0
        for member in selected:
            history = self.database.messages(group["id"], self.config["server"]["message_history_limit"])
            try:
                answer = await retry_operation(
                    lambda: self.agent_runtime.respond(member, history, ScopeKey(TEAM, group["id"])),
                    self.config["retry"]["team_retry"])
            except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
                answer = f"模型暂时不可用：{type(error).__name__}。请检查配置后重试。"
            else:
                completed += 1
            with self.database.transaction() as connection:
                self.message_service.insert(connection, group["id"], "agent", member["name"], answer)
        if not completed:
            raise RuntimeError("all team members failed")
        return completed
