"""Call Bamboo's deployed HTTP model proxy with its request envelope."""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

import httpx

from futurework.integrations.model_gateway.types import ModelRequest, ModelResult, ToolCall


ENV_REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _resolve(value: str) -> str:
    """Resolve a full environment reference only when this provider is used."""
    match = ENV_REFERENCE.fullmatch(value)
    if not match:
        return value
    resolved = os.environ.get(match.group(1), "")
    if not resolved:
        raise RuntimeError(f"缺少模型配置环境变量 {match.group(1)}")
    return resolved


def _endpoint(provider: dict) -> str:
    """Use the configured proxy endpoint verbatim after URL policy checks."""
    url = _resolve(provider["base_url"])
    try:
        parts = urlsplit(url)
        loopback = parts.hostname in {"localhost", "127.0.0.1", "::1"}
        allowed = parts.scheme == "https" or (parts.scheme == "http" and (loopback or provider.get("allow_insecure_http") is True))
        if not parts.hostname or not allowed or parts.username or parts.password or parts.fragment:
            raise ValueError("invalid endpoint")
    except ValueError as error:
        raise RuntimeError("HTTP 模型代理地址无效；局域网明文 HTTP 需要 allow_insecure_http = true") from error
    return url


def _content(value: object) -> list[dict]:
    """Translate one text message into the proxy's content-block format."""
    if not value:
        return []
    return [{"type": "text", "text": value}] if isinstance(value, str) else value


def _messages(request: ModelRequest) -> list[dict]:
    """Serialize system, user, assistant, and tool turns for the proxy."""
    result = []
    for item in request.messages:
        message = {"role": item["role"], "content": _content(item.get("content"))}
        if item["role"] == "tool":
            message["tool_call_id"] = item["tool_call_id"]
        if item.get("tool_calls"):
            message["tool_calls"] = item["tool_calls"]
        result.append(message)
    return result


def _detail(data: dict) -> str:
    """Extract a bounded provider error without exposing the request headers."""
    for key in ("errorMsg", "error_msg", "message", "msg"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value[:500]
    return "未知业务错误"


def _parse(data: object) -> ModelResult:
    """Accept either a result wrapper or a flat Chat Completion response."""
    if not isinstance(data, dict):
        raise RuntimeError("HTTP 模型代理返回了无效响应")
    if data.get("success") is not True and data.get("code") != 200 and any(key in data for key in ("success", "code", "errorCode")):
        raise RuntimeError(f"HTTP 模型代理业务错误：{_detail(data)}")
    completion = data.get("result") if isinstance(data.get("result"), dict) else data
    try:
        message = completion["choices"][0]["message"]
        raw_content = message.get("content")
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, list):
            content = "".join(block["text"] for block in raw_content if isinstance(block, dict) and isinstance(block.get("text"), str))
        else:
            content = ""
        calls = []
        for index, item in enumerate(message.get("tool_calls") or []):
            function = item["function"]
            arguments = function.get("arguments", "{}")
            arguments = json.loads(arguments or "{}") if isinstance(arguments, str) else arguments
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
            calls.append(ToolCall(id=item.get("id") or f"tool_call_{index}", name=function["name"], arguments=arguments))
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError("HTTP 模型代理返回了无效的 Chat Completion") from error
    if not content.strip() and not calls:
        raise RuntimeError("HTTP 模型代理返回了空内容")
    return ModelResult(text=content.strip(), tool_calls=calls)


async def generate(request: ModelRequest, provider: dict, model: dict, options: dict) -> ModelResult:
    """POST a Bamboo-compatible envelope to the exact configured endpoint."""
    env_name = provider.get("api_key_env", "")
    key = os.environ.get(env_name, "") if env_name else ""
    if not key and not provider.get("allow_no_key", False):
        raise RuntimeError(f"缺少模型密钥环境变量 {env_name}")
    headers = {"Content-Type": "application/json"}
    headers.update({name: _resolve(value) for name, value in provider.get("extra_headers", {}).items()})
    headers.update({name: _resolve(value) for name, value in model.get("extra_headers", {}).items()})
    if key:
        headers.setdefault("Authorization", f"Bearer {key}")

    extra = model.get("extra_body", {})
    overrides = extra.get("request", {})
    if not isinstance(overrides, dict):
        raise ValueError("extra_body.request 必须是 TOML 表")
    request_body = {"max_completion_tokens": model.get("max_output_tokens", options["max_output_tokens"]),
                    "messages": _messages(request), **overrides}
    temperature = model.get("temperature", options.get("temperature"))
    if temperature is not None:
        request_body["temperature"] = temperature
    if request.tools and model.get("supports_tools", True):
        request_body["tools"] = request.tools
    payload = {"model": model["remote_id"].removeprefix("local_"),
               "request": request_body, "timeout": int(extra.get("timeout", 30))}
    payload.update({name: value for name, value in extra.items() if name not in {"request", "timeout"}})
    async with httpx.AsyncClient(timeout=model.get("timeout_seconds", options["timeout_seconds"])) as client:
        response = await client.post(_endpoint(provider), headers=headers, json=payload)
        response.raise_for_status()
        return _parse(response.json())
