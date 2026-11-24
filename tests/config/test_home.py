"""Verify first use initializes user directories without overwriting manual TOML."""

from futurework.bootstrap import validate_home
from futurework.api.app import create_app
from futurework.home import DIRECTORIES, ensure_home
from fastapi.testclient import TestClient
import pytest


def test_home_is_initialized_and_manual_config_survives(tmp_path):
    home = ensure_home(tmp_path / "custom-home")
    assert all((home / relative / "README.md").is_file() for relative in DIRECTORIES)
    assert "用户配置和运行数据" in (home / "README.md").read_text()
    assert (home / "agents" / "assistant.toml").is_file()
    assert (home / "memory" / "agents" / "research" / "README.md").is_file()
    assert validate_home(home)["teams"]["ideas"]["mode"] == "swarm"
    manual = home / "agents" / "research.toml"
    manual.write_text(manual.read_text().replace('name = "知知"', 'name = "我的研究员"'))
    ensure_home(home)
    assert 'name = "我的研究员"' in manual.read_text()


def test_api_shell_reads_the_selected_home(tmp_path):
    home = ensure_home(tmp_path / "api-home")
    response = TestClient(create_app(home)).get("/api/v1/health")
    assert response.json() == {"status": "ok", "model_provider": "registry"}


def test_lan_local_model_requires_explicit_http_opt_in(tmp_path):
    home = ensure_home(tmp_path / "local-home")
    models = home / "models.toml"
    original = models.read_text()
    models.write_text(original.replace("http://127.0.0.1:11434/v1", "http://192.168.1.20:11434/v1"))
    with pytest.raises(ValueError, match="Invalid endpoint"):
        validate_home(home)
    models.write_text(models.read_text().replace(
        'base_url = "http://192.168.1.20:11434/v1"\nallow_no_key = true\nallow_insecure_http = false',
        'base_url = "http://192.168.1.20:11434/v1"\nallow_no_key = true\nallow_insecure_http = true',
    ))
    assert validate_home(home)["models"]["providers"]["ollama"]["allow_insecure_http"] is True
