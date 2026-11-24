"""Execute a Team turn within the group's own persisted conversation scope."""

import httpx

from futurework.model import respond
from futurework.runtime.group_controlled import choose_members
from futurework.runtime.group_swarm import responders


async def run_group_reply(group: dict, text: str, database, config: dict, insert_message) -> None:
    """Run one bounded Swarm or XiaoWei-controlled group turn and save replies."""
    members = [database.agent(member_id) for member_id in group["members"]]
    history = database.messages(group["id"], config["server"]["message_history_limit"])
    group_settings = config["group_reply"].get(group["id"], {})
    group_limit = group_settings.get("max_responders_per_round", config["runtime"]["max_parallel_agents"])
    total_calls = group_settings.get("max_total_model_calls", config["runtime"]["max_model_calls"])
    reserved = 2 if group["mode"] == "controlled" else 0
    limit = max(1, min(group_limit, config["runtime"]["max_parallel_agents"], total_calls - reserved))
    if group["mode"] == "swarm":
        selected = responders(members, text, limit)
    else:
        try:
            selected = await choose_members(members, text, history, config, limit)
        except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError):
            selected = []
        if not selected:
            with database.transaction() as connection:
                insert_message(connection, group["id"], "system", "系统", "小未暂时无法完成群聊分派，请检查模型配置后重试。")
            return
        with database.transaction() as connection:
            insert_message(connection, group["id"], "agent", config["ui"]["assistant_name"],
                           "这条消息交给" + "、".join(member["name"] for member in selected) + "协作处理。")
    for member in selected:
        history = database.messages(group["id"], config["server"]["message_history_limit"])
        try:
            answer = await respond(member, history, config)
        except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            answer = f"模型暂时不可用：{type(error).__name__}。请检查配置后重试。"
        with database.transaction() as connection:
            insert_message(connection, group["id"], "agent", member["name"], answer)
    if group["mode"] == "controlled" and len(selected) > 1:
        assistant = config["assistant"]
        controller = {"id": "assistant", "name": assistant["name"], "role": assistant["role"],
                      "model": assistant["model"]["id"]}
        history = database.messages(group["id"], config["server"]["message_history_limit"])
        try:
            summary = await respond(controller, history + [{"from": "me", "text": "请仅根据本群成员刚才的回复，简要汇总已完成内容与待办。"}], config)
        except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError):
            return
        with database.transaction() as connection:
            insert_message(connection, group["id"], "agent", controller["name"], summary)
