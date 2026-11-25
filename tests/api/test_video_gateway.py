"""Exercise local video frame extraction and bounded edits with FFmpeg."""

import asyncio
import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from futurework.config import load_config
from futurework.home import ensure_home
from futurework.integrations.model_gateway.video import VideoGateway
from futurework.api.app import create_app
from fastapi.testclient import TestClient


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg unavailable")
def test_video_analyze_and_trim(tmp_path):
    """Video analysis samples real frames; editing saves a valid local MP4."""
    config = load_config(ensure_home(tmp_path))
    source = tmp_path / "workspace" / "clip.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source)], check=True)
    class VisionStub:
        async def analyze_many(self, frames, prompt):
            assert frames and all(Path(frame).is_file() for frame in frames)
            return "蓝色画面"
    gateway = VideoGateway(config, VisionStub())
    assert asyncio.run(gateway.analyze("clip.mp4", "描述视频")) == "蓝色画面"
    output = asyncio.run(gateway.edit("clip.mp4", 0, 1, 160))
    assert (tmp_path / "workspace" / output).is_file()
    with pytest.raises(ValueError):
        asyncio.run(gateway.edit("../models.toml", 0, 1))


def test_video_upload(tmp_path):
    """The web upload endpoint accepts supported video bytes and rejects mismatches."""
    app = create_app(tmp_path)
    content = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16
    with TestClient(app) as client:
        response = client.post("/api/v1/videos", json={"filename": "clip.mp4", "media_type": "video/mp4",
                                                      "data_base64": base64.b64encode(content).decode()})
        assert response.status_code == 201
        assert (tmp_path / "workspace" / response.json()["path"]).read_bytes() == content
        assert client.post("/api/v1/videos", json={"filename": "bad.mp4", "media_type": "video/mp4",
                                                   "data_base64": base64.b64encode(b"not video").decode()}).status_code == 422
