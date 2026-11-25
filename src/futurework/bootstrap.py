"""Validate user configuration before a runtime or API server starts."""

from pathlib import Path

from futurework.config_store.loader import load_user_config


def validate_home(home: Path) -> dict:
    """Return a validated configuration snapshot for the selected home."""
    raw = load_user_config(home)
    from futurework.config import load_config

    load_config(home)
    return raw
