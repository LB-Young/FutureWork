"""Verify Skill instructions are loaded only for an Agent that enables them."""

import asyncio

from futurework.config import load_config
from tests.support import sample_home
from futurework.home import ensure_home
from futurework.model import respond
from futurework.runtime.tool_dispatch import ToolRegistry
from futurework.contexts.types import ScopeKey
import json


def test_user_skill_is_scoped_to_enabled_agent(tmp_path, monkeypatch):
    home = sample_home(tmp_path / "home")
    skill_dir = home / "skills" / "brief"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("先列出证据，再写结论。")
    agent_file = home / "agents" / "research.toml"
    agent_file.write_text(agent_file.read_text() + '\n[extensions]\nskills = ["brief"]\n')
    config = load_config(home)
    assert "skill_create" in config["tool_execution"]["require_approval_for"]
    prompts = []

    async def fake_generate(self, request):
        from futurework.integrations.model_gateway.types import ModelResult
        prompts.append(request.messages[0]["content"])
        return ModelResult(text="回复")

    monkeypatch.setattr("futurework.integrations.model_gateway.gateway.ModelGateway.generate", fake_generate)
    research = {"id": "research", "name": "知知", "role": "研究", "model": "default_fast"}
    code = {"id": "code", "name": "阿码", "role": "开发", "model": "default_fast"}
    asyncio.run(respond(research, [{"from": "me", "text": "研究一下"}], config))
    asyncio.run(respond(code, [{"from": "me", "text": "写代码"}], config))
    assert "先列出证据" in prompts[0]
    assert "先列出证据" not in prompts[1]


def test_assistant_creates_only_user_owned_skill(tmp_path):
    """The meta Skill's tool creates a valid package and refuses overwrite."""
    home = ensure_home(tmp_path / "home")
    config = load_config(home)
    registry = ToolRegistry("assistant", ["skill_create"], config, scope=ScopeKey("assistant", "assistant"))
    args = {"name": "market-review", "description": "用户要求反复审查市场报告时使用；普通问答不使用。",
            "instructions": "# 市场报告审查\n\n1. 收集报告。\n2. 核查来源。\n3. 写出结论与验收证据。"}
    result = asyncio.run(registry.execute("skill_create", args))
    assert result.success
    assert json.loads(result.content)["enabled_for_agents"] is False
    assert (home / "abilities" / "skills" / "market-review" / "SKILL.md").is_file()
    assert not asyncio.run(registry.execute("skill_create", args)).success
