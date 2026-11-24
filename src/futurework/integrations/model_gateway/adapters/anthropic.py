"""Call the Anthropic Messages API while keeping the gateway message contract."""

import json
import os

import httpx

from futurework.integrations.model_gateway.types import ModelRequest, ModelResult, ToolCall


async def generate(request: ModelRequest, provider: dict, model: dict, options: dict) -> ModelResult:
    """Translate system and conversation messages into Anthropic's request format."""
    env_name = provider["api_key_env"]
    key = os.environ.get(env_name)
    if not key:
        raise RuntimeError(f"缺少模型密钥环境变量 {env_name}")
    system = "\n".join(item["content"] for item in request.messages if item["role"] == "system")
    turns = []
    for item in request.messages:
        if item["role"] == "system":
            continue
        if item["role"] == "tool":
            turns.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": item["tool_call_id"], "content": item["content"]}]})
        elif item["role"] == "assistant" and item.get("tool_calls"):
            blocks = ([{"type": "text", "text": item["content"]}] if item.get("content") else [])
            blocks.extend({"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                           "input": json.loads(call["function"]["arguments"])} for call in item["tool_calls"])
            turns.append({"role": "assistant", "content": blocks})
        else:
            turns.append({"role": item["role"], "content": item["content"]})
    body = {"model": model["remote_id"], "system": system, "messages": turns,
            "max_tokens": model.get("max_output_tokens", options["max_output_tokens"])}
    if model.get("temperature", options.get("temperature")) is not None:
        body["temperature"] = model.get("temperature", options["temperature"])
    if request.tools and model.get("supports_tools", True):
        body["tools"] = [{"name": item["function"]["name"], "description": item["function"]["description"],
                          "input_schema": item["function"]["parameters"]} for item in request.tools]
    async with httpx.AsyncClient(timeout=options["timeout_seconds"]) as client:
        response = await client.post(
            provider["base_url"].rstrip("/") + "/v1/messages",
            headers={"x-api-key": key, "anthropic-version": provider.get("api_version", "2023-06-01")},
            json=body,
        )
        response.raise_for_status()
        blocks = response.json()["content"]
    answer = "\n".join(block["text"] for block in blocks if block.get("type") == "text")
    calls = [ToolCall(id=block["id"], name=block["name"], arguments=block["input"])
             for block in blocks if block.get("type") == "tool_use"]
    if not answer.strip() and not calls:
        raise RuntimeError("模型返回了空内容")
    return ModelResult(text=answer.strip(), tool_calls=calls)
