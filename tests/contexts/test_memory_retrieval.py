"""Verify staged scoped retrieval and the model-visible memory search tool."""

import asyncio
import json

import pytest

from futurework.config import load_config
from futurework.contexts.retrieval import MemoryRetriever
from futurework.contexts.store import MemoryStore
from futurework.contexts.types import ScopeKey
from futurework.home import ensure_home
from futurework.runtime.tool_dispatch import ToolRegistry


def _message(path, scope, message_id, speaker, text):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"schema_version": 1, "type": "message", "scope": scope,
                                 "id": message_id, "speaker": speaker, "text": text,
                                 "created_at": "2026-11-25T00:00:00+00:00"}, ensure_ascii=False) + "\n")


def test_private_experience_precedes_jsonl_and_falls_back_when_absent(tmp_path):
    home = ensure_home(tmp_path / "home")
    store = MemoryStore(home, load_config(home)["memory"])
    directory = store.directory(ScopeKey("agent", "research"))
    (directory / "experiences.md").write_text("# 经验\n\n研究结论：保留证据来源。\n<!-- source: experience-1 -->\n", encoding="utf-8")
    _message(directory / "messages.jsonl", "agent:research", "raw-1", "知知", "研究结论的完整原文")
    _message(directory / "messages.jsonl", "agent:research", "raw-2", "知知", "历史遗漏详情")
    retriever = MemoryRetriever(store)

    experience = retriever.search("研究结论", ScopeKey("agent", "research"), "research")
    assert experience.tier == "own_experience"
    assert [item.message_id for item in experience.matches] == ["experience-1"]
    raw = retriever.search("历史遗漏详情", ScopeKey("agent", "research"), "research")
    assert raw.tier == "jsonl"
    assert [item.message_id for item in raw.matches] == ["raw-2"]
    assert retriever.search("历史遗漏详情", ScopeKey("assistant", "assistant"), "assistant").tier == "none"


def test_group_member_experience_then_group_experience_then_group_jsonl(tmp_path):
    home = ensure_home(tmp_path / "home")
    store = MemoryStore(home, load_config(home)["memory"])
    scope = ScopeKey("group", "launch")
    root = store.directory(scope)
    topic = root / "topics" / "发布"
    topic.mkdir()
    (topic / "research.md").write_text("研究结论：用户关注发布时间。\n<!-- source: research-1 -->\n", encoding="utf-8")
    (topic / "design.md").write_text("设计结论：使用蓝色主题。\n<!-- source: design-1 -->\n", encoding="utf-8")
    (root / "overview.md").write_text("# 群聊话题\n\n发布任务：协调研究与设计。\n", encoding="utf-8")
    _message(root / "messages.jsonl", "group:launch", "raw-1", "知知", "原始群聊决议：星期三发布")
    retriever = MemoryRetriever(store)

    assert retriever.search("研究结论", scope, "research").tier == "member_experience"
    shared = retriever.search("设计结论", scope, "research")
    assert shared.tier == "group_experience"
    assert shared.matches[0].source.endswith("design.md")
    assert retriever.search("原始群聊决议", scope, "research").tier == "member_jsonl"
    assert retriever.search("原始群聊决议", ScopeKey("assistant", "assistant"), "assistant", group_id="launch").tier == "jsonl"
    with pytest.raises(PermissionError):
        retriever.search("设计结论", ScopeKey("agent", "research"), "research", group_id="launch")


def test_memory_tool_uses_bound_scope_without_agent_grant(tmp_path):
    home = ensure_home(tmp_path / "home")
    config = load_config(home)
    store = MemoryStore(home, config["memory"])
    root = store.directory(ScopeKey("agent", "research"))
    (root / "experiences.md").write_text("研究主题：核对来源。\n<!-- source: example -->\n", encoding="utf-8")
    registry = ToolRegistry("research", (), config, scope=ScopeKey("agent", "research"), memory_store=store)
    assert "memory_search" in [item["function"]["name"] for item in registry.schemas()]
    result = asyncio.run(registry.execute("memory_search", {"query": "研究主题"}))
    assert result.success
    assert json.loads(result.content)["tier"] == "own_experience"
    denied = asyncio.run(registry.execute("memory_search", {"query": "研究主题", "group_id": "launch"}))
    assert not denied.success
