import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decode_agent(row: sqlite3.Row) -> dict:
    agent = dict(row)
    agent["tools"] = json.loads(agent["tools"])
    agent["capabilities"] = json.loads(agent["capabilities"])
    agent["approval"] = bool(agent["approval"])
    return agent


def decode_group(row: sqlite3.Row) -> dict:
    group = dict(row)
    group["members"] = json.loads(group["members"])
    return group


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    @contextmanager
    def transaction(self):
        with self.lock:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def initialize(self, config: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, role TEXT NOT NULL,
                    icon TEXT NOT NULL, color TEXT NOT NULL, ink TEXT NOT NULL,
                    model TEXT NOT NULL, tools TEXT NOT NULL, capabilities TEXT NOT NULL,
                    approval INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                    icon TEXT NOT NULL, color TEXT NOT NULL, ink TEXT NOT NULL,
                    members TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    sender_kind TEXT NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL,
                    client_message_id TEXT UNIQUE, approval_id TEXT, task_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, created_at, id);
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    description TEXT NOT NULL, proposal TEXT NOT NULL,
                    status TEXT NOT NULL, expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL, decided_at TEXT
                );
                CREATE INDEX IF NOT EXISTS approvals_status ON approvals(status, conversation_id);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    request TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_steps (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    capability TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
                    agent_version INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS read_marks (
                    conversation_id TEXT PRIMARY KEY, message_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            step_columns = {row["name"] for row in connection.execute("PRAGMA table_info(task_steps)")}
            if "agent_version" not in step_columns:
                connection.execute("ALTER TABLE task_steps ADD COLUMN agent_version INTEGER NOT NULL DEFAULT 1")
            if connection.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 0:
                for item in config["agents"]["seed"]:
                    self.insert_agent(connection, {**item, "approval": True, "version": 1, "status": "active"})
            if connection.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 0:
                for item in config["groups"]["seed"]:
                    connection.execute(
                        "INSERT INTO groups VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (item["id"], item["name"], item["role"], item["icon"], item["color"],
                         item["ink"], json.dumps(item["members"]), utc_now()),
                    )

    @staticmethod
    def insert_agent(connection: sqlite3.Connection, agent: dict):
        connection.execute(
            "INSERT INTO agents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent["id"], agent["name"], agent["role"], agent["icon"], agent["color"], agent["ink"],
             agent["model"], json.dumps(agent["tools"], ensure_ascii=False),
             json.dumps(agent["capabilities"]), int(agent["approval"]), agent["version"],
             agent["status"], utc_now()),
        )

    @staticmethod
    def emit(connection: sqlite3.Connection, event_type: str, payload: dict):
        connection.execute(
            "INSERT INTO events(type, payload, created_at) VALUES (?, ?, ?)",
            (event_type, json.dumps(payload, ensure_ascii=False), utc_now()),
        )

    def agents(self) -> list[dict]:
        with self.transaction() as connection:
            return [decode_agent(row) for row in connection.execute("SELECT * FROM agents WHERE status='active' ORDER BY created_at, id")]

    def groups(self) -> list[dict]:
        with self.transaction() as connection:
            return [decode_group(row) for row in connection.execute("SELECT * FROM groups ORDER BY created_at, id")]

    def agent(self, agent_id: str) -> dict | None:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
            return decode_agent(row) if row else None

    def group(self, group_id: str) -> dict | None:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
            return decode_group(row) if row else None

    def messages(self, conversation_id: str, limit: int) -> list[dict]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
            return [self.message_dict(connection, row) for row in reversed(rows)]

    @staticmethod
    def message_dict(connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        message = dict(row)
        message["from"] = "me" if message["sender_kind"] == "user" else "them"
        if message["approval_id"]:
            approval = connection.execute("SELECT status, description, expires_at FROM approvals WHERE id=?", (message["approval_id"],)).fetchone()
            message["approval"] = approval["status"] == "pending" and approval["expires_at"] > utc_now() if approval else False
            message["approval_description"] = approval["description"] if approval else ""
        return message

    def inbox(self, config: dict, view: str) -> list[dict]:
        items = [({**agent, "kind": "agent"}) for agent in self.agents()]
        items.extend({**group, "kind": "group"} for group in self.groups())
        with self.transaction() as connection:
            result = []
            for item in items:
                latest = connection.execute(
                    "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (item["id"],)
                ).fetchone()
                pending = connection.execute(
                    "SELECT COUNT(*) FROM approvals WHERE conversation_id=? AND status='pending' AND expires_at>?",
                    (item["id"], utc_now()),
                ).fetchone()[0]
                mark = connection.execute("SELECT message_id FROM read_marks WHERE conversation_id=?", (item["id"],)).fetchone()
                result.append({
                    "id": item["id"], "kind": item["kind"], "text": latest["text"] if latest else "暂无消息，开始对话吧",
                    "time": latest["created_at"] if latest else None,
                    "speaker": latest["speaker"] if latest else None,
                    "approval_count": pending,
                    "unread": bool(latest and latest["sender_kind"] != "user" and (not mark or mark["message_id"] != latest["id"])),
                    "status": "待审批" if pending else "有新消息" if latest else "暂无消息",
                })
        result.sort(key=lambda item: item["time"] or "", reverse=True)
        if view == "approvals":
            return [item for item in result if item["approval_count"]]
        if view == "recent":
            return result[: config["ui"]["recent_limit"]]
        return result

    def events_after(self, sequence: int, limit: int) -> list[dict]:
        with self.transaction() as connection:
            rows = connection.execute("SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT ?", (sequence, limit)).fetchall()
            return [dict(row) for row in rows]
