"""Create one configured Agent friend through the same service used by the API."""

import json


def run(args: dict, agent_service) -> str:
    """Validate and persist a friend after its tool call has been approved."""
    agent = agent_service.create_agent(args["name"], args["role"], model=args.get("model"),
                                       tools=args.get("tools"), skills=args.get("skills"),
                                       capabilities=args.get("capabilities"))
    return json.dumps({"id": agent["id"], "name": agent["name"], "model": agent["model"],
                       "tools": agent["tools"], "skills": args.get("skills", []),
                       "capabilities": agent["capabilities"]}, ensure_ascii=False)
