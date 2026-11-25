"""Extract video frames and ask the configured vision model to interpret them."""

from futurework.integrations.model_gateway.video import VideoGateway


async def run(arguments: dict, config: dict) -> str:
    """Analyze one workspace video without exposing local paths to a cloud model."""
    return await VideoGateway(config).analyze(arguments["source"], arguments.get("prompt", ""))
