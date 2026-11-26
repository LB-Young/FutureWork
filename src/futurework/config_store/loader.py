"""Read user TOML files into a validated startup configuration snapshot."""

import re
import tomllib
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from futurework.extension_system.skill_loader import load_skills
from futurework.kinds import ASSISTANT, CONTROLLED, EXECUTION_KINDS, FRIEND, NATIVE, SWARM, TEAM, HTTP, PROCESS


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
    backends_path = home / "agent_backends.toml"
    with files("futurework").joinpath("defaults", "agent_backends.toml").open("rb") as source:
        bundled_backends = tomllib.load(source)
    user_backends = read_toml(backends_path) if backends_path.exists() else {}
    if not isinstance(user_backends.get("profiles", {}), dict) or not isinstance(user_backends.get("defaults", {}), dict):
        raise ValueError("agent_backends.toml profiles and defaults must be tables")
    if any(not isinstance(profile, dict) for profile in user_backends.get("profiles", {}).values()):
        raise ValueError("agent_backends.toml profile entries must be tables")
    profile_names = set(bundled_backends.get("profiles", {})) | set(user_backends.get("profiles", {}))
    backends = {"defaults": {**bundled_backends.get("defaults", {}),
                              **user_backends.get("defaults", {})},
                "profiles": {
                    name: {**bundled_backends.get("profiles", {}).get(name, {}),
                           **user_backends.get("profiles", {}).get(name, {})}
                    for name in profile_names}}
    if not isinstance(backends.get("profiles"), dict):
        raise ValueError("agent_backends.toml needs [profiles.*] tables")
    defaults = backends.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("agent_backends.toml [defaults] must be a table")
    for name, profile in backends["profiles"].items():
        if not isinstance(profile, dict):
            raise ValueError(f"Invalid Agent backend profile: {name}")
        profile = {**defaults, **profile}
        if "endpoint" in profile:
            endpoint = urlsplit(profile["endpoint"])
            if endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.fragment or endpoint.query:
                raise ValueError(f"Invalid Agent backend endpoint: {name}")
            if endpoint.scheme == "http" and endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError(f"HTTP Agent backend must use loopback: {name}")
        if "arguments" in profile and (not isinstance(profile["arguments"], list)
                                       or any(not isinstance(arg, str) for arg in profile["arguments"])):
            raise ValueError(f"Agent backend arguments must be a string array: {name}")
        if "environment" in profile and (not isinstance(profile["environment"], list)
                                          or any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                                                 for key in profile["environment"])):
            raise ValueError(f"Agent backend environment must list variable names: {name}")
        if "auth_env" in profile and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", profile["auth_env"]):
            raise ValueError(f"Agent backend auth_env is invalid: {name}")
        if "model" in profile and (not isinstance(profile["model"], str) or not profile["model"].strip()):
            raise ValueError(f"Agent backend model is invalid: {name}")
        if "sandbox" in profile and profile["sandbox"] not in {"read-only", "workspace-write"}:
            raise ValueError(f"Agent backend sandbox is invalid: {name}")
        if "permission_mode" in profile and profile["permission_mode"] not in {"plan", "default", "acceptEdits"}:
            raise ValueError(f"Claude Code permission mode is invalid: {name}")
        for limit in ("timeout_seconds", "health_timeout_seconds", "max_output_bytes", "max_answer_chars", "max_input_chars", "history_messages"):
            if limit in profile and (type(profile[limit]) is not int or profile[limit] <= 0):
                raise ValueError(f"Invalid Agent backend {limit}: {name}")
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
    if ASSISTANT not in agents:
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
        execution = agent.get("execution", {"kind": NATIVE})
        kind = execution.get("kind", NATIVE)
        if kind not in EXECUTION_KINDS:
            raise ValueError(f"Unknown execution backend for agent {agent_id}: {kind}")
        if kind == NATIVE:
            model_config = agent.get("model")
            if not isinstance(model_config, dict):
                raise ValueError(f"Agent {agent_id} needs a [model] table with id = \"default_fast\"")
            model_alias = model_config.get("id")
            if model_alias not in model_aliases:
                raise ValueError(f"Unknown model alias {model_alias!r} in agent {agent_id}")
        else:
            profile = backends["profiles"].get(execution.get("profile"))
            if not profile:
                raise ValueError(f"Unknown execution profile for agent {agent_id}")
            if kind == HTTP and not profile.get("endpoint"):
                raise ValueError(f"HTTP Agent {agent_id} needs a fixed endpoint")
            if kind == PROCESS and not profile.get("executable"):
                raise ValueError(f"Process Agent {agent_id} needs an executable")
        load_skills(home, agent.get("extensions", {}).get("skills", []), settings["extensions"]["policy"].get("max_skill_chars", 12000))
    for team_id, team in teams.items():
        if not team.get("name"):
            raise ValueError(f"Incomplete Team definition: {home / 'teams' / f'{team_id}.toml'}")
        if team.get("mode") not in {SWARM, CONTROLLED}:
            raise ValueError(f"Unknown group mode in team {team_id}")
        members = team.get("members", [])
        if not isinstance(members, list) or len(members) != len(set(members)) or any(member not in agents or member == "assistant" for member in members):
            raise ValueError(f"Invalid members in team {team_id}")
        controller = team.get("controller")
        if team["mode"] == CONTROLLED and (not controller or controller.get("agent_id") != ASSISTANT):
            raise ValueError(f"Controlled team {team_id} requires assistant controller")
        if team["mode"] == SWARM and controller:
            raise ValueError(f"Swarm team {team_id} cannot have a controller")
        reply = team.get("reply", {})
        if any(not isinstance(reply.get(key, 1), int) or reply.get(key, 1) <= 0
               for key in ("max_responders_per_round", "max_rounds", "max_total_model_calls")):
            raise ValueError(f"Invalid reply limits in team {team_id}")
        if team["mode"] == CONTROLLED and reply.get("max_total_model_calls", 8) < 3:
            raise ValueError(f"Controlled team {team_id} needs at least three model calls")
    installed = {
        "skills": sorted(str(path.relative_to(home)) for root in (home / "skills", home / "abilities" / "skills") for path in root.rglob("SKILL.md")),
        "workflows": sorted(str(path.relative_to(home)) for root in (home / "workflows", home / "abilities" / "workflows") for path in root.rglob("workflow.toml")),
        "mcp": sorted(str(path.relative_to(home)) for root in (home / "mcp", home / "abilities" / "mcp") for path in root.glob("*.toml")),
    }
    return {"app": app, "models": models, "backends": backends, "settings": settings,
            "agents": agents, "teams": teams, "installed_extensions": installed}
