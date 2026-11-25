"""Resolve user workspace images into provider-compatible visual message blocks."""

import base64
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

from futurework.integrations.model_gateway.gateway import ModelGateway
from futurework.integrations.model_gateway.types import ModelRequest


class VisionGateway:
    """Analyze a workspace image or HTTPS image with a configured vision model."""

    def __init__(self, config: dict, gateway: ModelGateway | None = None) -> None:
        self.config = config
        self.gateway = gateway or ModelGateway(config)

    def _image_url(self, source: str) -> str:
        parts = urlsplit(source)
        if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password:
            return source
        if parts.scheme or source.startswith("//"):
            raise ValueError("图片地址必须是 HTTPS 或工作区文件路径")
        root = (Path(self.config["home"]) / "workspace").resolve()
        path = (root / source).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("图片文件必须位于用户工作区")
        if path.stat().st_size > self.config["media"]["max_image_bytes"]:
            raise ValueError("图片文件超过大小限制")
        mime, _ = mimetypes.guess_type(path.name)
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError("不支持的图片格式")
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

    async def analyze(self, source: str, prompt: str) -> str:
        """Send visual input to a vision alias; return only the provider's text."""
        alias = self.config["media"]["aliases"].get("image_understanding", "")
        model = self.config["models"]["models"].get(alias, {})
        if model.get("model_type") != "vision":
            raise ValueError("未配置有效的图片理解模型")
        content = [{"type": "text", "text": prompt or "请描述并分析这张图片。"},
                   {"type": "image_url", "image_url": {"url": self._image_url(source)}}]
        result = await self.gateway.generate(ModelRequest(alias, [{"role": "user", "content": content}]))
        return result.text
