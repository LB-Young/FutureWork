"""Trim and resize workspace videos with bounded FFmpeg arguments."""

import json

from futurework.integrations.model_gateway.video import VideoGateway


async def run(arguments: dict, config: dict) -> str:
    """Return a workspace-relative path to the edited MP4 file."""
    path = await VideoGateway(config).edit(arguments["source"], arguments["start_seconds"],
                                           arguments["duration_seconds"], arguments.get("width", 0))
    return json.dumps({"output_path": path, "artifact_url": "/api/v1/artifacts/outputs/" + path.split("/")[-1]}, ensure_ascii=False)
