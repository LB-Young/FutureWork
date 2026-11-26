"""Resolve one configured Agent friend to a native, CLI, process, or HTTP backend."""

from .http_backend import HttpBackend
from .subprocess_backend import SubprocessBackend
from futurework.kinds import NATIVE, EXECUTION_KINDS, HTTP


class AgentBackendRegistry:
    """Keep backend selection outside the three conversation runtimes."""

    def __init__(self, config: dict):
        self.config = config

    def for_agent(self, agent_id: str):
        execution = self.config["agent_execution"].get(agent_id, {"kind": NATIVE})
        kind = execution.get("kind", NATIVE)
        if kind == NATIVE:
            return None
        profile = {**self.config["agent_backends"].get("defaults", {}),
                   **self.config["agent_backends"]["profiles"][execution["profile"]]}
        profile.setdefault("workdir", str(self.config["home"] / "workspace"))
        if kind == HTTP:
            return HttpBackend(profile)
        if kind in EXECUTION_KINDS - {NATIVE, HTTP}:
            return SubprocessBackend(kind, profile)
        raise ValueError(f"unknown Agent backend: {kind}")
