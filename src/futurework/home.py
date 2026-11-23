import os
import re
import shutil
import tempfile
import tomllib
import threading
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

import tomlkit


SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
RESOURCE_ROOT = files("futurework")


def home_path(override: str | Path | None = None) -> Path:
    value = override or os.environ.get("FUTUREWORK_HOME")
    return Path(value).expanduser().resolve() if value else Path.home() / ".futurework"


def ensure_home(override: str | Path | None = None) -> Path:
    home = home_path(override)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in (
        "agents", "teams", "skills", "workflows", "mcp", "memory/assistant",
        "memory/agents", "memory/teams", "data", "logs", "cache",
    ):
        (home / name).mkdir(parents=True, exist_ok=True)
    app_config = home / "app.toml"
    if not app_config.exists():
        shutil.copyfile(RESOURCE_ROOT.joinpath("defaults", "app.toml"), app_config)
    marker = home / ".initialized"
    if not marker.exists():
        agent_files = list((home / "agents").glob("*.toml"))
        if not agent_files:
            for resource in RESOURCE_ROOT.joinpath("defaults", "agents").iterdir():
                shutil.copyfile(resource, home / "agents" / resource.name)
        elif not (home / "agents" / "assistant.toml").exists():
            shutil.copyfile(RESOURCE_ROOT.joinpath("defaults", "agents", "assistant.toml"), home / "agents" / "assistant.toml")
        team_files = list((home / "teams").glob("*.toml"))
        if not team_files and not agent_files:
            for resource in RESOURCE_ROOT.joinpath("defaults", "teams").iterdir():
                shutil.copyfile(resource, home / "teams" / resource.name)
        marker.touch()
    return home


def read_toml_files(directory: Path) -> list[dict]:
    values = []
    for path in sorted(directory.glob("*.toml")):
        try:
            with path.open("rb") as source:
                item = tomllib.load(source)
        except tomllib.TOMLDecodeError as error:
            raise ValueError(f"invalid TOML in {path}: {error}") from error
        if item.get("id") != path.stem:
            raise ValueError(f"config ID must match filename: {path}")
        values.append(item)
    return values


def discover_extensions(home: Path) -> dict:
    skills = [{"id": path.parent.name, "file": str(path.relative_to(home))} for path in sorted((home / "skills").rglob("SKILL.md"))]
    workflows = read_toml_files(home / "workflows")
    mcp = read_toml_files(home / "mcp")
    return {"skills": skills, "workflows": workflows, "mcp": mcp}


class ConfigStore:
    def __init__(self, home: Path):
        self.home = home
        self.lock = threading.RLock()

    @contextmanager
    def batch(self):
        originals = {}
        with self.lock:
            try:
                yield lambda kind, item: self._write_tracked(kind, item, originals)
            except Exception:
                for path, content in reversed(list(originals.items())):
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        self._replace(path, content)
                raise

    def _write_tracked(self, kind: str, item: dict, originals: dict):
        path = self.path(kind, item["id"])
        if path not in originals:
            originals[path] = path.read_bytes() if path.exists() else None
        return self.write(kind, item)

    def path(self, kind: str, item_id: str) -> Path:
        if kind not in {"agents", "teams"} or not SAFE_ID.fullmatch(item_id):
            raise ValueError("invalid config kind or ID")
        return self.home / kind / f"{item_id}.toml"

    def write(self, kind: str, item: dict) -> Path:
        path = self.path(kind, item["id"])
        document = tomlkit.parse(path.read_text()) if path.exists() else tomlkit.document()
        keys = ("id", "name", "role", "icon", "color", "ink", "model", "tools", "capabilities", "approval", "status") if kind == "agents" else (
            "id", "name", "role", "icon", "color", "ink", "members", "status"
        )
        for key in keys:
            if key in item:
                document[key] = item[key]
        self._replace(path, tomlkit.dumps(document).encode("utf-8"))
        return path

    @staticmethod
    def _replace(path: Path, content: bytes):
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".toml", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
