"""Ask XiaoWei to select Team members using only the current group scope."""

import json

from futurework.model import respond


async def choose_members(members: list[dict], text: str, history: list[dict], config: dict, limit: int) -> list[dict]:
    """Resolve explicit mentions or use XiaoWei to produce a bounded member plan."""
    active = [member for member in members if member and member["status"] == "active"]
    if not active:
        return []
    mentioned = [member for member in active if f"@{member['name']}" in text]
    if mentioned:
        return mentioned[:limit]
    assistant = config["assistant"]
    controller = {"id": "assistant", "name": assistant["name"], "role": assistant["role"],
                  "model": assistant["model"]["id"]}
    roster = "；".join(f"{member['id']}={member['name']}（{member['role']}）" for member in active)
    prompt = (
        f"你正在本群担任中控。根据用户消息选择最多 {limit} 位成员：{text}\n候选：{roster}\n"
        '只返回 JSON，例如 {"agent_ids":["design","write"]}；只能使用候选 ID。'
    )
    selection = await respond(controller, history + [{"from": "me", "text": prompt}], config)
    try:
        selected_ids = json.loads(selection)["agent_ids"]
    except (ValueError, KeyError, TypeError):
        selected_ids = [selection.strip()]
    if not isinstance(selected_ids, list):
        selected_ids = []
    chosen = [member for member in active if member["id"] in selected_ids]
    return chosen[:limit] or active[:1]
