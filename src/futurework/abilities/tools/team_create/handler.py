"""Create one Team with explicit members and mode through GroupService."""

import json


def run(args: dict, group_service) -> str:
    """Persist a new Team after validating its selected friends and mode."""
    team = group_service.create(args["name"], args["member_ids"], args["mode"])
    return json.dumps({"id": team["id"], "name": team["name"],
                       "member_ids": team["members"], "mode": team["mode"]}, ensure_ascii=False)
