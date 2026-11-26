"""Construct typed runtime tasks from normalized RunParams without executing them."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from futurework.runtime.run_params import RunParams
from futurework.kinds import ASSISTANT, FRIEND, TEAM, SWARM, CONTROLLED, KINDS


class TaskKind(StrEnum):
    """A separate execution path for each supported conversation request."""

    AGENT_CHAT = KINDS["task_kind"]["agent_chat"]
    GROUP_SWARM = KINDS["task_kind"]["group_swarm"]
    GROUP_CONTROLLED = KINDS["task_kind"]["group_controlled"]


@dataclass(slots=True)
class Task:
    """One accepted request with its type, stable ID, and normalized inputs."""

    id: str
    kind: TaskKind
    params: RunParams
    status: str = "created"


class TaskFactory:
    """Choose an Agent or Team loop solely from the selected conversation."""

    def create(self, params: RunParams) -> Task:
        """Build a task object; routing and execution happen elsewhere."""
        target = params.target
        if target.kind in {ASSISTANT, FRIEND}:
            kind = TaskKind.AGENT_CHAT
        elif target.kind == TEAM:
            mode = target.record["mode"]
            if mode not in {SWARM, CONTROLLED}:
                raise ValueError("group mode must be swarm or controlled")
            kind = TaskKind.GROUP_SWARM if mode == SWARM else TaskKind.GROUP_CONTROLLED
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
