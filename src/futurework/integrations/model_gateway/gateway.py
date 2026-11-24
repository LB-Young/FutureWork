"""Route Agent model aliases with bounded retries for transient provider errors."""

import asyncio

import httpx

from futurework.integrations.model_gateway.adapters import anthropic, http_provider, openai_chat
from futurework.integrations.model_gateway.types import ModelRequest, ModelResult


ADAPTERS = {"openai_chat": openai_chat.OpenAIChatAdapter,
            "anthropic_messages": anthropic.AnthropicAdapter,
            "http_provider": http_provider.HttpProviderAdapter}


class ModelGateway:
    """Own provider routing and retry policy for one loaded configuration."""

    def __init__(self, config: dict, adapters: dict | None = None) -> None:
        self.config = config
        self.adapters = adapters if adapters is not None else ADAPTERS
        self._clients = {}

    def client_for(self, alias: str):
        """Create and reuse one protocol adapter for a configured model alias."""
        if alias not in self._clients:
            model = self.config["models"]["models"][alias]
            provider = self.config["models"]["providers"][model["provider"]]
            self._clients[alias] = self.adapters[provider["adapter"]](provider, model, self.config["model"])
        return self._clients[alias]

    def supports_tools(self, alias: str) -> bool:
        """Read the selected model's declared tool capability."""
        return self.config["models"]["models"][alias].get("supports_tools", True)

    async def generate(self, request: ModelRequest) -> ModelResult:
        """Resolve a typed request's alias and retry only transient failures."""
        client = self.client_for(request.alias)
        options = self.config["model"]
        for attempt in range(options["max_retries"] + 1):
            try:
                return await client.generate(request)
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


async def generate(request: ModelRequest, config: dict) -> ModelResult:
    """Compatibility entry point for existing provider integrations."""
    return await ModelGateway(config).generate(request)
