"""Route Agent model aliases with bounded retries for transient provider errors."""

import asyncio

import httpx

from futurework.integrations.model_gateway.adapters import anthropic, openai_chat
from futurework.integrations.model_gateway.types import ModelRequest, ModelResult


ADAPTERS = {"openai_chat": openai_chat.generate, "anthropic_messages": anthropic.generate}


async def generate(request: ModelRequest, config: dict) -> ModelResult:
    """Resolve a typed request's alias and call the matching text adapter."""
    model = config["models"]["models"][request.alias]
    provider = config["models"]["providers"][model["provider"]]
    options = config["model"]
    for attempt in range(options["max_retries"] + 1):
        try:
            return await ADAPTERS[provider["adapter"]](request, provider, model, options)
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
