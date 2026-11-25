"""Analyze sampled video frames and perform bounded local edits using FFmpeg."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from futurework.integrations.model_gateway.vision import VisionGateway


class VideoGateway:
    """Keep video processing inside the user workspace with explicit limits."""

    def __init__(self, config: dict, vision: VisionGateway | None = None) -> None:
        self.config = config
        self.settings = config["media"]
        self.root = (Path(config["home"]) / "workspace").resolve()
        self.vision = vision or VisionGateway(config)

    def _source(self, source: str) -> Path:
        path = (self.root / source).resolve()
        if not path.is_relative_to(self.root) or not path.is_file() or path.suffix.lower() not in {".mp4", ".mov", ".webm"}:
            raise ValueError("视频必须是工作区内的 MP4、MOV 或 WebM 文件")
        if path.stat().st_size > self.settings["max_video_bytes"]:
            raise ValueError("视频文件超过大小限制")
        return path

    async def _command(self, *arguments: str) -> bytes:
        process = await asyncio.create_subprocess_exec(*arguments, stdin=asyncio.subprocess.DEVNULL,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            output, error = await asyncio.wait_for(process.communicate(), self.settings["video_timeout_seconds"])
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("视频处理超时")
        if process.returncode:
            raise RuntimeError("视频处理失败：" + error.decode("utf-8", "replace")[:300])
        return output

    async def analyze(self, source: str, prompt: str) -> str:
        """Sample a few frames and ask the configured vision model about them."""
        path = self._source(source)
        raw = await self._command(self.settings["ffprobe_path"], "-v", "error", "-show_entries",
                                  "format=duration", "-of", "json", str(path))
        duration = float(json.loads(raw)["format"]["duration"])
        if duration <= 0:
            raise ValueError("视频时长无效")
        count = min(self.settings["max_video_frames"], max(1, int(duration)))
        times = [max(0, duration * (index + 0.5) / count) for index in range(count)]
        with tempfile.TemporaryDirectory(prefix=".futurework-frames-", dir=self.root) as directory:
            frames = []
            for index, second in enumerate(times):
                frame = Path(directory) / f"frame-{index}.jpg"
                await self._command(self.settings["ffmpeg_path"], "-nostdin", "-loglevel", "error", "-ss", str(second),
                                    "-i", str(path), "-frames:v", "1", "-vf", f"scale={self.settings['video_frame_width']}:-2",
                                    "-y", str(frame))
                frames.append(str(frame))
            return await self.vision.analyze_many(frames, f"以下是视频按时间顺序抽取的 {count} 帧。{prompt or '请分析视频内容。'}")

    async def edit(self, source: str, start_seconds: int, duration_seconds: int, width: int = 0) -> str:
        """Trim and optionally resize a video without accepting shell input."""
        path = self._source(source)
        if type(start_seconds) is not int or start_seconds < 0 or type(duration_seconds) is not int or \
           not 1 <= duration_seconds <= self.settings["max_edit_seconds"]:
            raise ValueError("视频裁剪时间无效")
        if type(width) is not int or width < 0 or width > self.settings["max_video_width"] or (width and width % 2):
            raise ValueError("视频宽度必须是合理的偶数")
        output_dir = self.root / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{uuid4().hex}.mp4"
        command = [self.settings["ffmpeg_path"], "-nostdin", "-loglevel", "error", "-ss", str(start_seconds),
                   "-i", str(path), "-t", str(duration_seconds)]
        if width:
            command.extend(["-vf", f"scale={width}:-2"])
        command.extend(["-c:v", "libx264", "-c:a", "aac", "-y", str(output)])
        try:
            await self._command(*command)
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return str(output.relative_to(self.root))
