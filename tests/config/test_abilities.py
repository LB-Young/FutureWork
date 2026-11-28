"""Verify minimal defaults, Skill creation, user profile, plans, and schedules."""

import asyncio
from datetime import datetime, timedelta, timezone
from importlib.resources import files

from futurework.abilities.tools.schedule import ScheduleStore
from futurework.config import load_config
from futurework.contexts.types import ScopeKey
from futurework.contexts.store import MemoryStore
from futurework.home import ensure_home
import futurework.home as home_module
from futurework.runtime.tool_dispatch import ToolRegistry
from futurework.runtime.agent_executor import AgentRuntime
from futurework.integrations.model_gateway.types import ModelResult
from futurework.algorithm import TaskPlanner
from futurework.api.app import create_app
from fastapi.testclient import TestClient
from futurework.runtime.tool_dispatch import SCHEMAS


def test_new_home_installs_multimedia_and_user_ability_directories(tmp_path):
    home = ensure_home(tmp_path / "home")
    config = load_config(home)
    assert {item["id"] for item in config["agents"]["seed"]} == {"image", "video", "codex", "openclaw", "claude_code"}
    assert {path.stem for path in (home / "agents").glob("*.toml")} == {"assistant", "image", "video", "codex", "openclaw", "claude_code"}
    assert {path.stem for path in (home / "teams").glob("*.toml")} == {"multimedia"}
    bootstrap = TestClient(create_app(home)).get("/api/v1/bootstrap").json()
    assert {agent["name"] for agent in bootstrap["agents"]} == {"小T", "小V", "Codex", "OpenClaw", "Claude Code"}
    assert [group["name"] for group in bootstrap["groups"]] == ["媒体群"]
    skill_root = files("futurework").joinpath("abilities", "skills")
    assert {path.name for path in skill_root.iterdir() if path.joinpath("SKILL.md").is_file()} == {"skill-creator"}
    assert (home / "user.md").read_text(encoding="utf-8") == ""
    for name in ("tools", "skills", "mcp", "workflows", "friends", "teams"):
        assert (home / "abilities" / name).is_dir()
    assert "skill-creator" in (home / "agents" / "assistant.toml").read_text()
    agents = [{**item, "status": "active"} for item in config["agents"]["seed"]]
    assert any(item.agent_id == "image" for item in TaskPlanner(config).assign_steps("生成图片", agents))
    assert any(item.agent_id == "video" for item in TaskPlanner(config).assign_steps("生成视频", agents))


def test_existing_assistant_gets_creation_tools_without_losing_grants(tmp_path):
    home = ensure_home(tmp_path / "home")
    path = home / "agents" / "assistant.toml"
    source = path.read_text(encoding="utf-8")
    path.write_text(source.replace('"friend_create", "team_create", ', ''), encoding="utf-8")
    ensure_home(home)
    config = load_config(home)
    assert {"delegate_task", "friend_create", "team_create", "calculator"}.issubset(
        set(config["assistant"]["tools"]))
    assert {"friend_create", "team_create"}.issubset(
        set(config["tool_execution"]["require_approval_for"]))


def test_user_profile_shared_and_bounded_and_plan_revisions(tmp_path):
    home = ensure_home(tmp_path / "home")
    config = load_config(home)
    registry = ToolRegistry("research", ["plan_update", "plan_check"], config,
                            scope=ScopeKey("agent", "research"))
    update = lambda name, args: asyncio.run(registry.execute(name, args))
    assert update("user_profile_update", {"fact": "喜欢中文简洁回答"}).success
    assert "喜欢中文简洁回答" in (home / "user.md").read_text()
    assert not update("user_profile_update", {"fact": "x" * 501}).success
    steps = [{"id": "first", "action": "整理需求", "acceptance": "列出三项需求"},
             {"id": "second", "action": "实现界面", "acceptance": "页面可加载"}]
    assert update("plan_update", {"steps": steps, "reason": "开始"}).success
    assert update("plan_check", {"step_id": "first", "passed": True, "evidence": "已列出三项需求"}).success
    revision = [steps[0], {"id": "second", "action": "先做接口", "acceptance": "接口返回 200"}]
    assert update("plan_update", {"steps": revision, "reason": "需要接口"}).success
    assert not update("plan_update", {"steps": [revision[1]], "reason": "删除已完成"}).success


