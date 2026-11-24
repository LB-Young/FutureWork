"""Run one Agent friend's direct conversation using only that conversation history."""

import httpx


async def run_direct_reply(agent: dict, database, config: dict, insert_message, model_respond) -> None:
    """Generate and persist an Agent reply without reading another conversation."""
    history = database.messages(agent["id"], config["server"]["message_history_limit"])
    try:
        reply = await model_respond(agent, history, config)
    except (RuntimeError, httpx.HTTPError, KeyError, IndexError, ValueError) as error:
        reply = f"模型暂时不可用：{type(error).__name__}。消息已保存，请稍后重试。"
    with database.transaction() as connection:
        insert_message(connection, agent["id"], "agent", agent["name"], reply)
