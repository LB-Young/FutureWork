"""Route a group task to the runtime that owns its execution mode."""

from futurework.runtime.group_controlled import ControlledRuntime
from futurework.runtime.group_swarm import SwarmRuntime
from futurework.runtime.task_factory import Task, TaskKind


class TeamRuntime:
    """Select a group runtime without running a group execution loop here."""

    def __init__(self, database, config: dict, message_service, agent_runtime) -> None:
        self.swarm = SwarmRuntime(database, config, message_service, agent_runtime)
        self.controlled = ControlledRuntime(database, config, message_service, agent_runtime)

    async def run(self, task: Task) -> int:
        """Dispatch a normalized task to its mode-specific runtime."""
        if task.kind is TaskKind.GROUP_SWARM:
            return await self.swarm.run(task)
        if task.kind is TaskKind.GROUP_CONTROLLED:
            return await self.controlled.run(task)
        raise ValueError(f"Unsupported group task kind: {task.kind}")
