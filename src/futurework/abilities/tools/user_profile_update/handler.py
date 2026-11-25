"""Append one explicitly observed user fact to the shared bounded profile."""

import json

from futurework.abilities.tools.management import UserProfile


def run(args: dict, config: dict) -> str:
    """Write a deduplicated fact without exceeding the configured 500-character cap."""
    profile = UserProfile(config["home"], config["user_profile"]["max_chars"])
    return json.dumps(profile.add(args["fact"]), ensure_ascii=False)
