"""Atomically persist Agent and Team TOML while preserving user comments."""

import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import tomlkit


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class ConfigStore:
    """Write TOML definitions with a rollback journal around database work."""

    def __init__(self, home: Path):
        self.home = home
        self.lock = threading.RLock()

    def path(self, kind: str, item_id: str) -> Path:
        """Validate the kind and ID before constructing a user-owned path."""
        if kind not in {"agents", "teams"} or not SAFE_ID.fullmatch(item_id):
            raise ValueError("invalid config kind or ID")
        custom = self.home / "abilities" / ("friends" if kind == "agents" else "teams") / f"{item_id}.toml"
        return custom if custom.is_file() else self.home / kind / f"{item_id}.toml"

    @contextmanager
    def batch(self):
        """Restore prior file bytes if a write or enclosed database transaction fails."""
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

    def _write_tracked(self, kind: str, item: dict, originals: dict) -> Path:
        path = self.path(kind, item["id"])
        if path not in originals:
            originals[path] = path.read_bytes() if path.exists() else None
        return self.write(kind, item)

    def write(self, kind: str, item: dict) -> Path:
        """Update only managed fields and keep unrelated user TOML fields intact."""
        path = self.path(kind, item["id"])
        doc = tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()
        for key in ("id", "name", "role", "icon", "color", "ink", "status"):
            if key in item:
                doc[key] = item[key]
        if kind == "agents":
            model = doc.get("model")
            if model is None:
                model = tomlkit.table()
            model["id"] = item["model"]
            doc["model"] = model
            doc["tools"] = item["tools"]
            doc["capabilities"] = item["capabilities"]
            doc["approval"] = item["approval"]
            if "skills" in item:
                extensions = doc.get("extensions") or tomlkit.table()
                extensions["skills"] = item["skills"]
                doc["extensions"] = extensions
            doc.setdefault("kind", "friend")
            doc.setdefault("schema_version", 1)
        else:
            doc["members"] = item["members"]
            doc["mode"] = item["mode"]
            doc.setdefault("schema_version", 1)
            if item["mode"] == "controlled":
                controller = doc.get("controller")
                if controller is None:
                    controller = tomlkit.table()
                controller["agent_id"] = "assistant"
                doc["controller"] = controller
            elif "controller" in doc:
                del doc["controller"]
        self._replace(path, tomlkit.dumps(doc).encode("utf-8"))
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
