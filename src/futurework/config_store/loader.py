"""Read user TOML files into a validated startup configuration snapshot."""

import re
import tomllib
from pathlib import Path


ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def read_toml(path: Path) -> dict:
    """Parse one TOML document while retaining its path in validation errors."""
    try:
        with path.open("rb") as source:
            return tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"Cannot read {path}: {error}") from error


def read_definitions(directory: Path) -> dict[str, dict]:
    """Read direct TOML children and require file stems to match safe IDs."""
    result = {}
    for path in sorted(directory.glob("*.toml")):
        item = read_toml(path)
        item_id = item.get("id")
        if item_id != path.stem or not ID_PATTERN.fullmatch(path.stem):
            raise ValueError(f"Definition ID must match a safe filename: {path}")
        result[item_id] = item
    return result


def load_user_config(home: Path) -> dict:
    """Load app, model, Agent, Team, and extension references in dependency order."""
    app = read_toml(home / "app.toml")
    server = app.get("server", {})
    if server.get("host") not in {"127.0.0.1", "localhost", "::1"} or not isinstance(server.get("port"), int) or not 1 <= server["port"] <= 65535:
        raise ValueError(f"Invalid loopback server configuration in {home / 'app.toml'}")
    models = read_toml(home / "models.toml")
    settings = {name: read_toml(home / f"{name}.toml") for name in (
        "tools", "matching", "planner", "runtime", "context", "extensions"
    )}
    agents = read_definitions(home / "agents")
    teams = read_definitions(home / "teams")
    if "assistant" not in agents:
        raise ValueError(f"Missing required Agent: {home / 'agents' / 'assistant.toml'}")
    model_aliases = set(models.get("models", {}))
    providers = models.get("providers", {})
    for alias, model in models.get("models", {}).items():
        if model.get("provider") not in providers or not model.get("remote_id"):
            raise ValueError(f"Invalid model alias {alias} in {home / 'models.toml'}")
    for agent_id, agent in agents.items():
        model_alias = agent.get("model", {}).get("id")
        if model_alias not in model_aliases:
            raise ValueError(f"Unknown model alias {model_alias!r} in agent {agent_id}")
    for team_id, team in teams.items():
        if team.get("mode") not in {"swarm", "controlled"}:
            raise ValueError(f"Unknown group mode in team {team_id}")
        members = team.get("members", [])
        if not isinstance(members, list) or len(members) != len(set(members)) or any(member not in agents or member == "assistant" for member in members):
            raise ValueError(f"Invalid members in team {team_id}")
        controller = team.get("controller")
        if team["mode"] == "controlled" and (not controller or controller.get("agent_id") != "assistant"):
            raise ValueError(f"Controlled team {team_id} requires assistant controller")
        if team["mode"] == "swarm" and controller:
            raise ValueError(f"Swarm team {team_id} cannot have a controller")
    installed = {
        "skills": sorted(str(path.relative_to(home)) for path in (home / "skills").rglob("SKILL.md")),
        "workflows": sorted(str(path.relative_to(home)) for path in (home / "workflows").rglob("workflow.toml")),
        "mcp": sorted(str(path.relative_to(home)) for path in (home / "mcp").glob("*.toml")),
    }
    return {"app": app, "models": models, "settings": settings,
            "agents": agents, "teams": teams, "installed_extensions": installed}
