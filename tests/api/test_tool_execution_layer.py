"""Verify approval, validation, retry classification, and scoped tool audit."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.config import load_config
from futurework.contexts.store import MemoryStore
from futurework.contexts.types import ScopeKey
from tests.support import sample_home
from futurework.runtime.tool_approvals import ToolApprovalStore
from futurework.runtime.tool_dispatch import ToolRegistry, ToolResult
from futurework.runtime.tool_execution import ToolCall, ToolExecutionLayer
from futurework.services.message_service import MessageService
from futurework.abilities.tools.web_fetch import handler as web_fetch_handler
from futurework.integrations.model_gateway.types import ModelResult, ToolCall as ModelToolCall
from uuid import uuid4


def _layer(tmp_path, name="read", approval_store=None, require_approval=True):
    home = sample_home(tmp_path / "home")
    config = load_config(home)
    config["tool_execution"]["base_backoff_seconds"] = 0.001
    config["tool_execution"]["max_backoff_seconds"] = 0.001
    scope = ScopeKey("agent", "research")
    store = MemoryStore(home, config["memory"])
    registry = ToolRegistry("research", [name], config, scope=scope, memory_store=store)
    return ToolExecutionLayer(registry, config, store, approval_store, require_approval), scope, home


def test_invalid_input_and_missing_grant_never_reach_handler(tmp_path, monkeypatch):
    layer, scope, home = _layer(tmp_path)
    calls = []

    async def handler(*args, **kwargs):
        calls.append(1)
        return ToolResult("should not run")

    monkeypatch.setattr(layer.registry, "execute", handler)
    invalid = asyncio.run(layer.execute(ToolCall("a", "research", scope, "read", {"file_path": 42})))
    denied = asyncio.run(layer.execute(ToolCall("b", "research", scope, "write", {"file_path": "x", "content": "y"})))
    assert not invalid.success and invalid.error_code == "invalid_input"
    assert not denied.success and denied.error_code == "denied"
    assert calls == []
    audit = (home / "memory" / "agents" / "research" / "tool_calls.jsonl").read_text().splitlines()
    assert len(audit) == 2
    assert all(json.loads(line)["decision"] == "deny" for line in audit)


def test_retry_only_safe_transient_reads(tmp_path, monkeypatch):
    layer, scope, _ = _layer(tmp_path)
    calls = []

    async def transient(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("temporary")
        return ToolResult("recovered")

    monkeypatch.setattr(layer.registry, "execute", transient)
    result = asyncio.run(layer.execute(ToolCall("r", "research", scope, "read", {"file_path": "note.txt"})))
    assert result.success and result.attempts == 2 and result.content == "recovered"
    assert len(calls) == 2
    audit = json.loads((layer.store.directory(scope) / "tool_calls.jsonl").read_text().splitlines()[-1])
    assert audit["attempts_detail"][0] == {"attempt": 1, "outcome": "ConnectError", "retry": True}

    write_layer, scope, _ = _layer(tmp_path, "write", require_approval=False)
    write_calls = []

    async def failed_write(*args, **kwargs):
        write_calls.append(1)
        raise httpx.ConnectError("uncertain side effect")

    monkeypatch.setattr(write_layer.registry, "execute", failed_write)
    failed = asyncio.run(write_layer.execute(ToolCall("w", "research", scope, "write", {"file_path": "x", "content": "y"})))
    assert not failed.success and failed.attempts == 1 and len(write_calls) == 1


def test_non_transient_http_and_invalid_output_do_not_retry(tmp_path, monkeypatch):
    layer, scope, _ = _layer(tmp_path)
    calls = []

    async def unauthorized(*args, **kwargs):
        calls.append(1)
        request = httpx.Request("GET", "https://example.org")
        raise httpx.HTTPStatusError("unauthorized", request=request, response=httpx.Response(401, request=request))

    monkeypatch.setattr(layer.registry, "execute", unauthorized)
    result = asyncio.run(layer.execute(ToolCall("r", "research", scope, "read", {"file_path": "x"})))
    assert result.attempts == 1 and not result.success and len(calls) == 1

    memory_layer, scope, _ = _layer(tmp_path, "memory_search")

    async def malformed(*args, **kwargs):
        return ToolResult("not JSON")

    monkeypatch.setattr(memory_layer.registry, "execute", malformed)
    result = asyncio.run(memory_layer.execute(ToolCall("m", "research", scope, "memory_search", {"query": "历史"})))
    assert not result.success and result.attempts == 1 and result.error_code == "invalid_output"


def test_http_rate_limit_retries_a_read_only_call(tmp_path, monkeypatch):
    layer, scope, _ = _layer(tmp_path)
    calls = []

    async def rate_limited(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            request = httpx.Request("GET", "https://example.org")
            raise httpx.HTTPStatusError("rate limit", request=request,
                                        response=httpx.Response(429, request=request))
        return ToolResult("ready")

    monkeypatch.setattr(layer.registry, "execute", rate_limited)
    result = asyncio.run(layer.execute(ToolCall("rate", "research", scope, "read", {"file_path": "x"})))
    assert result.success and result.attempts == 2 and len(calls) == 2


def test_real_web_handler_retries_429_then_returns_page(tmp_path, monkeypatch):
    layer, scope, _ = _layer(tmp_path, "web_fetch")
    seen = []

    async def public(url):
        return True

    def respond(request):
        seen.append(request)
        return httpx.Response(429 if len(seen) == 1 else 200, text="page ready")

    monkeypatch.setattr(web_fetch_handler, "public_url", public)
    original = httpx.AsyncClient
    monkeypatch.setattr(web_fetch_handler.httpx, "AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(layer.execute(ToolCall("web", "research", scope, "web_fetch",
                                                {"url": "https://example.org/page"})))
    assert result.success and result.content == "page ready" and result.attempts == 2


def test_call_approval_uses_existing_inbox_and_never_mutates_agent_config(tmp_path):
    home = sample_home(tmp_path / "home")
    app = create_app(home)
    client = TestClient(app)
    config = app.state.config
    scope = ScopeKey("agent", "research")
    approvals = ToolApprovalStore(app.state.database, MessageService(app.state.database), config)
    original = (home / "agents" / "research.toml").read_bytes()
    approval_id = approvals.request("research", scope, "call-1", "write", {"file_path": "x", "content": "hello"})
    pending = client.get("/api/v1/approvals").json()
    assert any(item["id"] == approval_id and item["proposal"]["kind"] == "tool_call" for item in pending)
    assert client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}).status_code == 200
    assert asyncio.run(approvals.wait(approval_id)) is True
    assert (home / "agents" / "research.toml").read_bytes() == original


def test_unavailable_or_rejected_approval_prevents_side_effect(tmp_path, monkeypatch):
    layer, scope, home = _layer(tmp_path, "write")
    calls = []

    async def handler(*args, **kwargs):
        calls.append(1)
        return ToolResult("written")

    monkeypatch.setattr(layer.registry, "execute", handler)
    args = {"file_path": "x", "content": "y"}
    unavailable = asyncio.run(layer.execute(ToolCall("a", "research", scope, "write", args)))
    assert unavailable.error_code == "approval_unavailable" and calls == []

    class Reject:
        def request(self, *args):
            return "approval-1"

        async def wait(self, approval_id):
            return False

        def still_granted(self, agent_id, name):
            return True

    layer.approval_store = Reject()
    rejected = asyncio.run(layer.execute(ToolCall("b", "research", scope, "write", args)))
    assert rejected.error_code == "approval_denied" and calls == []
    assert not (home / "workspace" / "x").exists()


def test_approved_call_runs_real_write_handler_once(tmp_path):
    class Approve:
        def request(self, *args):
            return "approval-1"

        async def wait(self, approval_id):
            return True

        def still_granted(self, agent_id, name):
            return True

    layer, scope, home = _layer(tmp_path, "write", approval_store=Approve())
    result = asyncio.run(layer.execute(ToolCall("write-1", "research", scope, "write",
                                                {"file_path": "approved.txt", "content": "done"})))
    assert result.success and result.attempts == 1 and result.approval_id == "approval-1"
    assert (home / "workspace" / "approved.txt").read_text() == "done"


def test_approval_does_not_restore_a_revoked_grant(tmp_path):
    class ApproveButRevoke:
        def request(self, *args):
            return "approval-2"

        async def wait(self, approval_id):
            return True

        def still_granted(self, agent_id, name):
            return False

    layer, scope, home = _layer(tmp_path, "write", approval_store=ApproveButRevoke())
    result = asyncio.run(layer.execute(ToolCall("write-2", "research", scope, "write",
                                                {"file_path": "revoked.txt", "content": "never"})))
    assert not result.success and result.error_code == "grant_revoked"
    assert not (home / "workspace" / "revoked.txt").exists()


def test_config_cannot_make_write_automatically_replayable(tmp_path):
    home = sample_home(tmp_path / "home")
    path = home / "tools.toml"
    data = path.read_text(encoding="utf-8")
    path.write_text(data.replace('retry_read_tools = ["read",', 'retry_read_tools = ["write", "read",'), encoding="utf-8")
    with pytest.raises(ValueError, match="replay-safe"):
        load_config(home)


def test_api_waits_for_exact_tool_approval_before_writing(tmp_path, monkeypatch):
    home = sample_home(tmp_path / "home")
    friend = home / "agents" / "research.toml"
    friend.write_text(friend.read_text().replace('"skill_load"]', '"skill_load", "write"]'), encoding="utf-8")

    async def generate(self, request):
        if request.messages[-1]["role"] == "tool":
            assert "Wrote approved.txt" in request.messages[-1]["content"]
            return ModelResult(text="文件已写入")
        return ModelResult(tool_calls=[ModelToolCall("write-1", "write",
                                                     {"file_path": "approved.txt", "content": "approved"})])

    monkeypatch.setattr("futurework.integrations.model_gateway.gateway.ModelGateway.generate", generate)
    app = create_app(home)
    app.state.config["tool_execution"]["approval_poll_seconds"] = 0.01
    app.state.config["tool_execution"]["approval_wait_seconds"] = 2.0

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            pending_send = asyncio.create_task(client.post(
                "/api/v1/conversations/research/messages",
                json={"client_message_id": str(uuid4()), "body": "写入文件"}))
            approvals = []
            for _ in range(50):
                approvals = (await client.get("/api/v1/approvals")).json()
                if approvals:
                    break
                await asyncio.sleep(0.01)
            assert approvals and not (home / "workspace" / "approved.txt").exists()
            approval_id = approvals[0]["id"]
            assert (await client.post(f"/api/v1/approvals/{approval_id}/decision",
                                      json={"decision": "approve"})).status_code == 200
            assert (await pending_send).status_code == 202

    asyncio.run(scenario())
    assert (home / "workspace" / "approved.txt").read_text() == "approved"
