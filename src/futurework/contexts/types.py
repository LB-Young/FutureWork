"""Define explicit assistant, Agent, and Team memory scope identities."""

import re
from dataclasses import dataclass
from typing import Literal


ScopeKind = Literal["assistant", "agent", "group"]
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class ScopeKey:
    """Prevent a conversation from resolving another scope's memory path."""

    kind: ScopeKind
    id: str

    def __post_init__(self) -> None:
        if self.kind not in {"assistant", "agent", "group"} or not SAFE_ID.fullmatch(self.id):
            raise ValueError("invalid memory scope")
        if self.kind == "assistant" and self.id != "assistant":
            raise ValueError("assistant scope ID must be assistant")
