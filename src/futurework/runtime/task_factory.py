"""Construct typed runtime tasks from normalized RunParams without executing them."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from futurework.runtime.run_params import RunParams


class TaskKind(StrEnum):
    """A separate execution path for each supported conversation request."""

    ASSISTANT_CHAT = "assistant_chat"
    ASSISTANT_DELEGATION = "assistant_delegation"
    AGENT_CHAT = "agent_chat"
    GROUP_SWARM = "group_swarm"
    GROUP_CONTROLLED = "group_controlled"


@dataclass(slots=True)
class Task:
    """One accepted request with its type, stable ID, and normalized inputs."""

    id: str
    kind: TaskKind
    params: RunParams
    status: str = "created"


class TaskFactory:
    """Choose a task type based on target scope and assistant intent."""

    def create(self, params: RunParams, *, assistant_intent: str | None = None) -> Task:
        """Build a task object; routing and execution happen elsewhere."""
        target = params.target
        if target.kind == "assistant":
            if assistant_intent not in {"chat", "task"}:
                raise ValueError("assistant intent must be chat or task")
            kind = TaskKind.ASSISTANT_CHAT if assistant_intent == "chat" else TaskKind.ASSISTANT_DELEGATION
        elif target.kind == "agent":
            kind = TaskKind.AGENT_CHAT
        elif target.kind == "group":
            mode = target.record["mode"]
            if mode not in {"swarm", "controlled"}:
                raise ValueError("group mode must be swarm or controlled")
            kind = TaskKind.GROUP_SWARM if mode == "swarm" else TaskKind.GROUP_CONTROLLED
        else:
            raise ValueError(f"unsupported conversation kind: {target.kind}")
        return Task(id=str(uuid4()), kind=kind, params=params)


@dataclass(frozen=True, slots=True)
class TaskResult:
    """The API-visible result of executing one runtime task."""

    message_id: str
    task_id: str | None = None
    status: str = "accepted"

    def as_response(self) -> dict:
        """Keep the existing HTTP response shape for the web client."""
        return {"message_id": self.message_id, "task_id": self.task_id, "status": self.status}
