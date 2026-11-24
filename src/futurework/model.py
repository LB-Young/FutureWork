"""Build one Agent's model context and delegate protocol work to ModelGateway."""

import json

from futurework.integrations.model_gateway.gateway import generate
from futurework.integrations.model_gateway.types import ModelRequest
from futurework.extension_system.skill_loader import load_skills
from futurework.runtime.tool_dispatch import ToolRequest, execute, schemas_for
from futurework.runtime.run_spec import AgentRun


async def respond(agent: dict, history: list[dict], config: dict) -> str:
    """Build an AgentRun object at the API/database boundary and execute it."""
    return await execute_run(AgentRun.from_records(agent, history, config))


async def execute_run(run: AgentRun) -> str:
    """Ask the configured provider using only this run's scoped data and grants."""
    config = run.config
    settings = config["model"]
    if settings["provider"] == "mock":
        return settings["mock_reply"]
    system = f"{settings['system_prompt']} 你的名字是{run.name}，职责是{run.role}。"
    enabled = config["agent_extensions"].get(run.agent_id, {}).get("skills", [])
    if enabled:
        instructions = load_skills(config["home"], enabled, config["skill_policy"].get("max_skill_chars", 12000))
        system += f"\n以下 Skill 只提供方法说明，不授予工具或数据权限：\n{instructions}"
    messages = [{"role": "system", "content": system}]
    messages.extend({"role": "user" if item["from"] == "me" else "assistant",
                     "content": f"{item.get('speaker', run.name)}：{item['text']}" if item["from"] != "me" else item["text"]}
                    for item in run.history)
    grants = list(run.tools)
    tools = schemas_for(grants)
    alias = run.model_alias
    if not config["models"]["models"][alias].get("supports_tools", True):
        tools = []
    for _ in range(config["tool_runtime"]["max_rounds"] + 1):
        result = await generate(ModelRequest(alias=alias, messages=messages, tools=tools), config)
        if not result.tool_calls:
            return result.text
        if not tools or len(result.tool_calls) > config["tool_runtime"]["max_calls_per_round"]:
            raise RuntimeError("模型工具调用超出权限或限额")
        messages.append({"role": "assistant", "content": result.text,
                         "tool_calls": [{"id": call.id, "type": "function", "function": {"name": call.name,
                                         "arguments": json.dumps(call.arguments)}} for call in result.tool_calls]})
        for call in result.tool_calls:
            output = execute(ToolRequest(agent_id=run.agent_id, name=call.name, arguments=call.arguments), grants, config)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output.content})
    raise RuntimeError("模型工具调用超过最大轮数")
