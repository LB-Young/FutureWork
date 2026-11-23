import os

import httpx


async def respond(agent: dict, history: list[dict], config: dict) -> str:
    settings = config["model"]
    if settings["provider"] == "mock":
        return settings["mock_reply"]
    api_key = os.environ.get(settings["api_key_env"])
    if not api_key:
        raise RuntimeError(f"missing model API key: {settings['api_key_env']}")
    messages = [{"role": "system", "content": f"{settings['system_prompt']} 你的名字是{agent['name']}，职责是{agent['role']}。"}]
    messages.extend({"role": "user" if item["from"] == "me" else "assistant", "content": item["text"]} for item in history)
    async with httpx.AsyncClient(timeout=settings["timeout_seconds"]) as client:
        response = await client.post(
            settings["api_url"],
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": agent["model"],
                "messages": messages,
                "temperature": settings["temperature"],
                "max_tokens": settings["max_output_tokens"],
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("model returned an empty response")
        return content.strip()
