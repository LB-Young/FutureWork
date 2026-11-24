"""Create Team definitions and persist their group conversation identity."""

import json
from uuid import uuid4

from futurework.database import utc_now


class GroupServiceError(Exception):
    """A rejected Team configuration with an API mappable status."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class GroupService:
    """Validate and create groups using loaded config and Agent records."""

    def __init__(self, database, config: dict, config_store) -> None:
        self.database = database
        self.config = config
        self.config_store = config_store

    def create(self, name: str, member_ids: list[str], mode: str) -> dict:
        """Persist a group and its TOML definition in one rollback batch."""
        members = list(dict.fromkeys(member_ids))
        if not name.strip() or len(name.strip()) > self.config["limits"]["max_group_name_chars"] or len(members) > self.config["limits"]["max_group_members"]:
            raise GroupServiceError(422, "invalid group name or member count")
        if mode not in {"swarm", "controlled"}:
            raise GroupServiceError(422, "invalid group mode")
        agents = [self.database.agent(member) for member in members]
        if any(not agent or agent["status"] != "active" for agent in agents):
            raise GroupServiceError(422, "group contains unknown agent")
        group_id = str(uuid4())
        group = {"id": group_id, "name": name.strip(), "role": "、".join(agent["name"] for agent in agents),
                 "icon": name.strip()[0], "color": self.config["ui"]["default_agent_color"],
                 "ink": self.config["ui"]["default_agent_ink"], "members": members,
                 "status": "active", "mode": mode}
        with self.config_store.batch() as write_config, self.database.transaction() as connection:
            connection.execute("INSERT INTO groups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (group_id, group["name"], group["role"], group["icon"], group["color"],
                                group["ink"], json.dumps(members), utc_now(), "active", mode))
            write_config("teams", group)
            self.database.emit(connection, "group.created", {"group_id": group_id})
        return group
