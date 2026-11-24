"""Verify Skill instructions are loaded only for an Agent that enables them."""

import asyncio

from futurework.config import load_config
from futurework.home import ensure_home
from futurework.model import respond


def test_user_skill_is_scoped_to_enabled_agent(tmp_path, monkeypatch):
    home = ensure_home(tmp_path / "home")
    skill_dir = home / "skills" / "brief"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("先列出证据，再写结论。")
    agent_file = home / "agents" / "research.toml"
    agent_file.write_text(agent_file.read_text() + '\n[extensions]\nskills = ["brief"]\n')
    config = load_config(home)
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
