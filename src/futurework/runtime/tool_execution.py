"""Enforce tool grants, per-call approval, schemas, bounded retries and audit."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import httpx

from futurework.contexts.store import MemoryStore
from futurework.contexts.types import ScopeKey
from futurework.runtime.tool_dispatch import REPLAY_SAFE_TOOLS, SCHEMAS, ToolRegistry, ToolResult


JSON_OUTPUTS = {"delegate_task": dict, "friend_create": dict, "team_create": dict, "team_directory": dict,
                "memory_search": dict, "plan_update": dict, "plan_check": dict,
                "schedule_create": dict, "schedule_list": list, "user_profile_update": str}
JSON_REQUIRED = {"delegate_task": {"task_id", "status"},
                 "friend_create": {"id", "name", "model", "tools", "skills"},
                 "team_create": {"id", "name", "member_ids", "mode"},
                 "team_directory": {"assistant", "friends", "teams"},
                 "memory_search": {"tier", "scope", "matches"},
                 "plan_update": {"steps"}, "plan_check": {"id", "status", "evidence"},
                 "schedule_create": {"id", "prompt", "run_at", "status"}}


class OutputValidationError(ValueError):
    """A tool handler returned content that violates its advertised contract."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Immutable model tool call with the identity and scope fixed by the run."""

    id: str
    agent_id: str
    scope: ScopeKey
    name: str
    arguments: dict[str, Any]


