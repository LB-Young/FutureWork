import os
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict:
    config_path = Path(path or os.environ.get("FUTUREWORK_CONFIG", ROOT / "config" / "app.toml"))
    with config_path.open("rb") as config_file:
        config = tomllib.load(config_file)
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


def database_path(config: dict, override: str | Path | None = None) -> Path:
    configured = Path(override or config["server"]["database_path"])
    return configured if configured.is_absolute() else ROOT / configured
