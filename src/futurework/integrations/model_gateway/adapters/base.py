"""Define the provider adapter object shared by model gateway implementations."""

from abc import ABC, abstractmethod

from futurework.integrations.model_gateway.types import ModelRequest, ModelResult


class ModelAdapter(ABC):
    """Hold one provider/model configuration and translate its request protocol."""

    def __init__(self, provider: dict, model: dict, options: dict) -> None:
        self.provider = provider
        self.model = model
        self.options = options

    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelResult:
        """Send one provider-specific request and return a normalized result."""
