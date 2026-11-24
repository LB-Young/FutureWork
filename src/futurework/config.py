"""Adapt user-owned TOML definitions into the runtime configuration snapshot."""

from importlib.resources import files
from pathlib import Path
import tomllib

from futurework.config_store.loader import load_user_config
from futurework.runtime.tool_dispatch import PUBLIC_TOOLS, SCHEMAS


WEB_DIRECTORY = files("futurework").joinpath("web")
DEFAULT_CONFIG = files("futurework").joinpath("defaults", "app.toml")


def _merge(base: dict, override: dict) -> dict:
    """Merge user app settings over bundled defaults without changing either input."""
    result = dict(base)
    for key, value in override.items():
        result[key] = _merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def load_config(home: Path) -> dict:
    """Load validated files and materialize Agent and Team database projections."""
    raw = load_user_config(home)
    with DEFAULT_CONFIG.open("rb") as source:
        bundled = tomllib.load(source)
    config = _merge(bundled, raw["app"])
    config["permissions"]["available_tools"] = list(PUBLIC_TOOLS)
    config["permissions"]["safe_default_tools"] = [name for name in config["permissions"]["safe_default_tools"] if name in SCHEMAS]
    required = set(bundled["permissions"]["approval_required_tools"]) | set(config["permissions"]["approval_required_tools"])
    config["permissions"]["approval_required_tools"] = [name for name in SCHEMAS if name in required]
    assistant = raw["agents"]["assistant"]
    config["ui"]["assistant_name"] = assistant["name"]
    config["ui"]["assistant_role"] = assistant["role"]
    config["models"] = raw["models"]
    config["home"] = home
    config["skill_policy"] = raw["settings"]["extensions"]["policy"]
    config["agent_extensions"] = {agent_id: item.get("extensions", {}) for agent_id, item in raw["agents"].items()}
    config["model"]["available_models"] = list(raw["models"]["models"])
    if config["model"]["default_model"] not in config["model"]["available_models"]:
        raise ValueError("app.toml default_model must name an alias in models.toml")
    if config["model"]["provider"] not in {"registry", "mock"}:
        raise ValueError("model.provider must be registry or mock")
    config["assistant"] = assistant
    config["agents"] = {"seed": []}
    for agent in raw["agents"].values():
        if agent["id"] == "assistant":
            continue
        config["agents"]["seed"].append({
            "id": agent["id"], "name": agent["name"], "role": agent["role"],
            "icon": agent.get("icon", agent["name"][0]),
            "color": agent.get("color", config["ui"]["default_agent_color"]),
            "ink": agent.get("ink", config["ui"]["default_agent_ink"]),
            "model": agent["model"]["id"],
            "tools": agent.get("tools", agent.get("permissions", {}).get("tools", [])),
            "capabilities": agent.get("capabilities", {}),
            "approval": agent.get("approval", True), "status": agent.get("status", "active"),
        })
    agent_names = {agent["id"]: agent["name"] for agent in config["agents"]["seed"]}
    config["groups"] = {"seed": []}
    config["group_reply"] = {}
    for group in raw["teams"].values():
        config["group_reply"][group["id"]] = group.get("reply", {})
        config["groups"]["seed"].append({
            "id": group["id"], "name": group["name"],
            "role": group.get("role", "、".join(agent_names[member] for member in group["members"])),
            "icon": group.get("icon", group["name"][0]),
            "color": group.get("color", config["ui"]["default_agent_color"]),
            "ink": group.get("ink", config["ui"]["default_agent_ink"]),
            "members": group["members"], "status": group.get("status", "active"),
            "mode": group["mode"],
        })
    config["installed_extensions"] = raw["installed_extensions"]
    return config


def database_path(config: dict, home: Path, override: Path | None = None) -> Path:
    """Resolve relative SQLite paths below the selected user home."""
    path = Path(override or config["server"]["database_path"])
    return path if path.is_absolute() else home / path
