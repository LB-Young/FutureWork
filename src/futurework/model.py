"""Provide compatibility functions for callers of the original model module."""

from futurework.runtime.agent_executor import AgentRuntime
from futurework.runtime.run_spec import AgentRun


async def respond(agent: dict, history: list[dict], config: dict) -> str:
    """Compatibility entry point for integrations that still pass records."""
    return await AgentRuntime(config).respond(agent, history)


async def execute_run(run: AgentRun) -> str:
    """Compatibility entry point for an already constructed AgentRun."""
    return await AgentRuntime(run.config).run(run)
