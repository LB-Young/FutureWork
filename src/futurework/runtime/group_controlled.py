"""Run a controlled Team with XiaoWei deciding after every member reply."""

import json

import httpx

from futurework.contexts.types import ScopeKey
from futurework.kinds import ASSISTANT, TEAM
from futurework.runtime.errors import retry_operation


class GroupController:
    """Ask XiaoWei for the next group action using current group history."""

    def __init__(self, config: dict, agent_runtime) -> None:
        self.config = config
        self.agent_runtime = agent_runtime

    def profile(self) -> dict:
        """Use the current XiaoWei model and identity for group control."""
        assistant = self.config["assistant"]
        return {"id": ASSISTANT, "name": assistant["name"], "role": assistant["role"],
                "model": assistant["model"]["id"]}

    async def next_member(self, members: list[dict], text: str, history: list[dict], group_id: str) -> dict | None:
        """Return one chosen member, or None when XiaoWei decides to finish."""
        active = [member for member in members if member and member["status"] == "active"]
        if not active:
            return None
        roster = "；".join(f"{member['id']}={member['name']}（{member['role']}）" for member in active)
        prompt = (f"你是本群中控小未。原始任务：{text}\n可继续指派：{roster}\n"
                  '阅读最新群聊记录，决定下一步。只返回 JSON：'
                  '{"action":"delegate","agent_id":"候选ID"} 或 {"action":"finish"}。'
                  '每次只指派一位成员；成员完成后你会再次决策。')
        answer = await self.agent_runtime.respond(
            self.profile(), history + [{"from": "me", "text": prompt}], ScopeKey(TEAM, group_id))
        try:
            decision = json.loads(answer)
        except (ValueError, TypeError) as error:
            raise ValueError("controller returned invalid JSON") from error
        if decision.get("action") == "finish":
            return None
        member_id = decision.get("agent_id")
        if member_id is None and isinstance(decision.get("agent_ids"), list):
            member_id = next((item for item in decision["agent_ids"]
                              if any(member["id"] == item for member in active)), None)
        if decision.get("action", "delegate") != "delegate" or not isinstance(member_id, str):
            raise ValueError("controller returned invalid action")
        return next((member for member in active if member["id"] == member_id), None)


class ControlledRuntime:
    """Keep XiaoWei in the loop until completion or the configured budget is spent."""

    def __init__(self, database, config, message_service, agent_runtime) -> None:
        self.database, self.config = database, config
        self.message_service, self.agent_runtime = message_service, agent_runtime
        self.controller = GroupController(config, agent_runtime)

    async def run(self, task) -> int:
        """Select, execute, reassess and finally report within one group scope."""
        group = task.params.target.record
        group_id = group["id"]
        scope = ScopeKey(TEAM, group_id)
        settings = self.config["group_reply"].get(group_id, {})
        max_rounds = settings.get("max_rounds", self.config["runtime"]["max_parallel_agents"])
        max_members = settings.get("max_responders_per_round", self.config["runtime"]["max_parallel_agents"])
        max_calls = settings.get("max_total_model_calls", self.config["runtime"]["max_model_calls"])
        if max_calls < 3:
            raise RuntimeError("controlled team needs at least three model calls")
        members = [self.database.agent(member_id) for member_id in group["members"]]
        completed = 0
        calls = 0
        attempted = set()
        while completed < max_rounds and completed < max_members and calls + 2 < max_calls:
            history = self.database.messages(group_id, self.config["server"]["message_history_limit"])
            available = [member for member in members if member and member["id"] not in attempted]
            if not available:
                break
            try:
                chosen = await retry_operation(
                    lambda: self.controller.next_member(available, task.params.message, history, group_id),
                    self.config["retry"]["team_retry"])
            except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
                if completed:
                    break
                raise RuntimeError("team controller could not select a member") from error
            calls += 1
            if chosen is None:
                break
            attempted.add(chosen["id"])
            with self.database.transaction() as connection:
                self.message_service.insert(connection, group_id, "agent", self.controller.profile()["name"],
                                            f"请{chosen['name']}接着处理：{task.params.message}")
            history = self.database.messages(group_id, self.config["server"]["message_history_limit"])
            try:
                answer = await retry_operation(
                    lambda: self.agent_runtime.respond(chosen, history, scope),
                    self.config["retry"]["team_retry"])
            except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
                answer = f"模型暂时不可用：{type(error).__name__}。请检查配置后重试。"
            else:
                completed += 1
            calls += 1
            with self.database.transaction() as connection:
                self.message_service.insert(connection, group_id, "agent", chosen["name"], answer)
        if not completed:
            raise RuntimeError("all team members failed or controller finished without delegation")
        history = self.database.messages(group_id, self.config["server"]["message_history_limit"])
        summary = await retry_operation(
            lambda: self.agent_runtime.respond(
                self.controller.profile(), history + [{"from": "me", "text": "请以小未身份向用户汇报本轮群聊的处理结果、未完成事项和下一步。仅依据群内实际回复。"}], scope),
            self.config["retry"]["team_retry"])
        with self.database.transaction() as connection:
            self.message_service.insert(connection, group_id, "agent", self.controller.profile()["name"], summary)
        return completed
