"""Plan user requests and rank eligible Agent friends for each capability."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Assignment:
    """One capability step and the selected or proposed Agent."""

    capability: str
    title: str
    agent_id: str | None
    suggested_name: str
    suggested_role: str


class TaskPlanner:
    """Own planning and matching policy for one loaded configuration."""

    def __init__(self, config: dict) -> None:
        self.config = config

    def plan_steps(self, text: str) -> list[dict]:
        """Select bounded planner rules for a request."""
        normalized = text.casefold()
        matched = [rule for rule in self.config["planner"]["rules"]
                   if any(keyword.casefold() in normalized for keyword in rule["keywords"])]
        if not matched:
            matched = [self.config["planner"]["fallback"]]
        return matched[: self.config["limits"]["max_plan_steps"]]

    def rank_agents(self, capability: str, agents: list[dict]) -> list[tuple[str, float]]:
        """Rank active Agents using configured capability and load weights."""
        settings = self.config["matching"]
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
            score = (settings["required_weight"] * proficiency
                     + settings["success_weight"] * success
                     + settings["load_weight"] * (1 - load)
                     + settings["cost_weight"] * (1 - cost))
            if score >= settings["minimum_score"]:
                ranked.append((agent["id"], round(score, 4)))
        return sorted(ranked, key=lambda item: (-item[1], item[0]))

    def assign_steps(self, text: str, agents: list[dict]) -> list[Assignment]:
        """Bind planned capabilities to eligible Agents or new Agent proposals."""
        assignments = []
        for rule in self.plan_steps(text):
            ranked = self.rank_agents(rule["capability"], agents)
            assignments.append(Assignment(
                capability=rule["capability"], title=rule["title"],
                agent_id=ranked[0][0] if ranked else None,
                suggested_name=rule["agent_name"], suggested_role=rule["agent_role"],
            ))
        return assignments


def plan_steps(text: str, config: dict) -> list[dict]:
    """Compatibility entry point for planner rule consumers."""
    return TaskPlanner(config).plan_steps(text)


def rank_agents(capability: str, agents: list[dict], config: dict) -> list[tuple[str, float]]:
    """Compatibility entry point for ranking consumers."""
    return TaskPlanner(config).rank_agents(capability, agents)


def assign_steps(text: str, agents: list[dict], config: dict) -> list[Assignment]:
    """Compatibility entry point for assignment consumers."""
    return TaskPlanner(config).assign_steps(text, agents)
