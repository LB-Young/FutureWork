"""Call an OpenAI compatible Chat Completions endpoint for text responses."""

import json
import os

import httpx

from futurework.integrations.model_gateway.types import ModelRequest, ModelResult, ToolCall


async def generate(request: ModelRequest, provider: dict, model: dict, options: dict) -> ModelResult:
    """Send an OpenAI compatible Chat Completions request."""
    env_name = provider.get("api_key_env", "")
    key = os.environ.get(env_name) if env_name else ""
    if not key and not provider.get("allow_no_key", False):
        raise RuntimeError(f"缺少模型密钥环境变量 {env_name}")
    url = provider["base_url"].rstrip("/") + "/chat/completions"
    body = {"model": model["remote_id"], "messages": request.messages,
            "max_tokens": model.get("max_output_tokens", options["max_output_tokens"])}
    if model.get("temperature", options.get("temperature")) is not None:
        body["temperature"] = model.get("temperature", options["temperature"])
    if request.tools and model.get("supports_tools", True):
        body["tools"] = request.tools
    body.update(model.get("extra_body", {}))
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    headers.update(provider.get("extra_headers", {}))
    async with httpx.AsyncClient(timeout=options["timeout_seconds"]) as client:
        response = await client.post(
            url, headers=headers, json=body,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
    content = message.get("content") or ""
    calls = [ToolCall(id=item["id"], name=item["function"]["name"],
                      arguments=json.loads(item["function"].get("arguments") or "{}"))
             for item in message.get("tool_calls", [])]
    if not isinstance(content, str) or (not content.strip() and not calls):
        raise RuntimeError("模型返回了空内容")
    return ModelResult(text=content.strip(), tool_calls=calls)
