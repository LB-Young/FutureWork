"""Submit one terminal message to the shared in-process FutureWork API."""

import asyncio
from uuid import uuid4

import httpx

from futurework.api.app import create_app


async def chat(home, conversation: str, message: str) -> str:
    """Reuse the Web task ingress and read the resulting conversation."""
    app = create_app(home, include_web=False, source="cli")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://futurework.local") as client:
        response = await client.post(f"/api/v1/conversations/{conversation}/messages",
                                     json={"client_message_id": str(uuid4()), "body": message})
        response.raise_for_status()
        messages = await client.get(f"/api/v1/conversations/{conversation}/messages")
        messages.raise_for_status()
        return messages.json()[-1]["text"]


def run(home, conversation: str, message: str) -> str:
    """Bridge the synchronous terminal command into the async task chain."""
    return asyncio.run(chat(home, conversation, message))
