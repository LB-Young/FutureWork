"""Load and execute bounded, declarative Agent workflows without arbitrary scripts."""

from __future__ import annotations

import json
import re
import tomllib
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from futurework.abilities.tools.management import atomic_text


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class WorkflowRunner:
    """Validate a workflow DAG and execute its Agent tasks in dependency order."""

    def __init__(self, home: Path, limits: dict) -> None:
        self.home = home
        self.limits = limits

    def load(self, workflow_id: str) -> dict:
        """Prefer user-installed workflow definitions, then bundled definitions."""
        if not SAFE_ID.fullmatch(workflow_id):
            raise ValueError("invalid workflow ID")
        candidates = [self.home / "abilities" / "workflows" / workflow_id / "workflow.toml",
                      self.home / "workflows" / workflow_id / "workflow.toml"]
        for path in candidates:
            if path.is_file():
                if not path.resolve().is_relative_to(self.home.resolve()):
                    raise ValueError("workflow path escapes user home")
                with path.open("rb") as source:
                    return self._validate(tomllib.load(source), workflow_id)
        resource = files("futurework").joinpath("abilities", "workflows", workflow_id, "workflow.toml")
        if resource.is_file():
            with resource.open("rb") as source:
                return self._validate(tomllib.load(source), workflow_id)
        raise ValueError("workflow not found")

    def _validate(self, workflow: dict, workflow_id: str) -> dict:
        if workflow.get("id") != workflow_id or workflow.get("enabled") is not True:
            raise ValueError("workflow is disabled or has an invalid ID")
        steps = workflow.get("steps", [])
        if not isinstance(steps, list) or not 1 <= len(steps) <= self.limits["max_steps"]:
            raise ValueError("invalid workflow step count")
        ids = set()
        for step in steps:
            if not isinstance(step, dict) or not SAFE_ID.fullmatch(str(step.get("id", ""))) or step["id"] in ids:
                raise ValueError("invalid or duplicate workflow step ID")
            ids.add(step["id"])
            if step.get("kind") != "agent_task" or not isinstance(step.get("agent_id"), str):
                raise ValueError("only agent_task steps with an agent_id are supported")
            if not isinstance(step.get("prompt"), str) or not step["prompt"].strip():
                raise ValueError("workflow step requires a prompt")
            if not isinstance(step.get("depends_on", []), list):
                raise ValueError("workflow dependency list is invalid")
        for step in steps:
            if any(dependency not in ids or dependency == step["id"] for dependency in step.get("depends_on", [])):
                raise ValueError("workflow has an unknown or self dependency")
        return workflow

    async def run(self, workflow_id: str, user_input: str, execute_step) -> dict:
        """Run a user-enabled workflow, persisting every completed step."""
        if not user_input.strip() or len(user_input) > self.limits["max_input_chars"]:
            raise ValueError("invalid workflow input")
        workflow = self.load(workflow_id)
        run_id = uuid4().hex
        path = self.home / "data" / "workflows" / f"{run_id}.json"
        state = {"run_id": run_id, "workflow_id": workflow_id, "status": "running", "steps": {}}
        atomic_text(path, json.dumps(state, ensure_ascii=False))
        pending = {step["id"]: step for step in workflow["steps"]}
        try:
            while pending:
                ready = [step for step in pending.values() if all(dependency in state["steps"] for dependency in step.get("depends_on", []))]
                if not ready:
                    raise ValueError("workflow dependency cycle")
                for step in ready:
                    prompt = step["prompt"].replace("{{input}}", user_input)
                    for dependency in step.get("depends_on", []):
                        prompt = prompt.replace("{{steps." + dependency + "}}", state["steps"][dependency]["output"])
                    output = await execute_step(step["agent_id"], prompt)
                    state["steps"][step["id"]] = {"agent_id": step["agent_id"], "output": output[:self.limits["max_output_chars"]]}
                    del pending[step["id"]]
                    atomic_text(path, json.dumps(state, ensure_ascii=False))
            state["status"] = "completed"
        except Exception:
            state["status"] = "failed"
            atomic_text(path, json.dumps(state, ensure_ascii=False))
            raise
        atomic_text(path, json.dumps(state, ensure_ascii=False))
        return state
