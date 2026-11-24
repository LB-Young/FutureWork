"""Verify first use initializes user directories without overwriting manual TOML."""

from futurework.bootstrap import validate_home
from futurework.api.app import create_app
from futurework.home import DIRECTORIES, ensure_home
from fastapi.testclient import TestClient


def test_home_is_initialized_and_manual_config_survives(tmp_path):
    home = ensure_home(tmp_path / "custom-home")
    assert all((home / relative / "README.md").is_file() for relative in DIRECTORIES)
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
    assert response.json() == {"status": "ok", "agents": 6, "teams": 3}
