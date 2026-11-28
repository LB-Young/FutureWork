"""Check that the user .env is private, append-only, and loaded literally."""

import os
import stat

from fastapi.testclient import TestClient

from futurework.adapters.api.app import create_app as create_api_app
from futurework.abilities.tools.skill_create.handler import run as create_skill
from futurework.config import load_config
from futurework.environment import load_environment
from futurework.home import ensure_home


def test_init_creates_private_env_and_loads_values(tmp_path, monkeypatch):
    home = ensure_home(tmp_path / "home")
    path = home / ".env"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    content = path.read_text(encoding="utf-8")
    for name in ("DEEPSEEK_API_KEY", "FUTUREWORK_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                 "HTTP_PROVIDER_BASE_URL", "OPENROUTER_API_KEY"):
        assert f"{name}=" in content
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path.write_text(content.replace("DEEPSEEK_API_KEY=\n", 'DEEPSEEK_API_KEY="test-local-value"\n'))
    load_environment(home)
    assert os.environ["DEEPSEEK_API_KEY"] == "test-local-value"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "process-value")
    load_environment(home)
    assert os.environ["DEEPSEEK_API_KEY"] == "process-value"


def test_init_and_skill_creator_only_append_new_names(tmp_path):
    home = ensure_home(tmp_path / "home")
    path = home / ".env"
    original = path.read_text(encoding="utf-8")
    edited = original.replace("DEEPSEEK_API_KEY=\n", "DEEPSEEK_API_KEY=kept-value\n")
    path.write_text(edited, encoding="utf-8")
    create_skill({"name": "external-skill", "description": "测试环境变量追加",
                  "instructions": "通过 ${NEW_SKILL_API_KEY} 调用服务。"}, load_config(home))
    appended = path.read_text(encoding="utf-8")
    assert appended.startswith(edited)
    assert appended.count("NEW_SKILL_API_KEY=") == 1
    assert "DEEPSEEK_API_KEY=kept-value" in appended
    ensure_home(home)
    assert path.read_text(encoding="utf-8") == appended


def test_values_from_another_home_are_not_reused(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    first = ensure_home(tmp_path / "first")
    path = first / ".env"
    path.write_text(path.read_text().replace("DEEPSEEK_API_KEY=\n", "DEEPSEEK_API_KEY=first-home\n"))
    load_environment(first)
    assert os.environ["DEEPSEEK_API_KEY"] == "first-home"
    ensure_home(tmp_path / "second")
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_headless_api_reads_its_key_from_home_env(tmp_path, monkeypatch):
    monkeypatch.delenv("FUTUREWORK_API_KEY", raising=False)
    home = ensure_home(tmp_path / "home")
    path = home / ".env"
    path.write_text(path.read_text().replace("FUTUREWORK_API_KEY=\n",
                                             "FUTUREWORK_API_KEY=local-api-test-key\n"))
    client = TestClient(create_api_app(home))
    assert client.get("/api/v1/agents").status_code == 401
    assert client.get("/api/v1/agents", headers={
        "Authorization": "Bearer local-api-test-key"}).status_code == 200
