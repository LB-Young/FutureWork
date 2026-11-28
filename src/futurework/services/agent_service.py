"""Create and revise Agent definitions while keeping TOML and SQLite aligned."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from futurework.algorithm import TaskPlanner
from futurework.contexts.types import ScopeKey
from futurework.database import decode_agent, utc_now
from futurework.extension_system.skill_loader import load_skills
from futurework.kinds import ASSISTANT, FRIEND, NATIVE


class AgentServiceError(Exception):
    """A domain conflict or limit that the API maps to an HTTP response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class AgentService:
    """Own Agent identity, default permissions, and versioned config writes."""

    def __init__(self, database, config: dict, config_store, message_service, memory_store=None) -> None:
        self.database = database
        self.config = config
        self.config_store = config_store
        self.message_service = message_service
        self.memory_store = memory_store
        self.planner = TaskPlanner(config)

    def create_agent(self, name: str, role: str, *, model: str | None = None,
                     tools: list[str] | None = None, skills: list[str] | None = None,
                     capabilities: dict[str, float] | None = None) -> dict:
        """Validate an explicit Agent request, create its file, and greet the user."""
        name, role = name.strip(), role.strip()
        if not name or not role or len(name) > self.config["limits"]["max_agent_name_chars"] or len(role) > self.config["limits"]["max_agent_role_chars"]:
            raise AgentServiceError(422, "agent name or role is too long")
        selected_model = model or self.config["model"]["default_model"]
        if selected_model not in self.config["model"]["available_models"]:
            raise AgentServiceError(422, "model is not available")
        if self.config["models"]["models"][selected_model].get("model_type", "text") not in {"text", "vision"}:
            raise AgentServiceError(422, "Agent conversation needs a text or vision model")
        selected_tools = list(self.config["permissions"]["safe_default_tools"] if tools is None else tools)
        if len(selected_tools) != len(set(selected_tools)) or not set(selected_tools).issubset(
                self.config["permissions"]["available_tools"]):
            raise AgentServiceError(422, "unknown or duplicate tool")
        selected_skills = list(skills or [])
        if len(selected_skills) != len(set(selected_skills)):
            raise AgentServiceError(422, "duplicate Skill")
        try:
            load_skills(self.config["home"], selected_skills, self.config["skill_policy"]["max_skill_chars"])
        except ValueError as error:
            raise AgentServiceError(422, str(error)) from error
        capability = self.planner.plan_steps(role)[0]["capability"]
        selected_capabilities = capabilities if capabilities is not None else {
            capability: self.config["matching"]["auto_agent_proficiency"]}
        if not selected_capabilities or any(not isinstance(key, str) or not key.strip()
                                            or type(value) not in (int, float) or not 0 < value <= 1
                                            for key, value in selected_capabilities.items()):
            raise AgentServiceError(422, "capabilities must map names to proficiency in (0, 1]")
        with self.config_store.batch() as write_config, self.database.transaction() as connection:
            created = self.create(connection, write_config, name, role, capability,
                                  model=selected_model, tools=selected_tools,
                                  skills=selected_skills, capabilities=selected_capabilities)
            self.message_service.insert(connection, created["id"], "agent", created["name"],
                                        f"你好，我是{created['name']}。我的职责是{created['role']}。")
        if self.memory_store is not None:
            self.memory_store.ensure_profile(ScopeKey(FRIEND, created["id"]))
        self.config["agent_execution"][created["id"]] = {"kind": NATIVE}
        self.config["agent_extensions"][created["id"]] = {"skills": selected_skills}
        return created

    def patch_agent(self, agent_id: str, proposal: dict) -> dict:
        """Apply a safe patch or create a review request for elevated permissions."""
        existing = self.assistant() if agent_id == ASSISTANT else self.database.agent(agent_id)
        if not existing:
            raise AgentServiceError(404, "agent not found")
        if proposal["model"] not in self.config["model"]["available_models"]:
            raise AgentServiceError(422, "model is not available")
        tools = proposal["tools"]
        available = (set(self.config["permissions"]["available_tools"])
                     | ({"delegate_task", "friend_create", "team_create"} if agent_id == ASSISTANT else set()))
        if len(tools) != len(set(tools)) or not set(tools).issubset(available):
            raise AgentServiceError(422, "unknown or duplicate tool")
        if existing["version"] != proposal["expected_version"]:
            raise AgentServiceError(409, "agent configuration has changed")
        added = set(tools) - set(existing["tools"])
        high_risk = added.intersection(self.config["permissions"]["approval_required_tools"]) or (existing["approval"] and not proposal["approval"])
        if high_risk:
            approval_id = str(uuid4())
            description = f"将 {existing['name']} 的权限更新为：{', '.join(tools) or '无工具'}；模型：{proposal['model']}；关键操作审批：{'开启' if proposal['approval'] else '关闭'}"
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=self.config["limits"]["approval_ttl_hours"])).isoformat()
            with self.database.transaction() as connection:
                connection.execute("INSERT INTO approvals VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL)",
                                   (approval_id, agent_id, agent_id, description, json.dumps(proposal, ensure_ascii=False), expires_at, utc_now()))
                self.message_service.insert(connection, agent_id, "system", "系统", description, approval_id=approval_id)
                self.database.emit(connection, "approval.created", {"approval_id": approval_id, "conversation_id": agent_id})
            return {"status": "pending_approval", "approval_id": approval_id}
        with self.config_store.batch() as write_config, self.database.transaction() as connection:
            self.apply_patch(connection, write_config, agent_id, proposal)
        return {"status": "updated", "agent": self.assistant() if agent_id == ASSISTANT else self.database.agent(agent_id)}

    def assistant(self) -> dict:
        """Expose the personal assistant through the same settings contract as friends."""
        definition = self.config["assistant"]
        return {"id": ASSISTANT, "name": definition["name"], "role": definition["role"],
                "icon": "✦", "color": "#efe8dc", "ink": "#7b5a49",
                "model": definition["model"]["id"], "tools": list(definition.get("tools", [])),
                "capabilities": definition.get("capabilities", {}),
                "approval": definition.get("approval", True), "version": definition.get("version", 1)}

    def pending_approvals(self) -> list[dict]:
        """Return unexpired approval records with parsed proposals."""
        with self.database.transaction() as connection:
            rows = connection.execute("SELECT * FROM approvals WHERE status='pending' AND expires_at>? ORDER BY created_at DESC", (utc_now(),)).fetchall()
            return [dict(row) | {"proposal": json.loads(row["proposal"])} for row in rows]

    def decide_approval(self, approval_id: str, decision: str) -> dict:
        """Resolve one pending proposal and apply its config patch if approved."""
        if decision not in {"approve", "reject"}:
            raise AgentServiceError(422, "invalid decision")
        with self.config_store.batch() as write_config, self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not row:
                raise AgentServiceError(404, "approval not found")
            if row["status"] != "pending" or row["expires_at"] <= utc_now():
                raise AgentServiceError(409, "approval is no longer pending")
            proposal = json.loads(row["proposal"])
            is_tool_call = proposal.get("kind") == "tool_call"
            if decision == "approve" and not is_tool_call:
                self.apply_patch(connection, write_config, row["agent_id"], json.loads(row["proposal"]))
            status = "approved" if decision == "approve" else "rejected"
            connection.execute("UPDATE approvals SET status=?, decided_at=? WHERE id=? AND status='pending'",
                               (status, utc_now(), approval_id))
            self.message_service.insert(connection, row["conversation_id"], "system", "系统",
                                        ("工具调用审批已通过。" if is_tool_call else "配置审批已通过。")
                                        if status == "approved" else
                                        ("工具调用审批已拒绝。" if is_tool_call else "配置审批已拒绝。"))
            self.database.emit(connection, "approval.resolved", {"approval_id": approval_id,
                                                                   "conversation_id": row["conversation_id"], "status": status})
        return {"id": approval_id, "status": status}

    def create(self, connection, write_config, name: str, role: str, capability: str, *,
               model: str | None = None, tools: list[str] | None = None,
               skills: list[str] | None = None, capabilities: dict[str, float] | None = None) -> dict:
        """Create an Agent in an existing database and file batch."""
        if connection.execute("SELECT COUNT(*) FROM agents WHERE status='active'").fetchone()[0] >= self.config["limits"]["max_agents"]:
            raise AgentServiceError(409, "agent limit reached")
        base_name = name.strip()
        unique_name = base_name
        suffix = 2
        while connection.execute("SELECT 1 FROM agents WHERE name=?", (unique_name,)).fetchone():
            unique_name = f"{base_name} {suffix}"
            suffix += 1
        agent = {
            "id": str(uuid4()), "name": unique_name, "role": role.strip(), "icon": unique_name[0],
            "color": self.config["ui"]["default_agent_color"], "ink": self.config["ui"]["default_agent_ink"],
            "model": model or self.config["model"]["default_model"],
            "tools": list(self.config["permissions"]["safe_default_tools"] if tools is None else tools),
            "capabilities": capabilities or {capability: self.config["matching"]["auto_agent_proficiency"]},
            "skills": list(skills or []),
            "approval": True, "version": 1, "status": "active",
        }
        self.database.insert_agent(connection, agent)
        write_config("agents", agent)
        self.database.emit(connection, "agent.created", {"agent_id": agent["id"]})
        return agent

    def apply_patch(self, connection, write_config, agent_id: str, proposal: dict) -> None:
        """Apply a version checked Agent patch and update its TOML definition."""
        if agent_id == ASSISTANT:
            current = self.assistant()
            if current["version"] != proposal["expected_version"]:
                raise AgentServiceError(409, "agent configuration has changed")
            updated = {**current, "model": proposal["model"], "tools": proposal["tools"],
                       "approval": proposal["approval"], "version": current["version"] + 1}
            write_config("agents", updated)
            self.config["assistant"].update({"model": {**self.config["assistant"]["model"], "id": updated["model"]},
                                             "tools": updated["tools"], "approval": updated["approval"],
                                             "version": updated["version"]})
            self.database.emit(connection, "agent.updated", {"agent_id": agent_id})
            return
        current = connection.execute("SELECT version FROM agents WHERE id=?", (agent_id,)).fetchone()
        if not current or current["version"] != proposal["expected_version"]:
            raise AgentServiceError(409, "agent configuration has changed")
        connection.execute(
            "UPDATE agents SET model=?, tools=?, approval=?, version=version+1 WHERE id=?",
            (proposal["model"], json.dumps(proposal["tools"], ensure_ascii=False), int(proposal["approval"]), agent_id),
        )
        row = connection.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        write_config("agents", decode_agent(row))
        self.database.emit(connection, "agent.updated", {"agent_id": agent_id})
