"""Verify bounded context summaries, tool turn integrity, and scoped records."""

import asyncio
import json

from futurework.config import load_config
from futurework.contexts.compactor import ContextCompactor
from futurework.contexts.store import MemoryStore
from futurework.contexts.types import ScopeKey
from tests.support import sample_home
from futurework.integrations.model_gateway.types import ModelRequest, ModelResult


class Gateway:
    """Return a short summary or a configured provider failure."""

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        return ModelResult(text="目标：整理设计；约束：保留历史；待办：完成页面。")


def _setup(tmp_path, gateway):
    home = sample_home(tmp_path / "home")
    config = load_config(home)
    config["models"]["models"]["default_fast"]["context_window"] = 1200
    config["compaction"].update(trigger_ratio=0.3, minimum_remaining_tokens=100,
                                preserve_recent_messages=2, max_passes=1, max_summary_chars=300)
    store = MemoryStore(home, config["memory"])
    return ContextCompactor(config, gateway, store), store


def test_compacts_old_history_and_preserves_recent_and_raw_records(tmp_path):
    gateway = Gateway()
    compactor, store = _setup(tmp_path, gateway)
    scope = ScopeKey("agent", "research")
    raw = store.directory(scope) / "messages.jsonl"
    raw.write_text('{"id":"original","text":"source"}\n', encoding="utf-8")
    messages = [{"role": "system", "content": "rules"}]
    messages.extend({"role": "user", "content": "旧要求" + str(i) * 900, "source_id": f"m{i}"}
                    for i in range(6))
    request = ModelRequest("default_fast", messages)
    result = asyncio.run(compactor.compact(request, scope, "research"))
    assert gateway.calls == 1
    assert result.messages[-2:] == messages[-2:]
    assert result.messages[1]["content"].startswith("【较早会话摘要】")
    assert len(result.messages) < len(messages)
    record = json.loads((store.directory(scope) / "compactions.jsonl").read_text(encoding="utf-8"))
    assert record["source_ids"] == ["m0", "m1", "m2", "m3"]
    assert record["scope"] == "agent:research"
    assert raw.read_text(encoding="utf-8") == '{"id":"original","text":"source"}\n'
    assert not (store.directory(ScopeKey("assistant", "assistant")) / "compactions.jsonl").exists()


def test_tool_call_and_results_remain_together(tmp_path):
    compactor, _ = _setup(tmp_path, Gateway())
    messages = [{"role": "system", "content": "rules"},
                {"role": "user", "content": "旧问题" * 500},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]},
                {"role": "tool", "tool_call_id": "call-1", "content": "结果"},
                {"role": "user", "content": "最新要求"}]
    result = asyncio.run(compactor.compact(ModelRequest("default_fast", messages),
                                          ScopeKey("assistant", "assistant"), "assistant"))
    roles = [item["role"] for item in result.messages]
    assert roles[-3:] == ["assistant", "tool", "user"]


def test_provider_failure_uses_bounded_excerpt(tmp_path):
    gateway = Gateway(fail=True)
    compactor, store = _setup(tmp_path, gateway)
    messages = [{"role": "system", "content": "rules"}]
    messages.extend({"role": "user", "content": "old" * 500, "source_id": str(i)} for i in range(5))
    result = asyncio.run(compactor.compact(ModelRequest("default_fast", messages),
                                          ScopeKey("group", "launch"), "research"))
    assert len(result.messages) < len(messages)
    record = json.loads((store.directory(ScopeKey("group", "launch")) / "compactions.jsonl").read_text())
    assert record["method"] == "excerpt"
    assert record["actor_id"] == "research"
