import os
import tomllib
from importlib.resources import files
from pathlib import Path

from futurework.home import discover_extensions, home_path, read_toml_files

WEB_DIRECTORY = files("futurework").joinpath("web")
DEFAULT_CONFIG = files("futurework").joinpath("defaults", "app.toml")


def load_config(path: str | Path | None = None, home: str | Path | None = None) -> dict:
    user_home = home_path(home)
    config_path = Path(path or os.environ.get("FUTUREWORK_CONFIG", user_home / "app.toml"))
    with config_path.open("rb") as config_file:
        config = tomllib.load(config_file)
    agent_files = read_toml_files(user_home / "agents")
    assistant_files = [item for item in agent_files if item["id"] == "assistant"]
    if len(assistant_files) != 1:
        raise ValueError("agents/assistant.toml is required")
    assistant = assistant_files[0]
    config["ui"]["assistant_name"] = assistant["name"]
    config["ui"]["assistant_role"] = assistant["role"]
    agents = []
    for item in agent_files:
        if item["id"] == "assistant":
            continue
        if not item.get("name") or not item.get("role") or not isinstance(item.get("capabilities"), dict):
            raise ValueError(f"incomplete agent config: {item['id']}")
        item.setdefault("model", config["model"]["default_model"])
        item.setdefault("tools", [])
        item.setdefault("icon", item["name"][0])
        item.setdefault("color", config["ui"]["default_agent_color"])
        item.setdefault("ink", config["ui"]["default_agent_ink"])
        item.setdefault("approval", True)
        item.setdefault("status", "active")
        if item["model"] not in config["model"]["available_models"]:
            raise ValueError(f"unknown model in agent config: {item['id']}")
        if not set(item["tools"]).issubset(config["permissions"]["available_tools"]):
            raise ValueError(f"unknown tool in agent config: {item['id']}")
        if any(not 0 <= value <= 1 for value in item["capabilities"].values()):
            raise ValueError(f"invalid capability proficiency: {item['id']}")
        agents.append(item)
    agent_ids = {item["id"] for item in agents}
    if len(agent_ids) != len(agents):
        raise ValueError("duplicate agent ID")
    teams = []
    for item in read_toml_files(user_home / "teams"):
        if not item.get("name") or not isinstance(item.get("members"), list):
            raise ValueError(f"incomplete team config: {item['id']}")
        if len(item["members"]) != len(set(item["members"])) or not set(item["members"]).issubset(agent_ids):
            raise ValueError(f"unknown or duplicate team member: {item['id']}")
        item.setdefault("role", "、".join(next(agent["name"] for agent in agents if agent["id"] == member) for member in item["members"]))
        item.setdefault("icon", item["name"][0])
        item.setdefault("color", config["ui"]["default_agent_color"])
        item.setdefault("ink", config["ui"]["default_agent_ink"])
        item.setdefault("status", "active")
        teams.append(item)
    config["agents"] = {"seed": agents}
    config["groups"] = {"seed": teams}
    config["assistant"] = assistant
    config["extensions"] = discover_extensions(user_home)
    weights = config["matching"]
    total = sum(weights[key] for key in ("required_weight", "success_weight", "load_weight", "cost_weight"))
    if abs(total - 1.0) > 0.0001:
        raise ValueError("matching weights must sum to 1")
    if any(not 0 <= weights[key] <= 1 for key in ("required_weight", "success_weight", "load_weight", "cost_weight")):
        raise ValueError("matching weights must be between 0 and 1")
    if config["server"]["host"] not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("MVP server must bind to loopback until authentication is implemented")
    if not 1 <= config["server"]["port"] <= 65535:
        raise ValueError("invalid server port")
    if config["model"]["provider"] not in {"mock", "openai_compatible"}:
        raise ValueError("unsupported model provider")
    if config["model"]["default_model"] not in config["model"]["available_models"]:
        raise ValueError("default model must be in available models")
    if not 0 <= config["model"]["temperature"] <= 2 or config["model"]["timeout_seconds"] <= 0 or config["model"]["max_output_tokens"] <= 0:
        raise ValueError("invalid model limits")
    if not set(config["permissions"]["safe_default_tools"]).issubset(config["permissions"]["available_tools"]):
        raise ValueError("safe default tools must be available")
    if not set(config["permissions"]["approval_required_tools"]).issubset(config["permissions"]["available_tools"]):
        raise ValueError("approval tools must be available")
    for section, keys in {
        "server": ("event_poll_seconds", "event_heartbeat_seconds", "event_batch_size", "message_history_limit"),
        "limits": ("max_message_chars", "max_agent_name_chars", "max_agent_role_chars", "max_agents", "max_plan_steps", "max_group_name_chars", "max_group_members", "approval_ttl_hours"),
        "ui": ("recent_limit",),
    }.items():
        if any(config[section][key] <= 0 for key in keys):
            raise ValueError(f"{section} values must be positive")
    for key in ("minimum_proficiency", "minimum_score", "auto_agent_proficiency", "default_success", "default_load", "default_cost"):
        if not 0 <= weights[key] <= 1:
            raise ValueError(f"matching.{key} must be between 0 and 1")
    return config


def database_path(config: dict, override: str | Path | None = None, home: str | Path | None = None) -> Path:
    configured = Path(override or config["server"]["database_path"])
    return configured if configured.is_absolute() else home_path(home) / configured
