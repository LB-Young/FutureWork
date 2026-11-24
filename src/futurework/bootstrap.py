"""Validate user configuration before a runtime or API server starts."""

from pathlib import Path

from futurework.config_store.loader import load_user_config


def validate_home(home: Path) -> dict:
    """Return a validated configuration snapshot for the selected home."""
    return load_user_config(home)
