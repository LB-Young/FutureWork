"""Persist scoped conversation messages and publish their creation events."""

from uuid import uuid4

from futurework.database import utc_now


class MessageService:
    """Own the message write contract shared by API and runtimes."""

    def __init__(self, database) -> None:
        self.database = database

    def insert(self, connection, conversation_id: str, sender_kind: str, speaker: str,
               text: str, client_message_id: str | None = None,
               approval_id: str | None = None, task_id: str | None = None) -> dict:
        """Write a message inside the caller's transaction and emit its event."""
        message = {
            "id": str(uuid4()), "conversation_id": conversation_id, "sender_kind": sender_kind,
            "speaker": speaker, "text": text, "client_message_id": client_message_id,
            "approval_id": approval_id, "task_id": task_id, "created_at": utc_now(),
        }
        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(message.values()))
        self.database.emit(connection, "message.created", {"conversation_id": conversation_id, "message_id": message["id"]})
        return message
