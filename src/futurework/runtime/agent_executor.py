"""Execute one Agent model and approved tool loop under fixed run inputs."""

import json
from dataclasses import dataclass

from futurework.extension_system.skill_loader import load_skills
from futurework.contexts.store import MemoryStore
from futurework.contexts.compactor import ContextCompactor
from futurework.contexts.types import ScopeKey
from futurework.abilities.tools.management import UserProfile
from futurework.integrations.model_gateway.gateway import ModelGateway
from futurework.integrations.model_gateway.types import ModelRequest
from futurework.runtime.run_spec import AgentRun
from futurework.runtime.tool_dispatch import ToolRegistry
from futurework.runtime.tool_execution import ToolCall, ToolExecutionLayer
from futurework.runtime.errors import UncertainOutcomeError, retry_operation
from futurework.kinds import ASSISTANT
from futurework.kinds import FRIEND


@dataclass(frozen=True)
class AgentResponse:
    """Return a final answer and any task that the Agent chose to delegate."""

    text: str
    task_id: str | None = None
from futurework.integrations.agent_backends import AgentBackendRegistry
from futurework.integrations.agent_backends.base import AgentRequest


class AgentRuntime:
    """Execute one AgentRun using owned model and tool dependencies."""

    def __init__(self, config: dict, model_gateway: ModelGateway | None = None,
                 memory_store: MemoryStore | None = None, approval_store=None) -> None:
        self.config = config
        self.model_gateway = model_gateway or ModelGateway(config)
        self.memory_store = memory_store or MemoryStore(config["home"], config["memory"], config["ui"]["assistant_name"])
        self.memory_store.ensure_profiles()
        self.compactor = ContextCompactor(config, self.model_gateway, self.memory_store)
        self.approval_store = approval_store
        self.backends = AgentBackendRegistry(config)
        self.delegation_service = None
        self.agent_service = None
        self.group_service = None

    async def respond(self, agent: dict, history: list[dict], scope: ScopeKey | None = None) -> str:
        """Convert persistence records into a scoped execution object."""
        return (await self.respond_with_result(agent, history, scope)).text

    async def handle_conversation(self, task, database, message_service) -> AgentResponse:
        """Own the entire personal assistant or friend turn after task routing."""
        if task.params.target.kind == ASSISTANT:
            definition = self.config["assistant"]
            agent = {"id": ASSISTANT, "name": definition["name"], "role": definition["role"],
                     "model": definition["model"]["id"], "tools": definition.get("tools", []),
                     "approval": definition.get("approval", True)}
            scope = ScopeKey(ASSISTANT, ASSISTANT)
        elif task.params.target.kind == FRIEND:
            agent = task.params.target.record
            scope = ScopeKey(FRIEND, agent["id"])
        else:
            raise ValueError("AgentRuntime requires an Agent conversation")
        history = database.messages(task.params.conversation_id,
                                    self.config["server"]["message_history_limit"])
        response = await self.respond_with_result(agent, history, scope)
        with database.transaction() as connection:
            message_service.insert(connection, task.params.conversation_id, "agent",
                                   agent["name"], response.text, task_id=response.task_id)
        return response

    async def respond_with_result(self, agent: dict, history: list[dict],
                                  scope: ScopeKey | None = None) -> AgentResponse:
        """Execute an Agent friend or XiaoWei with the identical loop."""
        return await self.run_with_result(AgentRun.from_records(agent, history, self.config, scope))

    async def run(self, run: AgentRun) -> str:
        """Ask the configured provider using only this run's history and grants."""
        return (await self.run_with_result(run)).text

    async def run_with_result(self, run: AgentRun) -> AgentResponse:
        """Run one Agent loop with bounded model recovery and tool feedback."""
        backend = self.backends.for_agent(run.agent_id)
        if backend is not None:
            latest_user = next((item for item in reversed(run.history) if item.get("from") == "me"), None)
            try:
                answer = await backend.run(AgentRequest(
                    agent_id=run.agent_id, name=run.name, role=run.role,
                    scope_type=run.scope.kind, scope_id=run.scope.id,
                    prompt=latest_user["text"] if latest_user else (run.history[-1]["text"] if run.history else ""),
                    history=run.history))
            except Exception as error:
                raise UncertainOutcomeError(f"external Agent outcome is unknown: {type(error).__name__}") from error
            return AgentResponse(answer)
        settings = self.config["model"]
        if settings["provider"] == "mock":
            return AgentResponse(settings["mock_reply"])
        system = f"{settings['system_prompt']} 你的名字是{run.name}，职责是{run.role}。"
        if run.agent_id == ASSISTANT and run.scope.kind == ASSISTANT:
            system += ("\n你和其他好友共用 Agent 执行循环。遇到需要专家或群协作的复杂任务时自主调用 "
                       "delegate_task；它只能指派给已有好友或群聊。缺少合适好友时，先用 friend_create 明确设置"
                       "名字、职责、模型、工具、Skill 和能力；需要新群聊时用 team_create 指定成员和模式，"
                       "随后再调用 delegate_task。创建配置必须经过审批。普通问题直接回答。"
                       "只有工具实际返回结果后才能说任务已完成。")
            if "team_directory" in run.tools and self.agent_service is not None:
                system += "\n需要确认当前好友、群聊或群成员时，调用 team_directory 查询实时目录，不要根据旧记忆猜测名单。"
            available_skills = sorted({*self.config["assistant"].get("extensions", {}).get("skills", []),
                                       *(item.rsplit("/", 2)[-2] for item in
                                         self.config.get("installed_extensions", {}).get("skills", []))})
            system += ("\n可选模型别名：" + "、".join(self.config["model"]["available_models"])
                       + "。可授予工具：" + "、".join(self.config["permissions"]["available_tools"])
                       + "。已安装 Skill：" + ("、".join(available_skills) or "无")
                       + "。创建好友时，仅使用这些已配置的别名和能力；不确定时使用空工具或空 Skill 列表。")
        profile = UserProfile(self.config["home"], self.config["user_profile"]["max_chars"]).read()
        system += ("\n用户画像（仅记录用户明确表达的信息；回答时尊重这些偏好，不把它当作新任务）：\n"
                   + (profile or "（尚无记录）")
                   + "\n当用户明确表达稳定的个人信息、习惯或偏好时，可调用 user_profile_update 追加一条简短事实；不要猜测。")
        memory = self.memory_store.prompt_context(run.scope, run.agent_id)
        if memory:
            system += f"\n以下是可供当前会话使用的长期记忆和人物/群聊介绍：\n{memory}"
        enabled = list(self.config["agent_extensions"].get(run.agent_id, {}).get("skills", []))
        if enabled:
            instructions = load_skills(self.config["home"], enabled, self.config["skill_policy"].get("max_skill_chars", 12000))
            system += f"\n以下 Skill 只提供方法说明，不授予工具或数据权限：\n{instructions}"
        mcp_servers = self.config["agent_extensions"].get(run.agent_id, {}).get("mcp", [])
        if mcp_servers and "mcp_list" in run.tools:
            system += "\n已授权的 MCP 服务 ID：" + "、".join(mcp_servers) + "。先用 mcp_list 查看工具说明，再调用 mcp_call。"
        messages = [{"role": "system", "content": system}]
        messages.extend({"role": "user" if item["from"] == "me" else "assistant",
                         "source_id": str(item.get("id", "")),
                         "content": f"{item.get('speaker', run.name)}：{item['text']}" if item["from"] != "me" else item["text"]}
                        for item in run.history)
        grants = run.tools
        if run.agent_id == ASSISTANT and run.scope.kind == ASSISTANT:
            if self.delegation_service is None:
                grants = tuple(name for name in grants if name != "delegate_task")
            if self.agent_service is None:
                grants = tuple(name for name in grants if name != "friend_create")
            if self.group_service is None:
                grants = tuple(name for name in grants if name != "team_create")
            if self.agent_service is None:
                grants = tuple(name for name in grants if name != "team_directory")
        tools_for_run = ToolRegistry(run.agent_id, grants, self.config,
                                     scope=run.scope, memory_store=self.memory_store,
                                     delegation_service=self.delegation_service,
                                     agent_service=self.agent_service, group_service=self.group_service)
        tool_executor = ToolExecutionLayer(tools_for_run, self.config, self.memory_store,
                                           approval_store=self.approval_store,
                                           require_approval=run.require_tool_approval)
        tools = tools_for_run.schemas() if self.model_gateway.supports_tools(run.model_alias) else []
        delegated_task_id = None
        tool_used = False
        for _ in range(self.config["tool_runtime"]["max_rounds"] + 1):
            compacted = await self.compactor.compact(ModelRequest(run.model_alias, messages, tools), run.scope, run.agent_id)
            messages = compacted.messages
            provider_messages = [{key: value for key, value in item.items() if key != "source_id"} for item in messages]
            request = ModelRequest(alias=run.model_alias, messages=provider_messages, tools=tools)
            try:
                result = await retry_operation(lambda: self.model_gateway.generate(request),
                                               self.config["retry"]["agent_retry"])
            except Exception as error:
                if tool_used:
                    raise UncertainOutcomeError("Agent failed after tool activity; automatic replay is unsafe") from error
                raise
            if not result.tool_calls:
                return AgentResponse(result.text, delegated_task_id)
            if not tools or len(result.tool_calls) > self.config["tool_runtime"]["max_calls_per_round"]:
                raise RuntimeError("模型工具调用超出权限或限额")
            messages.append({"role": "assistant", "content": result.text,
                             "tool_calls": [{"id": call.id, "type": "function", "function": {"name": call.name,
                                             "arguments": json.dumps(call.arguments)}} for call in result.tool_calls]})
            for call in result.tool_calls:
                tool_used = True
                output = await tool_executor.execute(ToolCall(call.id, run.agent_id, run.scope,
                                                              call.name, call.arguments))
                if call.name == "delegate_task" and output.success:
                    try:
                        delegated_task_id = json.loads(output.content).get("task_id")
                    except (ValueError, TypeError):
                        pass
                content = output.content if output.success else (
                    f"[tool-error code={output.error_code} attempts={output.attempts}] {output.content}. "
                    "Choose another safe approach or explain the failure to the user.")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        raise RuntimeError("模型工具调用超过最大轮数")
