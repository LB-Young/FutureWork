from dataclasses import dataclass


@dataclass(frozen=True)
class Assignment:
    capability: str
    title: str
    agent_id: str | None
    suggested_name: str
    suggested_role: str


def plan_steps(text: str, config: dict) -> list[dict]:
    normalized = text.casefold()
    matched = [
        rule for rule in config["planner"]["rules"]
        if any(keyword.casefold() in normalized for keyword in rule["keywords"])
    ]
    if not matched:
        matched = [config["planner"]["fallback"]]
    return matched[: config["limits"]["max_plan_steps"]]


def rank_agents(capability: str, agents: list[dict], config: dict) -> list[tuple[str, float]]:
    settings = config["matching"]
    ranked = []
    for agent in agents:
        if agent["status"] != "active":
            continue
        proficiency = agent["capabilities"].get(capability, 0)
        if proficiency < settings["minimum_proficiency"]:
            continue
        success = agent.get("success_ratio", settings["default_success"])
        load = agent.get("load_ratio", settings["default_load"])
        cost = agent.get("cost_ratio", settings["default_cost"])
        score = (
            settings["required_weight"] * proficiency
            + settings["success_weight"] * success
            + settings["load_weight"] * (1 - load)
            + settings["cost_weight"] * (1 - cost)
        )
        if score >= settings["minimum_score"]:
            ranked.append((agent["id"], round(score, 4)))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def assign_steps(text: str, agents: list[dict], config: dict) -> list[Assignment]:
    assignments = []
    for rule in plan_steps(text, config):
        ranked = rank_agents(rule["capability"], agents, config)
        assignments.append(Assignment(
            capability=rule["capability"],
            title=rule["title"],
            agent_id=ranked[0][0] if ranked else None,
            suggested_name=rule["agent_name"],
            suggested_role=rule["agent_role"],
        ))
    return assignments
