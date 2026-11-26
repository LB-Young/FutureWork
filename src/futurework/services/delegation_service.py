"""Execute XiaoWei's explicit delegation tool requests against friends or teams."""

import json
import asyncio
from uuid import uuid4

from futurework.algorithm import TaskPlanner
from futurework.contexts.types import ScopeKey
from futurework.database import decode_agent, utc_now
from futurework.runtime.run_params import RunParams
from futurework.runtime.task_factory import TaskFactory
from futurework.kinds import ASSISTANT, FRIEND, TEAM, NATIVE, DELEGATION_AUTO


class DelegationService:
    """Create a durable task only after XiaoWei actually calls delegate_task."""

    def __init__(self, database, config: dict, config_store, agent_service,
                 message_service, agent_runtime, team_runtime) -> None:
        self.database = database
        self.config = config
        self.config_store = config_store
        self.agent_service = agent_service
        self.message_service = message_service
        self.agent_runtime = agent_runtime
        self.team_runtime = team_runtime
        self.planner = TaskPlanner(config)

    async def execute(self, request: str, target_kind: str = DELEGATION_AUTO, target_id: str = "") -> str:
        """Plan and run one requested task, reporting persisted step results."""
        if not isinstance(request, str) or not request.strip():
            raise ValueError("delegation request is empty")
        request = request.strip()
        if target_kind not in {DELEGATION_AUTO, FRIEND, TEAM}:
            raise ValueError("unsupported delegation target")
        if target_kind != DELEGATION_AUTO and not target_id:
            raise ValueError("delegation target ID is required")
        if target_kind == TEAM:
            return await self._group(request, target_id)
        if target_kind == FRIEND:
            agent = self.database.agent(target_id)
            if not agent or agent["status"] != "active":
                raise ValueError("delegation friend is unavailable")
            assignments = [(agent, request, "explicit")]
        else:
            with self.database.transaction() as connection:
                agents = [decode_agent(row) for row in connection.execute(
                    "SELECT * FROM agents WHERE status='active'")]
            assignments = []
            for suggestion in self.planner.assign_steps(request, agents):
                agent = self.database.agent(suggestion.agent_id) if suggestion.agent_id else None
                if agent is None:
                    with self.config_store.batch() as write_config, self.database.transaction() as connection:
                        agent = self.agent_service.create(connection, write_config, suggestion.suggested_name,
                                                          suggestion.suggested_role, suggestion.capability)
                    agents.append(agent)
                    self.agent_runtime.config["agent_execution"][agent["id"]] = {"kind": NATIVE}
                assignments.append((agent, suggestion.title, suggestion.capability))
        task_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO tasks VALUES (?, ?, ?, 'running', ?)",
                               (task_id, ASSISTANT, request, utc_now()))
            steps = []
            for agent, title, capability in assignments:
                step_id = str(uuid4())
                connection.execute("INSERT INTO task_steps VALUES (?, ?, ?, ?, ?, 'assigned', ?)",
                                   (step_id, task_id, agent["id"], capability, title, agent["version"]))
                steps.append((step_id, agent, title))
            self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "running"})
        outputs = []
        for step_id, agent, title in steps:
            with self.database.transaction() as connection:
                connection.execute("UPDATE task_steps SET status='running' WHERE id=?", (step_id,))
            prompt = f"{self.config['execution']['step_instruction']}\n总任务：{request}\n子任务：{title}"
            try:
                answer = await self.agent_runtime.respond(
                    agent, [{"from": "me", "text": prompt}], ScopeKey(FRIEND, agent["id"]))
            except asyncio.CancelledError:
                with self.database.transaction() as connection:
                    connection.execute("UPDATE task_steps SET status='failed' WHERE id=?", (step_id,))
                    connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
                    self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "failed"})
                raise
            except Exception as error:
                with self.database.transaction() as connection:
                    connection.execute("UPDATE task_steps SET status='failed' WHERE id=?", (step_id,))
                    connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
                    self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "failed"})
                return json.dumps({"task_id": task_id, "status": "failed",
                                   "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False)
            outputs.append({"agent_id": agent["id"], "name": agent["name"], "title": title, "answer": answer})
            with self.database.transaction() as connection:
                connection.execute("UPDATE task_steps SET status='completed' WHERE id=?", (step_id,))
                self.message_service.insert(connection, agent["id"], "agent", agent["name"], answer, task_id=task_id)
                self.database.emit(connection, "task_step.updated",
                                   {"task_id": task_id, "step_id": step_id, "status": "completed"})
        with self.database.transaction() as connection:
            connection.execute("UPDATE tasks SET status='completed' WHERE id=?", (task_id,))
            self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "completed"})
        return json.dumps({"task_id": task_id, "status": "completed", "outputs": outputs}, ensure_ascii=False)

    async def _group(self, request: str, group_id: str) -> str:
        """Send an explicit assignment to a group and execute its own team loop."""
        group = self.database.group(group_id)
        if not group or group["status"] != "active":
            raise ValueError("delegation group is unavailable")
        task_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO tasks VALUES (?, ?, ?, 'running', ?)",
                               (task_id, group_id, request, utc_now()))
            self.message_service.insert(connection, group_id, "system", "小未",
                                        f"小未分派任务：{request}", task_id=task_id)
            self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "running"})
        params = RunParams.from_platform("schedule", {**group, "kind": TEAM},
                                         request, f"delegate:{task_id}")
        task = TaskFactory().create(params)
        try:
            completed = await self.team_runtime.run(task)
            if not completed:
                raise RuntimeError("team produced no completed replies")
        except asyncio.CancelledError:
            with self.database.transaction() as connection:
                connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
                self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "failed"})
            raise
        except Exception as error:
            with self.database.transaction() as connection:
                connection.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
                self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "failed"})
            return json.dumps({"task_id": task_id, "status": "failed",
                               "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False)
        with self.database.transaction() as connection:
            connection.execute("UPDATE tasks SET status='completed' WHERE id=?", (task_id,))
            self.database.emit(connection, "task.updated", {"task_id": task_id, "status": "completed"})
        return json.dumps({"task_id": task_id, "status": "completed", "group_id": group_id,
                           "recent_messages": self.database.messages(group_id, 5)}, ensure_ascii=False)
