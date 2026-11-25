"""Persist a short user profile and scoped dynamic plans for built-in tools."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from futurework.contexts.types import ScopeKey


def atomic_text(path: Path, content: str) -> None:
    """Replace one user-owned file only after a complete durable write."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class UserProfile:
    """Keep explicitly observed user preferences below the configured character cap."""

    def __init__(self, home: Path, max_chars: int = 500) -> None:
        self.path = home / "user.md"
        self.max_chars = max_chars

    def read(self) -> str:
        """Read the current shared profile, including manual edits."""
        content = self.path.read_text(encoding="utf-8") if self.path.is_file() else ""
        return content[:self.max_chars]

    def add(self, fact: str) -> str:
        """Append one concise fact without overwriting previous user information."""
        fact = fact.strip().replace("\n", " ")
        if not fact or len(fact) > self.max_chars or any(mark in fact for mark in ("<", ">")):
            raise ValueError("invalid profile fact")
        raw = self.path.read_text(encoding="utf-8") if self.path.is_file() else ""
        if len(raw) > self.max_chars:
            raise ValueError("existing user profile exceeds configured limit")
        existing = raw.strip()
        line = f"- {fact}"
        if line in existing.splitlines():
            return existing
        updated = f"{existing}\n{line}".strip()
        if len(updated) > self.max_chars:
            raise ValueError("user profile exceeds configured limit")
        atomic_text(self.path, updated + ("\n" if len(updated) < self.max_chars else ""))
        return updated


class DynamicPlan:
    """Store actionable steps and explicit acceptance evidence per actor and scope."""

    def __init__(self, home: Path, scope: ScopeKey, actor_id: str, max_steps: int) -> None:
        if not actor_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError("invalid plan actor")
        self.path = home / "data" / "plans" / scope.kind / scope.id / f"{actor_id}.json"
        self.max_steps = max_steps

    def read(self) -> dict:
        """Read the latest plan for this execution identity."""
        if not self.path.is_file():
            return {"steps": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def update(self, steps: list[dict], reason: str) -> dict:
        """Revise future steps while preserving already accepted results."""
        if not isinstance(steps, list) or not 1 <= len(steps) <= self.max_steps:
            raise ValueError("invalid plan step count")
        old = self.read()
        accepted = {item["id"]: item for item in old["steps"] if item.get("status") == "passed"}
        result = []
        ids = set()
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("invalid plan step")
            step_id = step.get("id")
            if not isinstance(step_id, str) or not step_id.isidentifier() or step_id in ids:
                raise ValueError("invalid or duplicate plan step ID")
            ids.add(step_id)
            if step_id in accepted:
                if step.get("action") != accepted[step_id]["action"] or step.get("acceptance") != accepted[step_id]["acceptance"]:
                    raise ValueError("accepted plan steps are immutable")
                result.append(accepted[step_id])
                continue
            action, acceptance = step.get("action"), step.get("acceptance")
            if not all(isinstance(value, str) and 0 < len(value.strip()) <= 500 for value in (action, acceptance)):
                raise ValueError("each plan step needs an action and acceptance criterion")
            result.append({"id": step_id, "action": action.strip(), "acceptance": acceptance.strip(),
                           "status": "pending", "evidence": ""})
        if not set(accepted).issubset(ids):
            raise ValueError("cannot remove accepted plan steps")
        plan = {"reason": str(reason)[:500], "steps": result}
        atomic_text(self.path, json.dumps(plan, ensure_ascii=False, indent=2))
        return plan

    def check(self, step_id: str, passed: bool, evidence: str) -> dict:
        """Record a concrete observation against one step's acceptance rule."""
        if type(passed) is not bool or not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 2000:
            raise ValueError("acceptance requires a bounded result and evidence")
        plan = self.read()
        for step in plan["steps"]:
            if step["id"] == step_id:
                step["status"] = "passed" if passed else "failed"
                step["evidence"] = evidence.strip()
                atomic_text(self.path, json.dumps(plan, ensure_ascii=False, indent=2))
                return step
        raise ValueError("plan step does not exist")
