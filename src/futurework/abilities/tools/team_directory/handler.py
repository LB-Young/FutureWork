"""Return the current Agent and Team directory from persisted active records."""

import json


def run(args: dict, agent_service) -> str:
    """Expose only identities and membership, without private messages or credentials."""
    database = agent_service.database
    friends = database.agents()
    names = {friend["id"]: friend["name"] for friend in friends}
    teams = database.groups()
    return json.dumps({
        "assistant": {"id": "assistant", "name": agent_service.config["assistant"]["name"],
                      "role": agent_service.config["assistant"]["role"]},
        "friends": [{"id": friend["id"], "name": friend["name"], "role": friend["role"]}
                    for friend in friends],
        "teams": [{"id": team["id"], "name": team["name"], "mode": team["mode"],
                   "members": [{"id": member_id, "name": names.get(member_id, member_id)}
                               for member_id in team["members"]]}
                  for team in teams],
    }, ensure_ascii=False)
