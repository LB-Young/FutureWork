"""Apply shared workspace boundaries and atomic file writes for built-in tools."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def workspace(config: dict) -> Path:
    """Resolve the configured workspace once for a tool invocation."""
    raw = Path(config["tool_runtime"]["workspace"])
    return (raw if raw.is_absolute() else config["home"] / raw).resolve()


def within(root: Path, name: str) -> Path:
    """Reject traversal and symlinks outside the workspace."""
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError("path escapes the configured workspace")
    return target


def replace_file(path: Path, content: str) -> None:
    """Atomically replace a UTF-8 workspace file."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
