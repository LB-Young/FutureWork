"""Call the Anthropic Messages API while keeping the gateway message contract."""

import json

import httpx

from futurework.integrations.model_gateway.types import ModelRequest, ModelResult, ToolCall
from futurework.integrations.model_gateway.adapters.base import ModelAdapter
from futurework.integrations.model_gateway.credentials import api_key


class AnthropicAdapter(ModelAdapter):
    """Translate requests for the configured provider instance."""

    async def generate(self, request: ModelRequest) -> ModelResult:
        """Translate system and conversation messages into Anthropic's request format."""
        provider, model, options = self.provider, self.model, self.options
        env_name = provider["api_key_env"]
        key = api_key(provider)
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
                content = item["content"]
                if isinstance(content, list):
                    converted = []
                    for block in content:
                        if block.get("type") == "text":
                            converted.append(block)
                        elif block.get("type") == "image_url":
                            source = block["image_url"]["url"]
                            if source.startswith("data:image/") and ";base64," in source:
                                header, encoded = source.split(",", 1)
                                converted.append({"type": "image", "source": {"type": "base64", "media_type": header[5:].split(";", 1)[0], "data": encoded}})
                            elif source.startswith("https://"):
                                converted.append({"type": "image", "source": {"type": "url", "url": source}})
                            else:
                                raise ValueError("不支持的 Anthropic 图片地址")
                    content = converted
                turns.append({"role": item["role"], "content": content})
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


async def generate(request: ModelRequest, provider: dict, model: dict, options: dict) -> ModelResult:
    """Compatibility entry point for direct adapter callers."""
    return await AnthropicAdapter(provider, model, options).generate(request)
