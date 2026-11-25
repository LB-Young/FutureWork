"""Invoke a configured media model and return generated URLs or saved images."""

import json

from futurework.integrations.model_gateway.media import MediaGateway


async def run(arguments: dict, config: dict) -> str:
    """Run a single media task with the caller's declared kind and prompt."""
    result = await MediaGateway(config).generate(arguments["kind"], arguments["prompt"],
                                                 arguments.get("image_url", ""))
    return json.dumps(result, ensure_ascii=False)
