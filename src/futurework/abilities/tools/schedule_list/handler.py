"""Query persistent assistant schedules and their execution state."""

import json

from futurework.abilities.tools.schedule import ScheduleStore


def run(args: dict, config: dict) -> str:
    """Return the current saved schedule list as JSON."""
    return json.dumps(ScheduleStore(config["home"], config["schedule"]).list(), ensure_ascii=False)
