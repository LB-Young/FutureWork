"""Exercise the Bamboo-inspired common tools through FutureWork's dispatcher."""

import asyncio
from importlib import import_module
from importlib.resources import files
import tomllib

import httpx
from fastapi.testclient import TestClient

from futurework.api.app import create_app
from futurework.config import load_config
from futurework.home import ensure_home
from futurework.abilities.tools.web_fetch import handler as web_fetch_handler
from futurework.runtime.tool_dispatch import ToolRequest, execute, execute_async


def test_file_write_edit_read_and_search_are_real(tmp_path):
    config = load_config(ensure_home(tmp_path / "home"))
    grants = ["write", "edit", "read", "glob", "grep"]
    run = lambda name, args: execute(ToolRequest("code", name, args), grants, config)
    assert run("write", {"file_path": "notes/today.txt", "content": "first line\nsecond line"}).success
    assert run("read", {"file_path": "notes/today.txt", "offset": 1}).content == "second line"
    assert "notes/today.txt" in run("glob", {"pattern": "**/*.txt"}).content
    assert "second line" in run("grep", {"pattern": "second"}).content
    assert run("edit", {"file_path": "notes/today.txt", "old_string": "second", "new_string": "third"}).success
    assert "third line" in run("read", {"file_path": "notes/today.txt"}).content
    assert not execute(ToolRequest("code", "write", {"file_path": "no.txt", "content": "x"}), ["read"], config).success
    assert not run("write", {"file_path": "../outside.txt", "content": "x"}).success


def test_skill_load_requires_agent_enablement(tmp_path):
    home = ensure_home(tmp_path / "home")
    skill = home / "skills" / "outline"
    skill.mkdir()
    (skill / "SKILL.md").write_text("先写提纲", encoding="utf-8")
    agent = home / "agents" / "research.toml"
    agent.write_text(agent.read_text() + '\n[extensions]\nskills = ["outline"]\n')
    config = load_config(home)
    granted = ["skill_load"]
    assert "先写提纲" in execute(ToolRequest("research", "skill_load", {"name": "outline"}), granted, config).content
    assert not execute(ToolRequest("code", "skill_load", {"name": "outline"}), granted, config).success


def test_web_fetch_and_markdown_write(tmp_path, monkeypatch):
    config = load_config(ensure_home(tmp_path / "home"))
    assert not asyncio.run(web_fetch_handler.public_url("http://127.0.0.1/private"))

    async def public(url):
        return True

    def handle(request):
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<html><body><h1>Title</h1><script>secret</script><p>Visible</p></body></html>")

    monkeypatch.setattr(web_fetch_handler, "public_url", public)
    original = httpx.AsyncClient
    monkeypatch.setattr(web_fetch_handler.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    grants = ["web_fetch", "url_to_md"]
    fetch = asyncio.run(execute_async(ToolRequest("research", "web_fetch", {"url": "https://example.org/page"}), grants, config))
    assert fetch.success and "Visible" in fetch.content and "secret" not in fetch.content
    save = asyncio.run(execute_async(ToolRequest("research", "url_to_md", {"url": "https://example.org/page", "output_path": "page.md"}), grants, config))
    assert save.success
    assert "Visible" in (config["home"] / "workspace" / "page.md").read_text()


def test_web_redirect_to_private_address_is_blocked(tmp_path, monkeypatch):
    config = load_config(ensure_home(tmp_path / "home"))

    async def public(url):
        return not url.startswith("http://127.0.0.1")

    def handle(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    monkeypatch.setattr(web_fetch_handler, "public_url", public)
    original = httpx.AsyncClient
    monkeypatch.setattr(web_fetch_handler.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    result = asyncio.run(execute_async(ToolRequest("research", "web_fetch", {"url": "https://example.org"}), ["web_fetch"], config))
    assert not result.success


def test_shell_requires_both_grant_and_explicit_config(tmp_path):
    config = load_config(ensure_home(tmp_path / "home"))
    call = ToolRequest("code", "bash", {"command": "printf hello"})
    assert not asyncio.run(execute_async(call, ["bash"], config)).success
    config["tool_runtime"]["allow_shell"] = True
    assert not asyncio.run(execute_async(call, ["read"], config)).success
    result = asyncio.run(execute_async(call, ["bash"], config))
    assert result.success and "hello" in result.content


def test_ui_only_lists_implemented_tools(tmp_path):
    client = TestClient(create_app(ensure_home(tmp_path / "home")))
    tools = client.get("/api/v1/bootstrap").json()["tools"]
    assert {"read", "write", "edit", "bash", "web_fetch"}.issubset(tools)
    assert "代码执行" not in tools


def test_each_shipped_tool_manifest_points_to_a_real_handler():
    root = files("futurework").joinpath("abilities", "tools")
    for directory in root.iterdir():
        manifest = directory.joinpath("manifest.toml")
        if not manifest.is_file():
            continue
        definition = tomllib.loads(manifest.read_text(encoding="utf-8"))
        assert definition["enabled"] is True
        module_name, method_name = definition["executor"].split(":")
        assert callable(getattr(import_module(module_name), method_name))
