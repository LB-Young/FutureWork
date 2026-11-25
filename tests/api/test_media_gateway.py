"""Exercise real media request protocols with deterministic provider responses."""

import asyncio
import base64

import httpx
import pytest

from futurework.config import load_config
from futurework.home import ensure_home
from futurework.integrations.model_gateway.media import MediaGateway
from futurework.integrations.model_gateway.vision import VisionGateway
from futurework.integrations.model_gateway.credentials import api_key
from futurework.api.app import create_app
from fastapi.testclient import TestClient


def test_dashscope_media_polling(tmp_path, monkeypatch):
    """The generated task ID must be polled and the final URL returned."""
    config = load_config(ensure_home(tmp_path))
    config["media"]["poll_interval_seconds"] = 0.001
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only")
    calls = []
    def respond(request):
        calls.append(request)
        if request.method == "POST":
            assert request.headers["X-DashScope-Async"] == "enable"
            return httpx.Response(200, json={"output": {"task_id": "task-1", "task_status": "PENDING"}})
        return httpx.Response(200, json={"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://example.com/image.png"}]}})
    result = asyncio.run(MediaGateway(config, httpx.MockTransport(respond)).generate("image_generation", "一只猫"))
    assert result == {"status": "SUCCEEDED", "task_id": "task-1", "urls": ["https://example.com/image.png"], "saved_paths": []}
    assert [item.method for item in calls] == ["POST", "GET"]


def test_openrouter_base64_image(tmp_path, monkeypatch):
    """OpenRouter base64 responses must yield a user-owned media file."""
    config = load_config(ensure_home(tmp_path))
    config["media"]["aliases"]["image_generation"] = "openrouter_image"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    content = b"\x89PNG\r\n\x1a\n"
    def respond(request):
        assert request.url.path.endswith("/images")
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(content).decode()}]})
    result = asyncio.run(MediaGateway(config, httpx.MockTransport(respond)).generate("image_generation", "一只猫"))
    assert result["urls"] == []
    assert len(result["saved_paths"]) == 1
    assert __import__("pathlib").Path(result["saved_paths"][0]).read_bytes() == content


def test_vision_workspace_boundary(tmp_path):
    """Visual models may read image files only from the user workspace."""
    config = load_config(ensure_home(tmp_path))
    image = tmp_path / "workspace" / "picture.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    gateway = VisionGateway(config)
    assert gateway._image_url("picture.png").startswith("data:image/png;base64,")
    with pytest.raises(ValueError):
        gateway._image_url("../models.toml")


def test_upload_image_for_vision(tmp_path):
    """The browser attachment endpoint stores a path the vision tool can read."""
    app = create_app(tmp_path)
    image = b"\x89PNG\r\n\x1a\n"
    with TestClient(app) as client:
        response = client.post("/api/v1/images", json={"filename": "example.png", "media_type": "image/png",
                                                      "data_base64": base64.b64encode(image).decode()})
        assert response.status_code == 201
        relative = response.json()["path"]
        assert (tmp_path / "workspace" / relative).read_bytes() == image
        assert client.post("/api/v1/images", json={"filename": "bad", "media_type": "text/plain", "data_base64": "YQ=="}).status_code == 422


def test_bamboo_credential_reference(tmp_path, monkeypatch):
    """The named local key is resolved at runtime and environment wins."""
    root = tmp_path / ".bamboo" / "configs"
    root.mkdir(parents=True)
    (root / "models.yaml").write_text("models:\n  named-model:\n    api_key: test-local-key\n", encoding="utf-8")
    monkeypatch.setattr("futurework.integrations.model_gateway.credentials.Path.home", lambda: tmp_path)
    provider = {"api_key_env": "FUTUREWORK_TEST_KEY", "bamboo_model": "named-model"}
    assert api_key(provider) == "test-local-key"
    monkeypatch.setenv("FUTUREWORK_TEST_KEY", "test-env-key")
    assert api_key(provider) == "test-env-key"
    (root / "models.yaml").write_text('models:\n  named-model:\n    api_key: "${BAMBOO_TEST_KEY}"\n', encoding="utf-8")
    assert api_key({"bamboo_model": "named-model"}) == ""
    monkeypatch.setenv("BAMBOO_TEST_KEY", "resolved-key")
    assert api_key({"bamboo_model": "named-model"}) == "resolved-key"
    monkeypatch.delenv("BAMBOO_TEST_KEY")
    (tmp_path / ".bamboo" / ".env").write_text("BAMBOO_TEST_KEY=local-env-key\n", encoding="utf-8")
    assert api_key({"bamboo_model": "named-model"}) == "local-env-key"
