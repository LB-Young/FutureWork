from futurework.algorithm import assign_steps, plan_steps, rank_agents
from futurework.config import load_config
from futurework.home import ensure_home


def test_low_proficiency_is_not_selected_even_with_high_success(tmp_path):
    config = load_config(home=ensure_home(tmp_path / "home"))
    candidates = [
        {"id": "unqualified", "status": "active", "capabilities": {"design.visual": 0.69}, "success_ratio": 1.0},
        {"id": "qualified", "status": "active", "capabilities": {"design.visual": 0.90}},
    ]
    assert rank_agents("design.visual", candidates, config)[0][0] == "qualified"
    assert all(agent_id != "unqualified" for agent_id, _ in rank_agents("design.visual", candidates, config))


def test_planner_uses_configured_rules_and_fallback(tmp_path):
    config = load_config(home=ensure_home(tmp_path / "home"))
    assert [item["capability"] for item in plan_steps("设计界面并写发布文案", config)] == ["design.visual", "writing.copy"]
    assert plan_steps("你好", config)[0]["capability"] == "planning.general"
    assigned = assign_steps("请做竞品分析", [], config)
    assert assigned[0].agent_id is None
    assert assigned[0].suggested_name == "数数"
