"""Create or revise an actor's scoped dynamic task plan."""

import json

from futurework.abilities.tools.management import DynamicPlan
from futurework.contexts.types import ScopeKey


def run(args: dict, config: dict, scope: ScopeKey, actor_id: str) -> str:
    """Persist bounded steps and acceptance criteria, preserving passed steps."""
    plan = DynamicPlan(config["home"], scope, actor_id, config["limits"]["max_plan_steps"])
    return json.dumps(plan.update(args["steps"], args["reason"]), ensure_ascii=False)
