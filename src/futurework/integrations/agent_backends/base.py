"""Define the request and result contract shared by external Agent adapters."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AgentRequest:
    agent_id: str
    name: str
    role: str
    scope_type: str
    scope_id: str
    prompt: str
    history: tuple[dict, ...]


class AgentBackend(Protocol):
    """A backend returns a final answer without writing FutureWork messages."""

    async def run(self, request: AgentRequest) -> str: ...

    async def health(self) -> dict: ...
