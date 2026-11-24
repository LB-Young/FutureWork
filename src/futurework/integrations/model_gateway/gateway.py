"""Route Agent model aliases with bounded retries for transient provider errors."""

import asyncio

import httpx

from futurework.integrations.model_gateway.adapters import anthropic, openai_chat


ADAPTERS = {"openai_chat": openai_chat.generate, "anthropic_messages": anthropic.generate}


async def generate(agent: dict, messages: list[dict], config: dict) -> str:
    """Resolve the Agent's alias and call the matching text adapter."""
    alias = agent["model"]
    model = config["models"]["models"][alias]
    provider = config["models"]["providers"][model["provider"]]
    options = config["model"]
    for attempt in range(options["max_retries"] + 1):
        try:
            return await ADAPTERS[provider["adapter"]](provider, model, messages, options)
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in {429, 500, 502, 503, 504} or attempt == options["max_retries"]:
                raise
            retry_after = error.response.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else options["retry_backoff_seconds"] * 2 ** attempt
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt == options["max_retries"]:
                raise
            delay = options["retry_backoff_seconds"] * 2 ** attempt
        await asyncio.sleep(min(delay, options["timeout_seconds"]))
    raise RuntimeError("模型重试次数已耗尽")