def test_schedule_persists_and_dispatches_once(tmp_path):
    home = ensure_home(tmp_path / "home")
    store = ScheduleStore(home, load_config(home)["schedule"])
    due = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    job = store.create("提醒我整理日报", due)
    assert store.list()[0]["id"] == job["id"]
    config = load_config(home)
    registry = ToolRegistry("assistant", ["schedule_list"], config, scope=ScopeKey("assistant", "assistant"))
    assert job["id"] in asyncio.run(registry.execute("schedule_list", {})).content
    path = store.directory / f"{job['id']}.json"
    content = path.read_text().replace(due, (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    path.write_text(content)
    seen = []

    async def dispatch(item):
        seen.append(item["prompt"])

    assert asyncio.run(store.run_due(dispatch)) == 1
    assert asyncio.run(store.run_due(dispatch)) == 0
    assert seen == ["提醒我整理日报"]


def test_default_home_copies_legacy_data_without_overwriting(tmp_path, monkeypatch):
    monkeypatch.setattr(home_module.Path, "home", lambda: tmp_path)
    legacy = tmp_path / ".futurework"
    legacy.mkdir()
    (legacy / "user.md").write_text("- 习惯：中文答复\n", encoding="utf-8")
    current = ensure_home()
    assert current == tmp_path / ".FutureWork"
    assert (current / "user.md").read_text() == "- 习惯：中文答复\n"
    (current / "user.md").write_text("- 新偏好\n")
    ensure_home()
    assert (current / "user.md").read_text() == "- 新偏好\n"


def test_user_friend_definition_and_profile_are_loaded(tmp_path):
    home = ensure_home(tmp_path / "home")
    source = home / "abilities" / "friends" / "helper.toml"
    source.write_text('id = "helper"\nname = "助手"\nrole = "记录"\ntools = []\n[model]\nid = "default_fast"\n', encoding="utf-8")
    config = load_config(home)
    assert "helper" in {item["id"] for item in config["agents"]["seed"]}
    store = MemoryStore(home, config["memory"])
    store.ensure_profiles()
    assert (home / "abilities" / "friends" / "helper.md").is_file()
    assert "助手" in store.prompt_context(ScopeKey("agent", "helper"), "helper")


def test_every_agent_sees_user_profile_and_assistant_gets_skill_creator(tmp_path):
    home = ensure_home(tmp_path / "home")
    (home / "user.md").write_text("- 偏好：中文简答\n", encoding="utf-8")
    config = load_config(home)

    class Gateway:
        def supports_tools(self, alias):
            return True

        async def generate(self, request):
            assert "中文简答" in request.messages[0]["content"]
            if "小未" in request.messages[0]["content"]:
                assert "创建 FutureWork Skill" in request.messages[0]["content"]
                assert "当前团队 Agent 好友" not in request.messages[0]["content"]
                assert "plan_update" in {item["function"]["name"] for item in request.tools}
                assert "skill_create" in {item["function"]["name"] for item in request.tools}
            return ModelResult(text="完成")

    runtime = AgentRuntime(config, model_gateway=Gateway())
    for item_id in ("assistant", "image"):
        agent = {"id": item_id, "name": "小未" if item_id == "assistant" else "小T",
                 "role": "助理", "model": "default_fast",
                 "tools": config["assistant"]["tools"] if item_id == "assistant" else []}
        assert asyncio.run(runtime.respond(agent, [{"from": "me", "text": "你好"}])) == "完成"


def test_skill_creation_request_runs_in_assistant_scope(tmp_path):
    """XiaoWei owns both Skill creation and deliberate task delegation."""
    config = load_config(ensure_home(tmp_path / "home"))
    assert "skill_create" in config["assistant"]["tools"]
    assert "delegate_task" in config["assistant"]["tools"]
    assert "delegate_task" in SCHEMAS
