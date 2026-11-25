"""Create a persistent one-shot or repeating assistant schedule."""

import json

from futurework.abilities.tools.schedule import ScheduleStore


def run(args: dict, config: dict) -> str:
    """Validate and save a future scheduled request."""
    store = ScheduleStore(config["home"], config["schedule"])
    return json.dumps(store.create(args["prompt"], args["run_at"], args.get("interval_seconds")), ensure_ascii=False)
