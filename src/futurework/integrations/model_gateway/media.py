"""Execute configured DashScope and OpenRouter media models with bounded polling."""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from uuid import uuid4

import httpx
from futurework.integrations.model_gateway.credentials import api_key


class MediaGateway:
    """Resolve media aliases and normalize generated URLs or binary images."""

    def __init__(self, config: dict, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self.transport = transport

    def alias_for(self, kind: str) -> str:
        alias = self.config["media"]["aliases"].get(kind, "")
        if not alias or alias not in self.config["models"]["models"]:
            raise ValueError(f"未配置 {kind} 媒体模型别名")
        model = self.config["models"]["models"][alias]
        if model.get("model_type") != kind:
            raise ValueError(f"模型 {alias} 的类型不是 {kind}")
        return alias

    async def generate(self, kind: str, prompt: str, image_url: str = "") -> dict:
        """Send a media request; never send generated content or provider keys to logs."""
        if not prompt.strip():
            raise ValueError("媒体提示词不能为空")
        alias = self.alias_for(kind)
        model = self.config["models"]["models"][alias]
        provider = self.config["models"]["providers"][model["provider"]]
        key = api_key(provider)
        if not key and not provider.get("allow_no_key", False):
            raise RuntimeError(f"缺少模型密钥环境变量 {provider.get('api_key_env', '')}")
        if image_url and kind != "image_edit":
            raise ValueError("只有图片编辑接受原图")
        if kind == "image_edit" and not image_url:
            raise ValueError("图片编辑需要 image_url")
        extra = model.get("extra_body", {})
        protocol = extra.get("protocol", "")
        base = model.get("base_url", provider["base_url"])
        headers = {"Authorization": f"Bearer {key}", **provider.get("extra_headers", {})}
        timeout = self.config["media"]["request_timeout_seconds"]
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            if protocol == "dashscope_async":
                inputs = {"prompt": prompt}
                if image_url:
                    inputs[extra.get("input_fields", {}).get("image_url", "image_url")] = image_url
                payload = {"model": model["remote_id"], "input": inputs}
                parameters = extra.get("parameters", {})
                if parameters:
                    payload["parameters"] = parameters
                response = await client.post(base.rstrip("/") + "/" + extra["endpoint"].lstrip("/"),
                                             headers={**headers, "X-DashScope-Async": "enable"}, json=payload)
                response.raise_for_status()
                data = response.json()
                task_id = data.get("output", {}).get("task_id")
                if not task_id:
                    raise RuntimeError("媒体服务未返回任务 ID")
                deadline = time.monotonic() + self.config["media"]["task_timeout_seconds"]
                while data.get("output", {}).get("task_status") not in {"SUCCEEDED", "FAILED", "CANCELED"}:
                    if time.monotonic() >= deadline:
                        return {"status": "PENDING", "task_id": task_id, "urls": [], "saved_paths": []}
                    await asyncio.sleep(self.config["media"]["poll_interval_seconds"])
                    response = await client.get(base.rstrip("/") + "/tasks/" + task_id, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                status = data["output"]["task_status"]
                if status != "SUCCEEDED":
                    raise RuntimeError(f"媒体任务 {task_id} 失败：{status}")
            elif protocol == "openrouter_images":
                payload = {"model": model["remote_id"], "prompt": prompt, **extra.get("parameters", {})}
                response = await client.post(base.rstrip("/") + "/" + extra.get("endpoint", "/images").lstrip("/"),
                                             headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                task_id = ""
            else:
                raise ValueError(f"不支持的媒体协议：{protocol}")
            urls = self._urls(data)
            saved = self._save_base64(data)
            return {"status": "SUCCEEDED", "task_id": task_id, "urls": urls, "saved_paths": saved,
                    "artifact_urls": ["/api/v1/artifacts/media/" + Path(path).name for path in saved]}

    @staticmethod
    def _urls(data: object) -> list[str]:
        urls: list[str] = []
        def visit(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"url", "image_url", "video_url", "output_url"} and isinstance(child, str) and child.startswith("https://"):
                        urls.append(child)
                    elif isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(data)
        return list(dict.fromkeys(urls))

    def _save_base64(self, data: object) -> list[str]:
        paths: list[str] = []
        root = Path(self.config["home"]) / "data" / "media"
        def visit(value: object) -> None:
            if isinstance(value, dict):
                encoded = value.get("b64_json")
                if isinstance(encoded, str):
                    raw = encoded.split(",", 1)[-1]
                    content = base64.b64decode(raw, validate=True)
                    if len(content) > self.config["media"]["max_image_bytes"]:
                        raise ValueError("媒体结果超过文件大小限制")
                    root.mkdir(parents=True, exist_ok=True)
                    path = root / f"{uuid4().hex}.png"
                    path.write_bytes(content)
                    paths.append(str(path))
                else:
                    for child in value.values():
                        if isinstance(child, (dict, list)):
                            visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(data)
        return paths
