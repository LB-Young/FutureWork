"""Resolve provider credentials from environment or the user's Bamboo model catalog."""

import ast
import os
import re
from pathlib import Path


def _local_env(name: str) -> str:
    """Read a named variable from Bamboo's private .env without loading it globally."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return ""
    path = Path.home() / ".bamboo" / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        match = re.fullmatch(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*", line)
        if match and match.group(1) == name:
            value = match.group(2)
            if value.startswith(("'", '"')):
                try:
                    parsed = ast.literal_eval(value)
                    return parsed if isinstance(parsed, str) else ""
                except (ValueError, SyntaxError):
                    return ""
            return value.split(" #", 1)[0].strip()
    return ""


def api_key(provider: dict) -> str:
    """Prefer an environment variable; optionally read one named local Bamboo model."""
    env_name = provider.get("api_key_env", "")
    value = os.environ.get(env_name, "") if env_name else ""
    if value:
        return value
    if env_name:
        value = _local_env(env_name)
        if value:
            return value
    model_name = provider.get("bamboo_model", "")
    if not model_name:
        return ""
    path = Path.home() / ".bamboo" / "configs" / "models.yaml"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    active = False
    for line in lines:
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            active = line.strip()[:-1] == model_name
            continue
        if active and line.startswith("    api_key:"):
            raw = line.split(":", 1)[1].strip()
            if raw.startswith(("'", '"')):
                try:
                    parsed = ast.literal_eval(raw)
                    value = parsed if isinstance(parsed, str) else ""
                    reference = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
                    return (os.environ.get(reference.group(1), "") or _local_env(reference.group(1))) if reference else value
                except (ValueError, SyntaxError):
                    return ""
            value = raw.split(" #", 1)[0].strip() if raw not in {"", "null", "~"} else ""
            reference = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
            return (os.environ.get(reference.group(1), "") or _local_env(reference.group(1))) if reference else value
    return ""
