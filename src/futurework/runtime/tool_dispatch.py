"""Authorize tool calls and dispatch them to per-tool ability handlers."""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from typing import Any

import httpx

from futurework.abilities.tools.bash import handler as bash_handler
from futurework.abilities.tools.delegate_task import handler as delegate_handler
from futurework.abilities.tools.friend_create import handler as friend_create_handler
from futurework.abilities.tools.team_create import handler as team_create_handler
from futurework.abilities.tools.calculator import handler as calculator_handler
from futurework.abilities.tools.edit import handler as edit_handler
from futurework.abilities.tools.glob import handler as glob_handler
from futurework.abilities.tools.grep import handler as grep_handler
from futurework.abilities.tools.memory_search import handler as memory_handler
from futurework.abilities.tools.media_generate import handler as media_handler
from futurework.abilities.tools.image_analyze import handler as image_handler
from futurework.abilities.tools.video_analyze import handler as video_analyze_handler
from futurework.abilities.tools.video_edit import handler as video_edit_handler
from futurework.abilities.tools.plan_check import handler as plan_check_handler
from futurework.abilities.tools.plan_update import handler as plan_update_handler
from futurework.abilities.tools.read import handler as read_handler
from futurework.abilities.tools.schedule_create import handler as schedule_create_handler
from futurework.abilities.tools.schedule_list import handler as schedule_list_handler
from futurework.abilities.tools.skill_load import handler as skill_handler
from futurework.abilities.tools.skill_create import handler as skill_create_handler
from futurework.abilities.tools.url_to_md import handler as url_to_md_handler
from futurework.abilities.tools.user_profile_update import handler as profile_handler
from futurework.abilities.tools.web_fetch import handler as web_fetch_handler
from futurework.abilities.tools.write import handler as write_handler
from futurework.contexts.retrieval import MemoryRetriever
from futurework.contexts.store import MemoryStore
from futurework.contexts.types import ScopeKey
from futurework.extension_system.mcp_client import MCPClient
from futurework.kinds import ASSISTANT, FRIEND, TEAM, DELEGATION_AUTO


