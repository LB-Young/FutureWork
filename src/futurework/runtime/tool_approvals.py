"""Persist and resolve approval requests for exact model-initiated tool calls."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from futurework.contexts.types import ScopeKey
from futurework.database import utc_now


class ToolApprovalStore:
    """Use the existing approval inbox while binding a decision to one call."""

    def __init__(self, database, message_service, config: dict) -> None:
        self.database = database
        self.message_service = message_service
        self.config = config

    def request(self, agent_id: str, scope: ScopeKey, call_id: str, name: str, arguments: dict) -> str:
        """Save a reviewable proposal and notify the selected conversation."""
        approval_id = str(uuid4())
        proposal = {"kind": "tool_call", "call_id": call_id, "tool": name,
                    "arguments": arguments, "scope": f"{scope.kind}:{scope.id}"}
        description = f"工具调用待审批：{name}；参数：{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}"
        expires_at = (datetime.now(timezone.utc) + timedelta(
            seconds=self.config["tool_execution"]["approval_wait_seconds"])).isoformat()
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO approvals VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL)",
                               (approval_id, scope.id, agent_id, description,
                                json.dumps(proposal, ensure_ascii=False), expires_at, utc_now()))
            self.message_service.insert(connection, scope.id, "system", "系统", description, approval_id=approval_id)
            self.database.emit(connection, "approval.created", {"approval_id": approval_id, "conversation_id": scope.id})
        return approval_id

    async def wait(self, approval_id: str) -> bool:
        """Poll one durable decision until approval, rejection or timeout."""
        policy = self.config["tool_execution"]
        deadline = asyncio.get_running_loop().time() + policy["approval_wait_seconds"]
        while True:
            with self.database.transaction() as connection:
                row = connection.execute("SELECT status FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if row is None or row["status"] in {"rejected", "expired"}:
                return False
            if row["status"] == "approved":
                return True
            if asyncio.get_running_loop().time() >= deadline:
                with self.database.transaction() as connection:
                    connection.execute("UPDATE approvals SET status='expired', decided_at=? WHERE id=? AND status='pending'",
                                       (utc_now(), approval_id))
                return False
            await asyncio.sleep(min(policy["approval_poll_seconds"], max(0.01, deadline - asyncio.get_running_loop().time())))

    def still_granted(self, agent_id: str, tool_name: str) -> bool:
        """Recheck the current Agent grant after a potentially long approval wait."""
        if agent_id == "assistant":
            grants = set(self.config["assistant"].get("tools", []))
            grants.update({"plan_update", "plan_check", "schedule_create", "schedule_list",
                           "memory_search", "user_profile_update"})
            return tool_name in grants
        agent = self.database.agent(agent_id)
        return bool(agent and agent["status"] == "active" and
                    (tool_name in agent["tools"] or tool_name in {"memory_search", "user_profile_update"}))

    def cancel(self, approval_id: str) -> None:
        """Close a pending approval when its tool execution is cancelled."""
        with self.database.transaction() as connection:
            connection.execute("UPDATE approvals SET status='expired', decided_at=? WHERE id=? AND status IN ('pending','approved')",
                               (utc_now(), approval_id))
