"""Compress older model context within one scope while preserving source histories."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from futurework.contexts.store import MemoryStore
from futurework.contexts.types import ScopeKey
from futurework.integrations.model_gateway.types import ModelRequest


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Estimated input and available model window for a complete request."""

    input_tokens: int
    remaining_tokens: int
    should_compact: bool


class ContextCompactor:
    """Replace only an old, protocol-complete prefix with a traceable summary."""

    def __init__(self, config: dict, gateway: Any, store: MemoryStore) -> None:
        self.policy = config["compaction"]
        self.models = config["models"]["models"]
        self.gateway = gateway
        self.store = store

    @staticmethod
    def _tokens(value: Any) -> int:
        return math.ceil(len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")) / 4)

    def evaluate(self, request: ModelRequest) -> ContextBudget:
        """Count system, conversation, tools, and structure against the chosen alias."""
        model = self.models[request.alias]
        window = model.get("context_window", self.policy["default_context_window"])
        reserve = model.get("max_output_tokens", self.policy["output_reserve_tokens"])
        if type(window) is not int or window <= 0 or type(reserve) is not int or reserve <= 0:
            raise ValueError("model context_window and max_output_tokens must be positive integers")
        used = self._tokens({"messages": request.messages, "tools": request.tools})
        remaining = window - reserve - used
        return ContextBudget(used, remaining,
                             used / window >= self.policy["trigger_ratio"]
                             or remaining <= self.policy["minimum_remaining_tokens"])

    def _prefix_end(self, messages: list[dict]) -> int:
        """Keep recent turns and never split an assistant/tool exchange."""
        end = len(messages) - self.policy["preserve_recent_messages"]
        if end <= 1:
            return 0
        while end > 1:
            pending = set()
            for item in messages[1:end]:
                if item.get("tool_calls"):
                    pending.update(call["id"] for call in item["tool_calls"])
                if item.get("role") == "tool":
                    pending.discard(item.get("tool_call_id"))
            if not pending and messages[end].get("role") != "tool":
                return end
            end -= 1
        return 0

    def _render(self, item: dict) -> str:
        content = str(item.get("content") or "")
        cap = self.policy["max_inline_message_chars"]
        if len(content) > cap:
            content = (content[:self.policy["preserve_head_chars"]]
                       + "\n[旧消息中间内容已省略；原文保留在消息日志]\n"
                       + content[-self.policy["preserve_tail_chars"]:])
        metadata = {key: item[key] for key in ("role", "tool_calls", "tool_call_id", "source_id") if key in item}
        return json.dumps({**metadata, "content": content}, ensure_ascii=False, default=str)

    async def compact(self, request: ModelRequest, scope: ScopeKey, actor_id: str) -> ModelRequest:
        """Bound model calls; on summary failure keep a deterministic, traceable excerpt."""
        if not self.policy["enabled"]:
            return request
        messages = list(request.messages)
        for _ in range(self.policy["max_passes"]):
            current = ModelRequest(request.alias, messages, request.tools)
            if not self.evaluate(current).should_compact:
                break
            end = self._prefix_end(messages)
            if not end:
                break
            selected = messages[1:end]
            rendered = "\n".join(self._render(item) for item in selected)
            source_cap = self.policy["max_source_chars"]
            source = rendered if len(rendered) <= source_cap else (
                rendered[:source_cap // 2] + "\n[中间历史省略；原文保留在消息日志]\n"
                + rendered[-source_cap // 2:])
            prompt = ("请将以下较早的会话历史压缩为继续当前任务所需的事实摘要。按适用情况记录目标、用户约束、"
                      "已做决定、文件及命令、工具结果、错误及修复、当前状态和待办。保留关键标识和未解决问题。"
                      "不要回答用户，也不要编造信息。")
            method = "model"
            try:
                result = await self.gateway.generate(ModelRequest(request.alias, [
                    {"role": "system", "content": prompt}, {"role": "user", "content": source}]))
                summary = result.text.strip()[:self.policy["max_summary_chars"]]
                if not summary or self._tokens(summary) >= self._tokens(rendered):
                    raise ValueError("summary did not reduce context")
            except Exception:
                method = "excerpt"
                summary = source[:self.policy["max_summary_chars"]]
            replacement = {"role": "assistant", "content": "【较早会话摘要】\n" + summary}
            updated = [messages[0], replacement, *messages[end:]]
            if self._tokens(updated) >= self._tokens(messages):
                break
            self.store._append_jsonl(self.store.directory(scope) / "compactions.jsonl", {
                "schema_version": 1, "type": "context_compaction",
                "scope": f"{scope.kind}:{scope.id}", "actor_id": actor_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_ids": [str(item.get("source_id", "")) for item in selected],
                "source_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                "source_count": len(selected), "summary": summary, "method": method,
                "input_tokens_before": self._tokens(messages), "input_tokens_after": self._tokens(updated),
            })
            messages = updated
        return ModelRequest(request.alias, messages, request.tools)