class ToolExecutionLayer:
    """Own all model-originated tool execution decisions for one Agent run."""

    def __init__(self, registry: ToolRegistry, config: dict, store: MemoryStore,
                 approval_store=None, require_approval: bool = True) -> None:
        self.registry = registry
        self.config = config
        self.store = store
        self.approval_store = approval_store
        self.require_approval = require_approval
        self.policy = config["tool_execution"]

    def _validate_input(self, call: ToolCall) -> None:
        """Validate the exact schema advertised to the model before any side effect."""
        if call.agent_id != self.registry.agent_id or call.scope != self.registry.scope:
            raise PermissionError("tool call identity or scope mismatch")
        if call.name not in SCHEMAS or call.name not in self.registry.grants:
            raise PermissionError("tool is not granted")
        if not isinstance(call.arguments, dict):
            raise ValueError("tool arguments must be an object")
        encoded = json.dumps(call.arguments, ensure_ascii=False, allow_nan=False)
        if len(encoded) > self.policy["max_input_chars"]:
            raise ValueError("tool arguments exceed configured limit")
        _, properties, required = SCHEMAS[call.name]
        if any(key not in call.arguments for key in required) or any(key not in properties for key in call.arguments):
            raise ValueError("tool arguments do not match advertised fields")
        expected = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
        for key, value in call.arguments.items():
            kind = properties[key]["type"]
            if kind == "integer":
                valid = type(value) is int
            else:
                valid = isinstance(value, expected[kind])
            if not valid:
                raise ValueError(f"invalid type for {key}")
            if "enum" in properties[key] and value not in properties[key]["enum"]:
                raise ValueError(f"invalid value for {key}")

    def _validate_output(self, call: ToolCall, result: ToolResult) -> ToolResult:
        """Check result shape and keep model-visible text within the configured budget."""
        if not isinstance(result, ToolResult) or not isinstance(result.content, str):
            raise OutputValidationError("tool handler returned an invalid result")
        if not result.success:
            return result
        if call.name in JSON_OUTPUTS:
            try:
                parsed = json.loads(result.content)
            except json.JSONDecodeError as error:
                raise OutputValidationError("tool returned invalid JSON") from error
            if not isinstance(parsed, JSON_OUTPUTS[call.name]):
                raise OutputValidationError("tool JSON output has the wrong shape")
            if call.name in JSON_REQUIRED and not JSON_REQUIRED[call.name].issubset(parsed):
                raise OutputValidationError("tool JSON output is missing required fields")
            if len(result.content) > self.policy["max_output_chars"]:
                raise OutputValidationError("structured tool output exceeds configured limit")
        if len(result.content) > self.policy["max_output_chars"]:
            cap = self.policy["max_output_chars"]
            marker = "\n[输出已截断]"
            result = ToolResult(result.content[:max(0, cap - len(marker))] + marker[:cap], True)
        return result

    def _retryable(self, call: ToolCall, error: Exception) -> bool:
        """Follow Bamboo's transient classification, then require a safe read tool."""
        if call.name not in REPLAY_SAFE_TOOLS or call.name not in self.policy["retry_read_tools"]:
            return False
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            return status in self.policy["retry_http_statuses"] or (self.policy["retry_http_5xx"] and 500 <= status <= 599)
        if isinstance(error, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, TimeoutError)):
            return True
        if isinstance(error, OSError):
            numbers = {getattr(errno, name) for name in self.policy["retry_system_errors"]}
            return error.errno in numbers
        return False

    def _audit(self, call: ToolCall, decision: str, result: ToolResult, duration_ms: int,
               attempts_detail: list[dict] | None = None) -> None:
        """Append a scoped record without copying potentially sensitive arguments."""
        scope = self.registry.scope
        if scope is None:
            return
        arguments_hash = hashlib.sha256(json.dumps(call.arguments, ensure_ascii=False,
                                                   sort_keys=True, default=str).encode()).hexdigest()
        self.store._append_jsonl(self.store.directory(scope) / "tool_calls.jsonl", {
            "schema_version": 1, "type": "tool_call", "scope": f"{scope.kind}:{scope.id}",
            "actor_id": call.agent_id, "call_id": call.id, "tool": call.name,
            "arguments_sha256": arguments_hash, "decision": decision, "success": result.success,
            "error_code": result.error_code, "attempts": result.attempts,
            "attempts_detail": attempts_detail or [],
            "approval_id": result.approval_id, "duration_ms": duration_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    async def execute(self, call: ToolCall) -> ToolResult:
        """Authorize once, await review if needed, then retry only safe transient reads."""
        started = perf_counter()
        approval_id = ""
        try:
            self._validate_input(call)
        except (ValueError, TypeError, PermissionError, KeyError) as error:
            result = ToolResult(f"tool call denied: {type(error).__name__}", False, "invalid_input" if not isinstance(error, PermissionError) else "denied")
            self._audit(call, "deny", result, int((perf_counter() - started) * 1000))
            return result
        if (self.require_approval or call.name in {"friend_create", "team_create"}) and call.name in self.policy["require_approval_for"]:
            if self.approval_store is None:
                result = ToolResult("tool call requires approval; approval channel unavailable", False, "approval_unavailable")
                self._audit(call, "ask", result, int((perf_counter() - started) * 1000))
                return result
            approval_id = self.approval_store.request(call.agent_id, call.scope, call.id, call.name, call.arguments)
            try:
                approved = await self.approval_store.wait(approval_id)
            except asyncio.CancelledError:
                self.approval_store.cancel(approval_id)
                raise
            if not approved:
                result = ToolResult("tool call approval rejected or expired", False, "approval_denied", approval_id=approval_id)
                self._audit(call, "deny", result, int((perf_counter() - started) * 1000))
                return result
            if not self.approval_store.still_granted(call.agent_id, call.name):
                result = ToolResult("tool grant was revoked before execution", False, "grant_revoked", approval_id=approval_id)
                self._audit(call, "deny", result, int((perf_counter() - started) * 1000))
                return result
        attempts = 0
        attempts_detail = []
        while attempts < self.policy["max_attempts"]:
            attempts += 1
            try:
                output = await asyncio.wait_for(
                    self.registry.execute(call.name, call.arguments, raise_errors=True),
                    timeout=self.policy["delegation_timeout_seconds"] if call.name == "delegate_task"
                    else self.policy["call_timeout_seconds"])
                result = self._validate_output(call, output)
                result = ToolResult(result.content, result.success, result.error_code,
                                    attempts, approval_id)
                attempts_detail.append({"attempt": attempts, "outcome": "success" if result.success else "handler_failure",
                                        "retry": False})
                self._audit(call, "allow", result, int((perf_counter() - started) * 1000), attempts_detail)
                return result
            except Exception as error:
                retry = attempts < self.policy["max_attempts"] and self._retryable(call, error)
                attempts_detail.append({"attempt": attempts, "outcome": type(error).__name__, "retry": retry})
                if not retry:
                    result = ToolResult(f"tool failed: {type(error).__name__}", False,
                                        "transient_exhausted" if self._retryable(call, error) else
                                        "invalid_output" if isinstance(error, OutputValidationError) else "execution_error",
                                        attempts, approval_id)
                    self._audit(call, "allow", result, int((perf_counter() - started) * 1000), attempts_detail)
                    return result
                delay = min(self.policy["max_backoff_seconds"],
                            self.policy["base_backoff_seconds"] * 2 ** (attempts - 1))
                await asyncio.sleep(delay)
        raise RuntimeError("tool execution retry loop exhausted unexpectedly")
