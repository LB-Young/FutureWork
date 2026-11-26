"""Execute a Team turn within the group's own persisted conversation scope."""

import httpx

from futurework.contexts.types import ScopeKey
from futurework.runtime.group_controlled import GroupController
from futurework.runtime.group_swarm import SwarmPolicy
from futurework.runtime.task_factory import Task, TaskKind
from futurework.runtime.errors import retry_operation
from futurework.kinds import TEAM


class TeamRuntime:
    """Own group history, member execution, and the selected group policy."""

    def __init__(self, database, config: dict, message_service, agent_runtime) -> None:
        self.database = database
        self.config = config
        self.message_service = message_service
        self.agent_runtime = agent_runtime
        self.swarm = SwarmPolicy()
        self.controller = GroupController(config, agent_runtime)

    async def run(self, task: Task) -> int:
        """Run one bounded Swarm or XiaoWei-controlled group turn."""
        group = task.params.target.record
        scope = ScopeKey(TEAM, group["id"])
        text = task.params.message
        members = [self.database.agent(member_id) for member_id in group["members"]]
        history = self.database.messages(group["id"], self.config["server"]["message_history_limit"])
        group_settings = self.config["group_reply"].get(group["id"], {})
        group_limit = group_settings.get("max_responders_per_round", self.config["runtime"]["max_parallel_agents"])
        total_calls = group_settings.get("max_total_model_calls", self.config["runtime"]["max_model_calls"])
        controlled = task.kind is TaskKind.GROUP_CONTROLLED
        reserved = 2 if controlled else 0
        limit = max(1, min(group_limit, self.config["runtime"]["max_parallel_agents"], total_calls - reserved))
        if task.kind is TaskKind.GROUP_SWARM:
            selected = self.swarm.responders(members, text, limit)
        elif controlled:
            try:
                selected = await retry_operation(
                    lambda: self.controller.choose_members(members, text, history, limit, group["id"]),
                    self.config["retry"]["team_retry"])
            except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError):
                selected = []
            if not selected:
                with self.database.transaction() as connection:
                    self.message_service.insert(connection, group["id"], "system", "系统", "小未暂时无法完成群聊分派，请检查模型配置后重试。")
                raise RuntimeError("team controller could not select a member")
            with self.database.transaction() as connection:
                self.message_service.insert(connection, group["id"], "agent", self.config["ui"]["assistant_name"],
                               "这条消息交给" + "、".join(member["name"] for member in selected) + "协作处理。")
        else:
            raise ValueError(f"Unsupported group task kind: {task.kind}")
        if not selected:
            raise RuntimeError("team has no active responders")
        completed = 0
        for member in selected:
            history = self.database.messages(group["id"], self.config["server"]["message_history_limit"])
            try:
                answer = await retry_operation(
                    lambda: self.agent_runtime.respond(member, history, scope),
                    self.config["retry"]["team_retry"])
            except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
                answer = f"模型暂时不可用：{type(error).__name__}。请检查配置后重试。"
            else:
                completed += 1
            with self.database.transaction() as connection:
                self.message_service.insert(connection, group["id"], "agent", member["name"], answer)
        if not completed:
            raise RuntimeError("all team members failed")
        if controlled and len(selected) > 1:
            controller = self.controller.profile()
            history = self.database.messages(group["id"], self.config["server"]["message_history_limit"])
            try:
                summary = await retry_operation(
                    lambda: self.agent_runtime.respond(controller, history + [{"from": "me", "text": "请仅根据本群成员刚才的回复，简要汇总已完成内容与待办。"}], scope),
                    self.config["retry"]["team_retry"])
            except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError):
                return completed
            with self.database.transaction() as connection:
                self.message_service.insert(connection, group["id"], "agent", controller["name"], summary)
        return completed
