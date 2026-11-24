"""Normalize an incoming conversation request before creating a runtime task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ConversationKind = Literal["assistant", "agent", "group"]


@dataclass(frozen=True, slots=True)
class ConversationTarget:
    """The selected conversation and its configuration snapshot at entry time."""

    id: str
    kind: ConversationKind
    name: str
    record: dict

    @classmethod
    def from_record(cls, record: dict) -> "ConversationTarget":
        """Convert an API/database projection into a typed target."""
        return cls(id=record["id"], kind=record["kind"], name=record["name"], record=dict(record))


@dataclass(frozen=True, slots=True)
class RunParams:
    """Stable input boundary shared by assistant, friend, and group execution."""

    source: str
    target: ConversationTarget
    message: str
    client_message_id: str

    @classmethod
    def from_http(cls, conversation: dict, body: str, client_message_id: str) -> "RunParams":
        """Normalize the HTTP payload once before any model or task work."""
        return cls(source="http", target=ConversationTarget.from_record(conversation),
                   message=body.strip(), client_message_id=client_message_id)

    @property
    def conversation_id(self) -> str:
        """Return the persisted session ID used for conversation context."""
        return self.target.id
