"""Execute one Agent model and approved tool loop under fixed run inputs."""

import json

from futurework.extension_system.skill_loader import load_skills
from futurework.contexts.store import MemoryStore
from futurework.contexts.compactor import ContextCompactor
from futurework.contexts.types import ScopeKey
from futurework.integrations.model_gateway.gateway import ModelGateway
from futurework.integrations.model_gateway.types import ModelRequest
from futurework.runtime.run_spec import AgentRun
from futurework.runtime.tool_dispatch import ToolRegistry


class AgentRuntime:
    """Execute one AgentRun using owned model and tool dependencies."""

    def __init__(self, config: dict, model_gateway: ModelGateway | None = None,
                 memory_store: MemoryStore | None = None) -> None:
        self.config = config
        self.model_gateway = model_gateway or ModelGateway(config)
        self.memory_store = memory_store or MemoryStore(config["home"], config["memory"], config["ui"]["assistant_name"])
        self.memory_store.ensure_profiles()
        self.compactor = ContextCompactor(config, self.model_gateway, self.memory_store)

    async def respond(self, agent: dict, history: list[dict], scope: ScopeKey | None = None) -> str:
        """Convert persistence records into a scoped execution object."""
        return await self.run(AgentRun.from_records(agent, history, self.config, scope))

    async def run(self, run: AgentRun) -> str:
        """Ask the configured provider using only this run's history and grants."""
        settings = self.config["model"]
        if settings["provider"] == "mock":
            return settings["mock_reply"]
        system = f"{settings['system_prompt']} 你的名字是{run.name}，职责是{run.role}。"
        memory = self.memory_store.prompt_context(run.scope, run.agent_id)
        if memory:
            system += f"\n以下是可供当前会话使用的长期记忆和人物/群聊介绍：\n{memory}"
        enabled = self.config["agent_extensions"].get(run.agent_id, {}).get("skills", [])
        if enabled:
            instructions = load_skills(self.config["home"], enabled, self.config["skill_policy"].get("max_skill_chars", 12000))
            system += f"\n以下 Skill 只提供方法说明，不授予工具或数据权限：\n{instructions}"
        messages = [{"role": "system", "content": system}]
        messages.extend({"role": "user" if item["from"] == "me" else "assistant",
                         "source_id": str(item.get("id", "")),
                         "content": f"{item.get('speaker', run.name)}：{item['text']}" if item["from"] != "me" else item["text"]}
                        for item in run.history)
        tools_for_run = ToolRegistry(run.agent_id, run.tools, self.config,
                                     scope=run.scope, memory_store=self.memory_store)
        tools = tools_for_run.schemas() if self.model_gateway.supports_tools(run.model_alias) else []
        for _ in range(self.config["tool_runtime"]["max_rounds"] + 1):
            compacted = await self.compactor.compact(ModelRequest(run.model_alias, messages, tools), run.scope, run.agent_id)
            messages = compacted.messages
            provider_messages = [{key: value for key, value in item.items() if key != "source_id"} for item in messages]
            result = await self.model_gateway.generate(ModelRequest(alias=run.model_alias, messages=provider_messages, tools=tools))
            if not result.tool_calls:
                return result.text
            if not tools or len(result.tool_calls) > self.config["tool_runtime"]["max_calls_per_round"]:
                raise RuntimeError("模型工具调用超出权限或限额")
            messages.append({"role": "assistant", "content": result.text,
                             "tool_calls": [{"id": call.id, "type": "function", "function": {"name": call.name,
                                             "arguments": json.dumps(call.arguments)}} for call in result.tool_calls]})
            for call in result.tool_calls:
                output = await tools_for_run.execute(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": output.content})
        raise RuntimeError("模型工具调用超过最大轮数")
