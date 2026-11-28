"""Maintain a private append-only .env template and load literal values at startup."""

from __future__ import annotations

import ast
import os
import re
import threading
import tomllib
from importlib.resources import files
from pathlib import Path


NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
SECRET_NAME = re.compile(r"\b[A-Z][A-Z0-9_]*(?:API_KEY|AUTH_TOKEN|BASE_URL|SECRET)\b")
SYSTEM_NAMES = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}
_loaded: dict[str, str] = {}
_lock = threading.RLock()


def _catalog() -> dict[str, str]:
    with files("futurework").joinpath("defaults", "environment.toml").open("rb") as source:
        return tomllib.load(source)["variables"]


def _collect(value, names: set[str]) -> None:
    """Find environment references in nested user configuration without evaluating it."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"api_key_env", "key_env", "auth_env"} and isinstance(item, str) and NAME.fullmatch(item):
                names.add(item)
            elif key in {"env", "environment"} and isinstance(item, list):
                names.update(name for name in item if isinstance(name, str) and NAME.fullmatch(name))
            _collect(item, names)
    elif isinstance(value, list):
        for item in value:
            _collect(item, names)
    elif isinstance(value, str):
        names.update(REFERENCE.findall(value))


def required_variables(home: Path) -> dict[str, str]:
    """Combine packaged variables with names referenced by installed config and Skills."""
    catalog = _catalog()
    names = set(catalog)
    paths = [home / "models.toml", home / "app.toml", home / "agent_backends.toml"]
    paths += list((home / "mcp").glob("*.toml"))
    paths += list((home / "abilities" / "mcp").glob("*/manifest.toml"))
    for path in paths:
        if not path.is_file():
            continue
        with path.open("rb") as source:
            _collect(tomllib.load(source), names)
    skill_paths = list((home / "skills").glob("*/SKILL.md"))
    skill_paths += list((home / "abilities" / "skills").glob("*/SKILL.md"))
    bundled = files("futurework").joinpath("abilities", "skills")
    skill_paths += [entry.joinpath("SKILL.md") for entry in bundled.iterdir()
                    if entry.joinpath("SKILL.md").is_file()]
    for path in skill_paths:
        content = path.read_text(encoding="utf-8")
        names.update(REFERENCE.findall(content))
        names.update(SECRET_NAME.findall(content))
    return {name: catalog.get(name, "由用户配置、Skill 或扩展引用的环境变量。")
            for name in sorted(names - SYSTEM_NAMES) if NAME.fullmatch(name)}


def ensure_environment_file(home: Path) -> Path:
    """Create a private template or append only missing variable names."""
    path = home / ".env"
    if path.is_symlink():
        raise ValueError("FutureWork .env must not be a symbolic link")
    names = required_variables(home)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    present = {match.group(1) for line in existing.splitlines()
               if (match := ASSIGNMENT.match(line))}
    missing = [name for name in names if name not in present]
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("# FutureWork 私有环境变量；填写等号右侧。文件不会由程序覆盖或删减。\n")
    if missing:
        with path.open("a", encoding="utf-8") as output:
            if existing and not existing.endswith("\n"):
                output.write("\n")
            output.write("\n# 本次初始化新增的可配置变量\n")
            for name in missing:
                output.write(f"# {names[name]}\n{name}=\n")
    return path


def _literal(raw: str) -> str:
    """Read shell-like quoted or unquoted values without expansion or execution."""
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return ""
    if raw.startswith(("'", '"')):
        try:
            value = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            raise ValueError("invalid quoted value in FutureWork .env") from None
        if not isinstance(value, str):
            raise ValueError("FutureWork .env values must be strings")
        return value
    return raw.split(" #", 1)[0].strip()


def load_environment(home: Path) -> None:
    """Load nonempty values, preserving explicit process environment variables."""
    path = home / ".env"
    with _lock:
        for name, value in list(_loaded.items()):
            if os.environ.get(name) == value:
                os.environ.pop(name, None)
            del _loaded[name]
        for line in path.read_text(encoding="utf-8").splitlines():
            match = ASSIGNMENT.match(line)
            if not match or match.group(1) == "FUTUREWORK_HOME":
                continue
            name = match.group(1)
            value = _literal(line[match.end():])
            if value and name not in os.environ:
                os.environ[name] = value
                _loaded[name] = value
