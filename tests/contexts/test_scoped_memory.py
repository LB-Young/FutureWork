"""Check source logs, experience files, profiles, and prompt scope isolation."""

import asyncio
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.config import load_config
from futurework.contexts.store import MemoryStore
from futurework.contexts.types import ScopeKey
from tests.support import sample_home
from futurework.integrations.model_gateway.types import ModelResult
from futurework.runtime.agent_executor import AgentRuntime
from futurework.runtime.agent_executor import AgentResponse


def _send(client, conversation_id, body):
    return client.post(f"/api/v1/conversations/{conversation_id}/messages",
                       json={"client_message_id": str(uuid4()), "body": body})


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_separate_jsonl_and_experience_survive_restart(tmp_path, monkeypatch):
    async def reply(self, agent, history, scope=None):
        return f"{agent['name']} 已完成"

    monkeypatch.setattr("futurework.model.AgentRuntime.respond", reply)
    async def direct_reply(self, agent, history, scope=None):
        return AgentResponse(f"{agent['name']} 已完成")
    monkeypatch.setattr("futurework.model.AgentRuntime.respond_with_result", direct_reply)
    home = sample_home(tmp_path / "home")
    client = TestClient(create_app(home))
    assert _send(client, "assistant", "助理私事").status_code == 202
    assert _send(client, "research", "研究私事").status_code == 202
    group = client.post("/api/v1/groups", json={"name": "测试讨论", "member_ids": ["design", "write"], "mode": "swarm"}).json()
    assert _send(client, group["id"], "发布主题").status_code == 202

    assistant_log = home / "memory" / "assistant" / "messages.jsonl"
    agent_log = home / "memory" / "agents" / "research" / "messages.jsonl"
    group_dir = home / "memory" / "teams" / group["id"]
    group_log = group_dir / "messages.jsonl"
    assert [item["text"] for item in _records(assistant_log)] == ["助理私事", "小未 已完成"]
    assert [item["text"] for item in _records(agent_log)] == ["研究私事", "知知 已完成"]
    assert [item["speaker"] for item in _records(group_log)] == ["你", "小绘", "言言"]
    assert "发布主题" in (group_dir / "overview.md").read_text()
    assert (group_dir / "topics").is_dir()
    topic_dir = next((group_dir / "topics").iterdir())
    assert (topic_dir / "design.md").is_file()
    assert (topic_dir / "write.md").is_file()
    assert "研究私事" in (home / "memory" / "agents" / "research" / "experiences.md").read_text()
    assert (home / "agents" / "research.md").is_file()
    assert (home / "teams" / f"{group['id']}.md").is_file()

    before = {path: path.read_bytes() for path in (assistant_log, agent_log, group_log, topic_dir / "design.md")}
    TestClient(create_app(home))
    assert {path: path.read_bytes() for path in before} == before


def test_prompt_reads_profiles_but_keeps_private_experience_out_of_group(tmp_path):
    home = sample_home(tmp_path / "home")
    config = load_config(home)
    store = MemoryStore(home, config["memory"])
    store.ensure_profiles()
    profile_content = "知知专长：特殊研究。" + "详细背景" * 800
    (home / "agents" / "research.md").write_text(profile_content, encoding="utf-8")
    (home / "teams" / "launch.md").write_text("发布群职责：协调发布。", encoding="utf-8")
    (home / "memory" / "assistant" / "experiences.md").write_text("助理私密记忆", encoding="utf-8")
    (home / "memory" / "agents" / "research" / "experiences.md").write_text("知知私密记忆", encoding="utf-8")
    (home / "memory" / "teams" / "launch" / "overview.md").write_text("发布群共享经验", encoding="utf-8")

    assistant = store.prompt_context(ScopeKey("assistant", "assistant"), "assistant")
    assert "知知专长" in assistant and "发布群职责" in assistant and "助理私密记忆" in assistant
    assert profile_content in assistant
    direct = store.prompt_context(ScopeKey("agent", "research"), "research")
    assert "知知专长" in direct and "知知私密记忆" in direct
    assert "助理私密记忆" not in direct and "发布群共享经验" not in direct
    group = store.prompt_context(ScopeKey("group", "launch"), "research")
    assert "发布群职责" in group and "发布群共享经验" in group
    assert "知知私密记忆" not in group and "助理私密记忆" not in group
    controller = store.prompt_context(ScopeKey("group", "launch"), "assistant")
    assert "知知专长" in controller and "发布群职责" in controller
    assert "助理私密记忆" not in controller

    class Gateway:
        def supports_tools(self, alias):
            return False

        async def generate(self, request):
            assert "知知专长" in request.messages[0]["content"]
            assert "发布群职责" in request.messages[0]["content"]
            return ModelResult(text="完成")

    runtime = AgentRuntime(config, model_gateway=Gateway(), memory_store=store)
    profile = {"id": "assistant", "name": "小未", "role": "助理", "model": "default_fast"}
    assert asyncio.run(runtime.respond(profile, [{"from": "me", "text": "分派工作"}])) == "完成"
    store.ensure_profiles()
    assert (home / "agents" / "research.md").read_text(encoding="utf-8") == profile_content


def test_restart_recovers_a_committed_message_missing_from_jsonl(tmp_path):
    home = sample_home(tmp_path / "home")
    first = create_app(home)
    database = first.state.database
    database.journal = None
    with database.transaction() as connection:
        first.state.memory_store.ensure_profiles()
        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (str(uuid4()), "research", "user", "你", "需要补齐的消息", str(uuid4()), None, None, "2026-11-25T00:00:00+00:00"))
    path = home / "memory" / "agents" / "research" / "messages.jsonl"
    assert path.read_text(encoding="utf-8") == ""
    create_app(home)
    assert [item["text"] for item in _records(path)] == ["需要补齐的消息"]
