"""Invoke the configured visual model for a scoped user image."""

from futurework.integrations.model_gateway.vision import VisionGateway


async def run(arguments: dict, config: dict) -> str:
    """Analyze one HTTPS image or workspace image file."""
    return await VisionGateway(config).analyze(arguments["image_url"], arguments.get("prompt", ""))
