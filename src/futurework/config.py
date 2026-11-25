"""Adapt user-owned TOML definitions into the runtime configuration snapshot."""

from importlib.resources import files
import errno
from pathlib import Path
import tomllib

from futurework.config_store.loader import load_user_config
from futurework.runtime.tool_dispatch import PUBLIC_TOOLS, REPLAY_SAFE_TOOLS, SCHEMAS


WEB_DIRECTORY = files("futurework").joinpath("web")
DEFAULT_CONFIG = files("futurework").joinpath("defaults", "app.toml")
DEFAULT_CONTEXT = files("futurework").joinpath("defaults", "context.toml")
DEFAULT_TOOLS = files("futurework").joinpath("defaults", "tools.toml")
DEFAULT_MEDIA = files("futurework").joinpath("defaults", "media.toml")
DEFAULT_EXTENSIONS = files("futurework").joinpath("defaults", "extensions.toml")


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
    with DEFAULT_MEDIA.open("rb") as source:
        media_defaults = tomllib.load(source)
    user_media = home / "media.toml"
    media_settings = tomllib.loads(user_media.read_text(encoding="utf-8")) if user_media.exists() else {}
    config["media"] = _merge(media_defaults["media"], media_settings.get("media", {}))
    if any(type(config["media"][key]) is not int or config["media"][key] <= 0 for key in
           ("request_timeout_seconds", "task_timeout_seconds", "poll_interval_seconds", "max_image_bytes",
            "max_video_bytes", "max_video_frames", "video_frame_width", "video_timeout_seconds", "max_edit_seconds", "max_video_width")):
        raise ValueError("media.toml contains invalid limits")
    if any(not isinstance(config["media"].get(key), str) or not config["media"][key] for key in ("ffmpeg_path", "ffprobe_path")):
        raise ValueError("media.toml video executables are invalid")
    config["home"] = home
    config["skill_policy"] = raw["settings"]["extensions"]["policy"]
    with DEFAULT_EXTENSIONS.open("rb") as source:
        extension_defaults = tomllib.load(source)
    config["workflow"] = _merge(extension_defaults["workflow"], raw["settings"]["extensions"].get("workflow", {}))
    if any(type(config["workflow"].get(name)) is not int or config["workflow"][name] <= 0 for name in
           ("max_steps", "max_input_chars", "max_output_chars")):
        raise ValueError("extensions.toml workflow limits must be positive integers")
    config["mcp"] = _merge(extension_defaults["mcp"], raw["settings"]["extensions"].get("mcp", {}))
    if type(config["mcp"].get("timeout_seconds")) is not int or config["mcp"]["timeout_seconds"] <= 0 or \
       type(config["mcp"].get("max_output_chars")) is not int or config["mcp"]["max_output_chars"] <= 0 or \
       type(config["mcp"].get("shutdown_timeout_seconds")) is not int or config["mcp"]["shutdown_timeout_seconds"] <= 0 or \
       not isinstance(config["mcp"].get("protocol_version"), str):
        raise ValueError("extensions.toml MCP settings are invalid")
    with DEFAULT_TOOLS.open("rb") as source:
        tool_defaults = tomllib.load(source)
    config["tool_execution"] = _merge(tool_defaults["execution"], raw["settings"]["tools"].get("execution", {}))
    policy = config["tool_execution"]
    if any(type(policy[key]) is not int or policy[key] < 1 for key in ("max_attempts", "max_input_chars", "max_output_chars")):
        raise ValueError("invalid tool execution integer limit")
    if any(type(policy[key]) not in (int, float) or policy[key] <= 0 for key in
           ("base_backoff_seconds", "max_backoff_seconds", "call_timeout_seconds", "approval_wait_seconds", "approval_poll_seconds")):
        raise ValueError("invalid tool execution duration")
    if policy["max_backoff_seconds"] < policy["base_backoff_seconds"]:
        raise ValueError("tool execution max backoff must cover base backoff")
    for key in ("require_approval_for", "retry_read_tools"):
        if not isinstance(policy[key], list) or any(name not in SCHEMAS for name in policy[key]):
            raise ValueError(f"invalid tool execution {key}")
    if not set(policy["retry_read_tools"]).issubset(REPLAY_SAFE_TOOLS):
        raise ValueError("tool retries are restricted to replay-safe built-ins")
    if (not isinstance(policy["retry_http_statuses"], list)
            or any(type(status) is not int or not 100 <= status <= 599 for status in policy["retry_http_statuses"])
            or type(policy["retry_http_5xx"]) is not bool
            or not isinstance(policy["retry_system_errors"], list)):
        raise ValueError("invalid tool retry error classes")
    if any(not isinstance(name, str) or not hasattr(errno, name) for name in policy["retry_system_errors"]):
        raise ValueError("invalid tool retry system error name")
    with DEFAULT_CONTEXT.open("rb") as source:
        context_defaults = tomllib.load(source)
    config["memory"] = _merge(context_defaults["memory"], raw["settings"]["context"].get("memory", {}))
    config["compaction"] = _merge(context_defaults["compaction"], raw["settings"]["context"].get("compaction", {}))
    if type(config["memory"]["search_enabled"]) is not bool:
        raise ValueError("context.toml memory.search_enabled must be a boolean")
    if any(type(value) is not int or value <= 0
           for key, value in config["memory"].items() if key != "search_enabled"):
        raise ValueError("context.toml [memory] values must be positive integers")
    compact = config["compaction"]
    if type(compact["enabled"]) is not bool or not 0 < compact["trigger_ratio"] <= 1:
        raise ValueError("invalid context.toml [compaction] switch or ratio")
    if any(type(value) is not int or value <= 0 for key, value in compact.items()
           if key not in {"enabled", "trigger_ratio"}):
        raise ValueError("context.toml [compaction] token and size limits must be positive integers")
    if compact["preserve_head_chars"] + compact["preserve_tail_chars"] >= compact["max_inline_message_chars"]:
        raise ValueError("compaction inline message limit must exceed preserved head and tail")
    config["agent_extensions"] = {agent_id: item.get("extensions", {}) for agent_id, item in raw["agents"].items()}
    config["user_profile"] = raw["settings"]["context"].get("user_profile", {"max_chars": 500})
    if any(type(config["schedule"].get(key)) is not int or config["schedule"][key] <= 0
           for key in ("poll_seconds", "min_interval_seconds", "max_prompt_chars")):
        raise ValueError("schedule settings must be positive integers")
    if type(config["user_profile"].get("max_chars")) is not int or not 1 <= config["user_profile"]["max_chars"] <= 500:
        raise ValueError("context.toml user_profile.max_chars must be between 1 and 500")
    if any(type(config["worker"].get(name)) is not bool for name in
           ("recover_assigned_on_startup", "mark_interrupted_failed")):
        raise ValueError("app.toml worker recovery switches must be booleans")
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
