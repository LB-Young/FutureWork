"""Read user TOML files into a validated startup configuration snapshot."""

import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from futurework.extension_system.skill_loader import load_skills


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
    for category, definitions in (("friends", agents), ("teams", teams)):
        for item_id, item in read_definitions(home / "abilities" / category).items():
            if item_id in definitions:
                raise ValueError(f"Duplicate {category} ID across legacy and abilities directories: {item_id}")
            definitions[item_id] = item
    if "assistant" not in agents:
        raise ValueError(f"Missing required Agent: {home / 'agents' / 'assistant.toml'}")
    if set(agents) & set(teams):
        raise ValueError("Agent and Team IDs must not overlap because conversation scopes share IDs")
    model_aliases = set(models.get("models", {}))
    providers = models.get("providers", {})
    for provider_id, provider in providers.items():
        if provider.get("adapter") not in {"openai_chat", "anthropic_messages", "http_provider"}:
            raise ValueError(f"Unknown adapter for provider {provider_id}")
        url = provider.get("base_url", "")
        dynamic_url = provider.get("adapter") == "http_provider" and isinstance(url, str) and re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", url)
        parts = urlsplit(url) if isinstance(url, str) and not dynamic_url else None
        loopback = parts is not None and parts.hostname in {"127.0.0.1", "localhost", "::1"}
        http_allowed = parts is not None and parts.scheme == "http" and (loopback or provider.get("allow_insecure_http") is True)
        query_allowed = provider.get("adapter") == "http_provider"
        valid_literal = parts is not None and parts.hostname and (parts.scheme == "https" or http_allowed) and not (parts.username or parts.password or parts.fragment or (parts.query and not query_allowed))
        if (not (dynamic_url or valid_literal)
                or (not provider.get("api_key_env") and provider.get("allow_no_key") is not True)):
            raise ValueError(f"Invalid endpoint or key reference for provider {provider_id}")
    for alias, model in models.get("models", {}).items():
        if model.get("provider") not in providers or not model.get("remote_id"):
            raise ValueError(f"Invalid model alias {alias} in {home / 'models.toml'}")
        if model.get("model_type", "text") not in {"text", "vision", "image_generation", "image_edit", "video_generation"}:
            raise ValueError(f"Invalid model type for {alias}")
    for agent_id, agent in agents.items():
        if not agent.get("name") or not agent.get("role") or not isinstance(agent.get("capabilities", {}), dict):
            raise ValueError(f"Incomplete Agent definition: {home / 'agents' / f'{agent_id}.toml'}")
        model_config = agent.get("model")
        if not isinstance(model_config, dict):
            raise ValueError(f"Agent {agent_id} needs a [model] table with id = \"default_fast\"")
        model_alias = model_config.get("id")
        if model_alias not in model_aliases:
            raise ValueError(f"Unknown model alias {model_alias!r} in agent {agent_id}")
        load_skills(home, agent.get("extensions", {}).get("skills", []), settings["extensions"]["policy"].get("max_skill_chars", 12000))
    for team_id, team in teams.items():
        if not team.get("name"):
            raise ValueError(f"Incomplete Team definition: {home / 'teams' / f'{team_id}.toml'}")
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
        reply = team.get("reply", {})
        if any(not isinstance(reply.get(key, 1), int) or reply.get(key, 1) <= 0
               for key in ("max_responders_per_round", "max_rounds", "max_total_model_calls")):
            raise ValueError(f"Invalid reply limits in team {team_id}")
        if team["mode"] == "controlled" and reply.get("max_total_model_calls", 8) < 3:
            raise ValueError(f"Controlled team {team_id} needs at least three model calls")
    installed = {
        "skills": sorted(str(path.relative_to(home)) for root in (home / "skills", home / "abilities" / "skills") for path in root.rglob("SKILL.md")),
        "workflows": sorted(str(path.relative_to(home)) for root in (home / "workflows", home / "abilities" / "workflows") for path in root.rglob("workflow.toml")),
        "mcp": sorted(str(path.relative_to(home)) for root in (home / "mcp", home / "abilities" / "mcp") for path in root.glob("*.toml")),
    }
    return {"app": app, "models": models, "settings": settings,
            "agents": agents, "teams": teams, "installed_extensions": installed}
