"""Ask XiaoWei to select Team members using only the current group scope."""

import json

class GroupController:
    """Use XiaoWei's model within one group's history to select members."""

    def __init__(self, config: dict, agent_runtime) -> None:
        self.config = config
        self.agent_runtime = agent_runtime

    def profile(self) -> dict:
        """Build XiaoWei's group controller identity from the loaded config."""
        assistant = self.config["assistant"]
        return {"id": "assistant", "name": assistant["name"], "role": assistant["role"],
                "model": assistant["model"]["id"]}

    async def choose_members(self, members: list[dict], text: str, history: list[dict], limit: int) -> list[dict]:
        """Resolve explicit mentions or request a bounded member selection."""
        active = [member for member in members if member and member["status"] == "active"]
        if not active:
            return []
        mentioned = [member for member in active if f"@{member['name']}" in text]
        if mentioned:
            return mentioned[:limit]
        roster = "；".join(f"{member['id']}={member['name']}（{member['role']}）" for member in active)
        prompt = (
            f"你正在本群担任中控。根据用户消息选择最多 {limit} 位成员：{text}\n候选：{roster}\n"
            '只返回 JSON，例如 {"agent_ids":["design","write"]}；只能使用候选 ID。'
        )
        selection = await self.agent_runtime.respond(self.profile(), history + [{"from": "me", "text": prompt}])
        try:
            selected_ids = json.loads(selection)["agent_ids"]
        except (ValueError, KeyError, TypeError):
            selected_ids = [selection.strip()]
        if not isinstance(selected_ids, list):
            selected_ids = []
        chosen = [member for member in active if member["id"] in selected_ids]
        return chosen[:limit] or active[:1]