SCHEMAS = {
    "delegate_task": ("Assign a complex task to a capable Agent friend or team; XiaoWei only. "
                      "Only select existing friends or teams. If no friend matches, use friend_create first, "
                      "then call delegate_task again. Summarize only actual results.",
                      {"request": {"type": "string"},
                       "target_kind": {"type": "string", "enum": [DELEGATION_AUTO, FRIEND, TEAM]},
                       "target_id": {"type": "string"}}, ["request"]),
    "friend_create": ("Create an Agent friend with a name, role, model alias, permitted tools, enabled Skills and capabilities; XiaoWei only. Requires approval.",
                      {"name": {"type": "string"}, "role": {"type": "string"},
                       "model": {"type": "string"},
                       "tools": {"type": "array", "items": {"type": "string"}},
                       "skills": {"type": "array", "items": {"type": "string"}},
                       "capabilities": {"type": "object"}}, ["name", "role", "model", "tools", "skills"]),
    "team_create": ("Create a Team from existing friend IDs in controlled or swarm mode; XiaoWei only. Requires approval.",
                    {"name": {"type": "string"},
                     "member_ids": {"type": "array", "items": {"type": "string"}},
                     "mode": {"type": "string", "enum": ["controlled", "swarm"]}},
                    ["name", "member_ids", "mode"]),
    "skill_create": ("Create a reusable Skill in the user's abilities directory; requires approval.",
                     {"name": {"type": "string"}, "description": {"type": "string"},
                      "instructions": {"type": "string"}}, ["name", "description", "instructions"]),
    "video_analyze": ("Analyze sampled frames of a workspace video with the vision model.",
                      {"source": {"type": "string"}, "prompt": {"type": "string"}}, ["source"]),
    "video_edit": ("Trim and optionally resize a workspace video into an MP4 file.",
                   {"source": {"type": "string"}, "start_seconds": {"type": "integer"},
                    "duration_seconds": {"type": "integer"}, "width": {"type": "integer"}},
                   ["source", "start_seconds", "duration_seconds"]),
    "mcp_list": ("List tools from an enabled MCP server.", {"server_id": {"type": "string"}}, ["server_id"]),
    "mcp_call": ("Call an advertised tool on an enabled MCP server after user approval.",
                 {"server_id": {"type": "string"}, "tool_name": {"type": "string"},
                  "arguments": {"type": "object"}}, ["server_id", "tool_name", "arguments"]),
    "image_analyze": ("Analyze an HTTPS image URL or an image path in the user workspace.",
                      {"image_url": {"type": "string"}, "prompt": {"type": "string"}}, ["image_url"]),
    "media_generate": ("Generate an image, edit an image, or generate a video using a configured media model.",
                       {"kind": {"type": "string", "enum": ["image_generation", "image_edit", "video_generation"]},
                        "prompt": {"type": "string"}, "image_url": {"type": "string"}}, ["kind", "prompt"]),
    "calculator": ("Evaluate basic arithmetic.", {"expression": {"type": "string"}}, ["expression"]),
    "read_file": ("Read a UTF-8 file inside the configured workspace.",
                  {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["path"]),
    "glob_files": ("List files matching a glob inside the configured workspace.",
                   {"pattern": {"type": "string"}}, ["pattern"]),
    "grep_files": ("Search workspace text files with a regular expression.",
                   {"pattern": {"type": "string"}, "glob": {"type": "string"}}, ["pattern"]),
    "read": ("Read a workspace UTF-8 file with optional line bounds.",
             {"file_path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["file_path"]),
    "glob": ("List workspace files matching a glob pattern.",
             {"pattern": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}}, ["pattern"]),
    "grep": ("Search workspace text files with a regular expression.",
             {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"},
              "context": {"type": "integer"}, "limit": {"type": "integer"}}, ["pattern"]),
    "write": ("Write a UTF-8 file in the workspace.",
              {"file_path": {"type": "string"}, "content": {"type": "string"}}, ["file_path", "content"]),
    "edit": ("Replace exact text in an existing workspace file.",
             {"file_path": {"type": "string"}, "old_string": {"type": "string"},
              "new_string": {"type": "string"}, "mode": {"type": "string"},
              "edits": {"type": "array", "items": {"type": "object"}}}, ["file_path"]),
    "skill_load": ("Load an enabled Skill's full instructions.",
                   {"name": {"type": "string"}}, ["name"]),
    "memory_search": ("Search scoped experience first, then raw messages if no experience matches.",
                      {"query": {"type": "string"}, "limit": {"type": "integer"},
                       "group_id": {"type": "string"}}, ["query"]),
    "user_profile_update": ("Record an explicit user fact or preference in the shared 500-character profile.",
                            {"fact": {"type": "string"}}, ["fact"]),
    "plan_update": ("Create or revise future plan steps with per-step acceptance criteria.",
                    {"steps": {"type": "array", "items": {"type": "object"}},
                     "reason": {"type": "string"}}, ["steps", "reason"]),
    "plan_check": ("Record acceptance evidence and outcome for one plan step.",
                   {"step_id": {"type": "string"}, "passed": {"type": "boolean"},
                    "evidence": {"type": "string"}}, ["step_id", "passed", "evidence"]),
    "schedule_create": ("Schedule a future assistant request with optional repeat interval.",
                        {"prompt": {"type": "string"}, "run_at": {"type": "string"},
                         "interval_seconds": {"type": "integer"}}, ["prompt", "run_at"]),
    "schedule_list": ("List scheduled assistant requests and their status.", {}, []),
    "web_fetch": ("Fetch public web page text.",
                  {"url": {"type": "string"}, "max_length": {"type": "integer"}}, ["url"]),
    "url_to_md": ("Fetch a public page and save readable Markdown in the workspace.",
                 {"url": {"type": "string"}, "output_path": {"type": "string"},
                  "overwrite": {"type": "boolean"}}, ["url"]),
    "bash": ("Execute an approved shell command in the workspace.",
             {"command": {"type": "string"}, "cwd": {"type": "string"},
              "timeout": {"type": "integer"}}, ["command"]),
}

PUBLIC_TOOLS = tuple(name for name in SCHEMAS if name not in {"read_file", "glob_files", "grep_files", "memory_search", "user_profile_update", "delegate_task", "friend_create", "team_create"})
REPLAY_SAFE_TOOLS = frozenset({"calculator", "read", "read_file", "glob", "glob_files", "grep", "grep_files",
                               "memory_search", "skill_load", "web_fetch", "schedule_list"})


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """One authorized tool invocation in an Agent run."""

    agent_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Bounded text returned to the model after tool execution."""

    content: str
    success: bool = True
    error_code: str = ""
    attempts: int = 1
    approval_id: str = ""


def schemas_for(grants: list[str] | tuple[str, ...]) -> list[dict]:
    """Expose only implemented tools explicitly granted to this Agent."""
    return [{"type": "function", "function": {"name": name, "description": SCHEMAS[name][0],
            "parameters": {"type": "object", "properties": SCHEMAS[name][1], "required": SCHEMAS[name][2],
                           "additionalProperties": False}}} for name in grants if name in SCHEMAS]


class ToolRegistry:
    """Authorize one run's tools and dispatch into their real ability handlers."""

    def __init__(self, agent_id: str, grants: tuple[str, ...] | list[str], config: dict,
                 scope: ScopeKey | None = None, memory_store: MemoryStore | None = None,
                 delegation_service=None, agent_service=None, group_service=None) -> None:
        self.agent_id = agent_id
        self.scope = scope
        self.memory_retriever = MemoryRetriever(memory_store) if scope and memory_store and config["memory"]["search_enabled"] else None
        intrinsic = ("user_profile_update",)
        if self.memory_retriever:
            intrinsic += ("memory_search",)
        self.grants = tuple(dict.fromkeys((*grants, *intrinsic))) if scope else tuple(grants)
        self.config = config
        self.delegation_service = delegation_service
        self.agent_service = agent_service
        self.group_service = group_service
        self.mcp_servers = tuple(config.get("agent_extensions", {}).get(agent_id, {}).get("mcp", []))

    def schemas(self) -> list[dict]:
        """Expose only the tool schemas granted to this Agent."""
        return schemas_for(self.grants)

    def _authorized(self, request: ToolRequest) -> ToolResult | None:
        """Reject unrecognized, cross-Agent or ungranted tool calls."""
        if request.agent_id != self.agent_id:
            return ToolResult("tool belongs to another Agent", False)
        if request.name not in SCHEMAS or request.name not in self.grants:
            return ToolResult("tool is not granted", False)
        if not isinstance(request.arguments, dict):
            return ToolResult("invalid tool arguments", False)
        return None

    def execute_sync(self, request: ToolRequest, *, raise_errors: bool = False) -> ToolResult:
        """Call a synchronous built-in handler after grant and argument checks."""
        denied = self._authorized(request)
        if denied:
            return denied
        name = {"read_file": "read", "glob_files": "glob", "grep_files": "grep"}.get(request.name, request.name)
        args = dict(request.arguments)
        if name == "read" and request.name == "read":
            args["path"] = args.get("file_path")
        limit = self.config["tool_runtime"]["max_result_chars"]
        try:
            if name == "calculator":
                content = calculator_handler.run(args, self.config)
            elif name in {"read", "glob", "grep", "write", "edit"}:
                handler = {"read": read_handler, "glob": glob_handler, "grep": grep_handler,
                           "write": write_handler, "edit": edit_handler}[name]
                content = handler.run(args, self.config)
            elif name == "skill_load":
                content = skill_handler.run(args, self.config, self.agent_id)
            elif name == "skill_create":
                content = skill_create_handler.run(args, self.config)
            else:
                return ToolResult("tool requires asynchronous dispatch", False)
            return ToolResult(content[:limit] or "(no result)")
        except (OSError, ValueError, TypeError, KeyError, PermissionError, SyntaxError,
                ZeroDivisionError, OverflowError, re.error) as error:
            if raise_errors:
                raise
            return ToolResult(f"tool failed: {type(error).__name__}", False)

    async def execute(self, name: str, arguments: dict[str, Any], *, raise_errors: bool = False) -> ToolResult:
        """Call the bound scoped, network, shell or synchronous ability handler."""
        request = ToolRequest(self.agent_id, name, arguments)
        denied = self._authorized(request)
        if denied:
            return denied
        try:
            if name == "delegate_task":
                if self.agent_id != ASSISTANT or self.scope is None or self.scope.kind != ASSISTANT or self.delegation_service is None:
                    return ToolResult("delegation is available only to XiaoWei's personal conversation", False)
                content = await delegate_handler.run(arguments, self.delegation_service)
            elif name in {"friend_create", "team_create"}:
                if self.agent_id != ASSISTANT or self.scope is None or self.scope.kind != ASSISTANT:
                    return ToolResult("creation is available only to XiaoWei's personal conversation", False)
                if name == "friend_create":
                    if self.agent_service is None:
                        return ToolResult("friend creation service is unavailable", False)
                    content = friend_create_handler.run(arguments, self.agent_service)
                else:
                    if self.group_service is None:
                        return ToolResult("team creation service is unavailable", False)
                    content = team_create_handler.run(arguments, self.group_service)
            elif name == "memory_search":
                if self.memory_retriever is None or self.scope is None:
                    return ToolResult("memory search is unavailable for this run", False)
                content = memory_handler.run(arguments, self.config, self.memory_retriever, self.scope, self.agent_id)
            elif name in {"plan_update", "plan_check"}:
                if self.scope is None:
                    return ToolResult("plan scope is unavailable", False)
                handler = plan_update_handler if name == "plan_update" else plan_check_handler
                content = handler.run(arguments, self.config, self.scope, self.agent_id)
            elif name == "user_profile_update":
                if self.scope is None:
                    return ToolResult("profile scope is unavailable", False)
                content = profile_handler.run(arguments, self.config)
            elif name in {"schedule_create", "schedule_list"}:
                if self.scope is None:
                    return ToolResult("schedule scope is unavailable", False)
                handler = schedule_create_handler if name == "schedule_create" else schedule_list_handler
                content = handler.run(arguments, self.config)
            elif name == "web_fetch":
                content = await web_fetch_handler.run(arguments, self.config)
            elif name == "media_generate":
                content = await media_handler.run(arguments, self.config)
            elif name == "image_analyze":
                content = await image_handler.run(arguments, self.config)
            elif name == "video_analyze":
                content = await video_analyze_handler.run(arguments, self.config)
            elif name == "video_edit":
                content = await video_edit_handler.run(arguments, self.config)
            elif name in {"mcp_list", "mcp_call"}:
                server_id = arguments["server_id"]
                if server_id not in self.mcp_servers:
                    return ToolResult("MCP server is not enabled for this Agent", False)
                mcp_client = MCPClient(self.config["home"], self.config["mcp"])
                if name == "mcp_list":
                    content = json.dumps(await mcp_client.list_tools(server_id), ensure_ascii=False)
                else:
                    content = await mcp_client.call_tool(server_id, arguments["tool_name"], arguments["arguments"])
            elif name == "url_to_md":
                content = await url_to_md_handler.run(arguments, self.config)
            elif name == "bash":
                content, success = await bash_handler.run(arguments, self.config)
                return ToolResult(content, success)
            else:
                return self.execute_sync(request, raise_errors=raise_errors)
            return ToolResult(content)
        except (OSError, ValueError, TypeError, KeyError, PermissionError, httpx.HTTPError) as error:
            if raise_errors:
                raise
            return ToolResult(f"tool failed: {type(error).__name__}", False)


def execute(request: ToolRequest, grants: list[str], config: dict) -> ToolResult:
    """Compatibility entry point for synchronous tool callers."""
    return ToolRegistry(request.agent_id, grants, config).execute_sync(request)


async def execute_async(request: ToolRequest, grants: list[str], config: dict) -> ToolResult:
    """Compatibility entry point for asynchronous tool callers."""
    return await ToolRegistry(request.agent_id, grants, config).execute(request.name, request.arguments)
