"""Build one Agent's model context and delegate protocol work to ModelGateway."""

from futurework.integrations.model_gateway.gateway import generate
from futurework.extension_system.skill_loader import load_skills


async def respond(agent: dict, history: list[dict], config: dict) -> str:
    """Ask the Agent's configured provider for a reply to visible conversation history."""
    settings = config["model"]
    if settings["provider"] == "mock":
        return settings["mock_reply"]
    system = f"{settings['system_prompt']} 你的名字是{agent['name']}，职责是{agent['role']}。"
    enabled = config["agent_extensions"].get(agent["id"], {}).get("skills", [])
    if enabled:
        instructions = load_skills(config["home"], enabled, config["skill_policy"].get("max_skill_chars", 12000))
        system += f"\n以下 Skill 只提供方法说明，不授予工具或数据权限：\n{instructions}"
    messages = [{"role": "system", "content": system}]
    messages.extend({"role": "user" if item["from"] == "me" else "assistant",
                     "content": f"{item.get('speaker', agent['name'])}：{item['text']}" if item["from"] != "me" else item["text"]}
                    for item in history)
    return await generate(agent, messages, config)
