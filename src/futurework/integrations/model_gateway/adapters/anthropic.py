"""Call the Anthropic Messages API while keeping the gateway message contract."""

import os

import httpx


async def generate(provider: dict, model: dict, messages: list[dict], options: dict) -> str:
    """Translate system and conversation messages into Anthropic's request format."""
    env_name = provider["api_key_env"]
    key = os.environ.get(env_name)
    if not key:
        raise RuntimeError(f"缺少模型密钥环境变量 {env_name}")
    system = "\n".join(item["content"] for item in messages if item["role"] == "system")
    turns = [item for item in messages if item["role"] != "system"]
    async with httpx.AsyncClient(timeout=options["timeout_seconds"]) as client:
        response = await client.post(
            provider["base_url"].rstrip("/") + "/v1/messages",
            headers={"x-api-key": key, "anthropic-version": provider.get("api_version", "2023-06-01")},
            json={"model": model["remote_id"], "system": system, "messages": turns,
                  "temperature": options["temperature"], "max_tokens": options["max_output_tokens"]},
        )
        response.raise_for_status()
        blocks = response.json()["content"]
    answer = "\n".join(block["text"] for block in blocks if block.get("type") == "text")
    if not answer.strip():
        raise RuntimeError("模型返回了空内容")
    return answer.strip()
