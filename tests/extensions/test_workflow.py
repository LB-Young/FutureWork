"""Verify declarative workflow ordering, persistence, and dependency validation."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from futurework.extension_system.workflow_runner import WorkflowRunner
from futurework.api.app import create_app


def test_builtin_workflow_runs_agents_in_order(tmp_path):
    """Each step receives dependency output and is persisted after execution."""
    runner = WorkflowRunner(tmp_path, {"max_steps": 12, "max_input_chars": 4000, "max_output_chars": 12000})
    calls = []
    async def execute(agent_id, prompt):
        calls.append((agent_id, prompt))
        return f"{agent_id} result"
    result = asyncio.run(runner.run("product_launch", "新产品", execute))
    assert result["status"] == "completed"
    assert [call[0] for call in calls] == ["image", "video"]
    assert "image result" in calls[1][1]
    saved = tmp_path / "data" / "workflows" / f"{result['run_id']}.json"
    assert json.loads(saved.read_text())["status"] == "completed"


def test_workflow_rejects_cycle(tmp_path):
    """Cyclic dependencies cannot execute any Agent step."""
    directory = tmp_path / "workflows" / "loop"
    directory.mkdir(parents=True)
    (directory / "workflow.toml").write_text('id="loop"\nenabled=true\n[[steps]]\nid="a"\nkind="agent_task"\nagent_id="research"\nprompt="x"\ndepends_on=["b"]\n[[steps]]\nid="b"\nkind="agent_task"\nagent_id="design"\nprompt="y"\ndepends_on=["a"]\n')
    runner = WorkflowRunner(tmp_path, {"max_steps": 12, "max_input_chars": 4000, "max_output_chars": 12000})
    async def execute(agent_id, prompt):
        raise AssertionError("should not execute")
    with pytest.raises(ValueError, match="cycle"):
        asyncio.run(runner.run("loop", "input", execute))


def test_workflow_api_runs_with_agent_runtime(tmp_path):
    """The public endpoint invokes configured Agents and saves their replies."""
    app = create_app(tmp_path)
    app.state.config["model"]["provider"] = "mock"
    with TestClient(app) as client:
        response = client.post("/api/v1/workflows/product_launch/runs", json={"input": "测试发布"})
        assert response.status_code == 201
        assert response.json()["status"] == "completed"
        assert len(client.get("/api/v1/conversations/image/messages").json()) >= 2
