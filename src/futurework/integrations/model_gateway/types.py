"""Typed model requests and results shared by runtimes, gateway, and adapters."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One model requested tool call, identified for the next provider turn."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One provider neutral text turn with optional approved tool schemas."""

    alias: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ModelResult:
    """Text and tool calls from one provider turn."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
