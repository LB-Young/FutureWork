"""Record the outcome and evidence of one dynamic plan acceptance check."""

import json

from futurework.abilities.tools.management import DynamicPlan
from futurework.contexts.types import ScopeKey


def run(args: dict, config: dict, scope: ScopeKey, actor_id: str) -> str:
    """Persist a model or tool observation for the selected plan step."""
    plan = DynamicPlan(config["home"], scope, actor_id, config["limits"]["max_plan_steps"])
    return json.dumps(plan.check(args["step_id"], args["passed"], args["evidence"]), ensure_ascii=False)
