"""Load instructions for a Skill explicitly enabled on the current Agent."""

from futurework.extension_system.skill_loader import load_skills


def run(args: dict, config: dict, agent_id: str) -> str:
    """Check the Agent's enabled Skill IDs before reading the selected package."""
    skill_id = args["name"]
    enabled = config["agent_extensions"].get(agent_id, {}).get("skills", [])
    if agent_id == "assistant":
        enabled = [*enabled, "dynamic_plan"]
    if skill_id not in enabled:
        raise PermissionError("skill is not enabled for this Agent")
    maximum = config["skill_policy"].get("max_skill_chars", config["tool_runtime"]["max_result_chars"])
    return load_skills(config["home"], [skill_id], maximum)
