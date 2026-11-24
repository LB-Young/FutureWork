"""Call an OpenAI compatible Chat Completions endpoint for text responses."""

import os

import httpx


async def generate(provider: dict, model: dict, messages: list[dict], options: dict) -> str:
    """Send a text-only request to the configured provider and return its answer."""
    env_name = provider["api_key_env"]
    key = os.environ.get(env_name)
    if not key:
        raise RuntimeError(f"缺少模型密钥环境变量 {env_name}")
    url = provider["base_url"].rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=options["timeout_seconds"]) as client:
        response = await client.post(
            url, headers={"Authorization": f"Bearer {key}"},
            json={"model": model["remote_id"], "messages": messages,
                  "temperature": options["temperature"], "max_tokens": options["max_output_tokens"]},
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("模型返回了空内容")
    return content.strip()
