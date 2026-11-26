"""Freeze the inputs and grants of one Agent model execution in a typed object."""

from dataclasses import dataclass
from typing import Any
from futurework.contexts.types import ScopeKey
from futurework.kinds import ASSISTANT, FRIEND


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Agent identity, scoped history, configuration snapshot, and tool grants."""

    agent_id: str
    name: str
    role: str
    model_alias: str
    tools: tuple[str, ...]
    history: tuple[dict[str, Any], ...]
    config: dict[str, Any]
    scope: ScopeKey
    require_tool_approval: bool = True

    @classmethod
    def from_records(cls, agent: dict, history: list[dict], config: dict,
                     scope: ScopeKey | None = None) -> "AgentRun":
        """Convert database and TOML records once at the runtime boundary."""
        return cls(agent_id=agent["id"], name=agent["name"], role=agent["role"],
                   model_alias=agent["model"], tools=tuple(agent.get("tools", [])),
                   history=tuple(dict(item) for item in history), config=config,
                   scope=scope or ScopeKey(ASSISTANT if agent["id"] == ASSISTANT else FRIEND, agent["id"]),
                   require_tool_approval=agent.get("approval", True))
