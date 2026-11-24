"""Expose a small Bamboo-inspired built-in tool set with per-Agent grants."""

from __future__ import annotations

import ast
import asyncio
from html.parser import HTMLParser
import ipaddress
from itertools import islice
import os
import operator
import re
import socket
import tempfile
from urllib.parse import urljoin, urlsplit
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from futurework.extension_system.skill_loader import load_skills


SCHEMAS = {
    "calculator": ("Evaluate basic arithmetic.", {"expression": {"type": "string"}}, ["expression"]),
    "read_file": ("Read a UTF-8 file inside the configured workspace.",
                  {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["path"]),
    "glob_files": ("List files matching a glob inside the configured workspace.",
                   {"pattern": {"type": "string"}}, ["pattern"]),
    "grep_files": ("Search workspace text files with a regular expression.",
                   {"pattern": {"type": "string"}, "glob": {"type": "string"}}, ["pattern"]),
    "read": ("Read a workspace UTF-8 file with optional line bounds.",
             {"file_path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["file_path"]),
    "glob": ("List workspace files matching a glob pattern.",
             {"pattern": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}}, ["pattern"]),
    "grep": ("Search workspace text files with a regular expression.",
             {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"},
              "context": {"type": "integer"}, "limit": {"type": "integer"}}, ["pattern"]),
    "write": ("Write a UTF-8 file in the workspace.",
              {"file_path": {"type": "string"}, "content": {"type": "string"}}, ["file_path", "content"]),
    "edit": ("Replace exact text in an existing workspace file.",
             {"file_path": {"type": "string"}, "old_string": {"type": "string"},
              "new_string": {"type": "string"}, "mode": {"type": "string"},
              "edits": {"type": "array", "items": {"type": "object"}}}, ["file_path"]),
    "skill_load": ("Load an enabled Skill's full instructions.",
                   {"name": {"type": "string"}}, ["name"]),
    "web_fetch": ("Fetch public web page text.",
                  {"url": {"type": "string"}, "max_length": {"type": "integer"}}, ["url"]),
    "url_to_md": ("Fetch a public page and save readable Markdown in the workspace.",
                 {"url": {"type": "string"}, "output_path": {"type": "string"},
                  "overwrite": {"type": "boolean"}}, ["url"]),
    "bash": ("Execute an approved shell command in the workspace.",
             {"command": {"type": "string"}, "cwd": {"type": "string"},
              "timeout": {"type": "integer"}}, ["command"]),
}

PUBLIC_TOOLS = tuple(name for name in SCHEMAS if name not in {"read_file", "glob_files", "grep_files"})


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """One authorized tool invocation in an Agent run."""

    agent_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Bounded text returned to the model after tool execution."""

    content: str
    success: bool = True


def schemas_for(grants: list[str] | tuple[str, ...]) -> list[dict]:
    """Expose only implemented tools explicitly granted to this Agent."""
    return [{"type": "function", "function": {"name": name, "description": SCHEMAS[name][0],
            "parameters": {"type": "object", "properties": SCHEMAS[name][1], "required": SCHEMAS[name][2],
                           "additionalProperties": False}}} for name in grants if name in SCHEMAS]


def _workspace(config: dict) -> Path:
    raw = Path(config["tool_runtime"]["workspace"])
    return (raw if raw.is_absolute() else config["home"] / raw).resolve()


def _path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("path escapes the configured workspace")
    return path


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _calculate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _calculate(node.left), _calculate(node.right)
        if abs(left) > 1e12 or abs(right) > 1e12 or isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("calculation exceeds limit")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calculate(node.operand))
    raise ValueError("unsupported expression")


def _replace_file(path: Path, content: str) -> None:
    """Write a workspace file atomically so interrupted edits keep old content."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class _PageText(HTMLParser):
    """Extract visible text without script or style blocks."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        elif tag in {"p", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        elif tag in {"p", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


async def _public_url(url: str) -> bool:
    """Reject local/private hosts and DNS results before an outbound fetch."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return False
        addresses = await asyncio.to_thread(socket.getaddrinfo, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (ValueError, OSError):
        return False


async def _fetch_public(url: str, config: dict) -> str:
    """Fetch a bounded public page and recheck every redirect destination."""
    maximum = config["tool_runtime"]["max_web_bytes"]
    async with httpx.AsyncClient(timeout=config["tool_runtime"]["web_timeout_seconds"], follow_redirects=False) as client:
        for _ in range(config["tool_runtime"]["max_web_redirects"] + 1):
            if not await _public_url(url):
                raise ValueError("URL is not a public HTTP(S) address")
            async with client.stream("GET", url, headers={"User-Agent": config["tool_runtime"]["web_user_agent"]}) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect has no location")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > maximum:
                        raise ValueError("web response exceeds limit")
                    chunks.append(chunk)
                raw = b"".join(chunks).decode("utf-8", errors="replace")
                if "html" in response.headers.get("content-type", "").lower() or "<html" in raw[:500].lower():
                    parser = _PageText()
                    parser.feed(raw)
                    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
                return raw.strip()
        raise ValueError("too many redirects")


async def _drain(reader: asyncio.StreamReader, limit: int) -> bytes:
    """Drain process output while retaining at most the configured byte limit."""
    parts = []
    kept = 0
    while chunk := await reader.read(4096):
        if kept < limit:
            part = chunk[:limit - kept]
            parts.append(part)
            kept += len(part)
    return b"".join(parts)


class ToolRegistry:
    """Own the schemas, grants, and execution policy for one Agent run."""

    def __init__(self, agent_id: str, grants: tuple[str, ...] | list[str], config: dict) -> None:
        self.agent_id = agent_id
        self.grants = tuple(grants)
        self.config = config

    def schemas(self) -> list[dict]:
        """Expose only implemented tools granted to this Agent."""
        return schemas_for(self.grants)

    def execute_sync(self, request: ToolRequest) -> ToolResult:
        """Recheck grants and keep filesystem reads inside the workspace."""
        if request.agent_id != self.agent_id:
            return ToolResult("tool belongs to another Agent", False)
        if request.name not in SCHEMAS or request.name not in self.grants:
            return ToolResult("tool is not granted", False)
        args = request.arguments
        if not isinstance(args, dict):
            return ToolResult("invalid tool arguments", False)
        name = {"read": "read_file", "glob": "glob_files", "grep": "grep_files"}.get(request.name, request.name)
        if name == "read_file" and request.name == "read":
            args = {**args, "path": args.get("file_path")}
        if name in {"glob_files", "grep_files"} and request.name in {"glob", "grep"}:
            args = {**args, "path": args.get("path", ".")}
        limit = self.config["tool_runtime"]["max_result_chars"]
        root = _workspace(self.config)
        try:
            if name == "calculator":
                expression = args["expression"]
                if not isinstance(expression, str) or len(expression) > self.config["tool_runtime"]["max_expression_chars"]:
                    raise ValueError("invalid expression")
                content = str(_calculate(ast.parse(expression, mode="eval").body))
            elif name == "read_file":
                path = _path(root, args["path"])
                if not path.is_file() or path.stat().st_size > self.config["tool_runtime"]["max_file_bytes"]:
                    raise ValueError("file unavailable or too large")
                offset = max(0, int(args.get("offset", 0)))
                line_limit = max(1, min(int(args.get("limit", 100)), self.config["tool_runtime"]["max_lines"]))
                content = "\n".join(path.read_text(encoding="utf-8").splitlines()[offset:offset + line_limit])
            elif name == "glob_files":
                pattern = args["pattern"]
                if not isinstance(pattern, str) or len(pattern) > self.config["tool_runtime"]["max_pattern_chars"] or ".." in Path(pattern).parts or Path(pattern).is_absolute():
                    raise ValueError("invalid glob")
                search_root = _path(root, args.get("path", "."))
                matches = (path for path in islice(search_root.glob(pattern), self.config["tool_runtime"]["max_scanned_files"])
                           if path.is_file() and path.resolve().is_relative_to(root))
                max_matches = min(int(args.get("limit", self.config["tool_runtime"]["max_matches"])), self.config["tool_runtime"]["max_matches"])
                content = "\n".join(str(path.relative_to(root)) for path in islice(matches, max(1, max_matches)))
            elif name == "grep_files":
                if not isinstance(args["pattern"], str) or len(args["pattern"]) > self.config["tool_runtime"]["max_pattern_chars"]:
                    raise ValueError("invalid pattern")
                pattern = re.compile(args["pattern"])
                glob = args.get("glob", "**/*")
                if not isinstance(glob, str) or len(glob) > self.config["tool_runtime"]["max_pattern_chars"] or ".." in Path(glob).parts or Path(glob).is_absolute():
                    raise ValueError("invalid glob")
                matches = []
                search_root = _path(root, args.get("path", "."))
                max_matches = min(int(args.get("limit", self.config["tool_runtime"]["max_matches"])), self.config["tool_runtime"]["max_matches"])
                context_lines = min(max(0, int(args.get("context", 0))), self.config["tool_runtime"]["max_context_lines"])
                for path in islice(search_root.glob(glob), self.config["tool_runtime"]["max_scanned_files"]):
                    if not path.is_file() or not path.resolve().is_relative_to(root) or path.stat().st_size > self.config["tool_runtime"]["max_file_bytes"]:
                        continue
                    try:
                        lines = path.read_text(encoding="utf-8").splitlines()
                        for line_no, line in enumerate(lines, 1):
                            if pattern.search(line):
                                start = max(0, line_no - 1 - context_lines)
                                end = min(len(lines), line_no + context_lines)
                                snippet = "\n".join(f"{index + 1}: {lines[index]}" for index in range(start, end))
                                matches.append(f"{path.relative_to(root)}:{line_no}\n{snippet}")
                            if len(matches) >= max_matches:
                                break
                    except (OSError, UnicodeError):
                        continue
                    if len(matches) >= max_matches:
                        break
                content = "\n".join(matches)
            elif name == "write":
                content = args["content"]
                if not isinstance(content, str) or len(content.encode("utf-8")) > self.config["tool_runtime"]["max_file_bytes"]:
                    raise ValueError("content exceeds file limit")
                path = _path(root, args["file_path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                _replace_file(path, content)
                content = f"Wrote {path.relative_to(root)}"
            elif name == "edit":
                path = _path(root, args["file_path"])
                if not path.is_file() or path.stat().st_size > self.config["tool_runtime"]["max_file_bytes"]:
                    raise ValueError("file unavailable or too large")
                original = path.read_text(encoding="utf-8")
                mode = args.get("mode", "replace")
                if mode == "replace":
                    old, new = args["old_string"], args.get("new_string", "")
                    if not isinstance(old, str) or not old or not isinstance(new, str) or old not in original:
                        raise ValueError("old_string must match existing text")
                    updated = original.replace(old, new, 1)
                elif mode == "multi_replace":
                    edits = args["edits"]
                    if not isinstance(edits, list) or not edits or any(not isinstance(item, dict) or not item.get("old") or original.count(item["old"]) != 1 for item in edits):
                        raise ValueError("each old string must match exactly once")
                    updated = original
                    for item in edits:
                        updated = updated.replace(item["old"], item.get("new", ""), 1)
                else:
                    raise ValueError("unsupported edit mode")
                if len(updated.encode("utf-8")) > self.config["tool_runtime"]["max_file_bytes"]:
                    raise ValueError("edited file exceeds limit")
                _replace_file(path, updated)
                content = f"Edited {path.relative_to(root)}"
            elif name == "skill_load":
                skill_id = args["name"]
                if skill_id not in self.config["agent_extensions"].get(request.agent_id, {}).get("skills", []):
                    return ToolResult("skill is not enabled for this Agent", False)
                content = load_skills(self.config["home"], [skill_id], self.config["skill_policy"].get("max_skill_chars", limit))
            else:
                return ToolResult("tool requires asynchronous dispatch", False)
            return ToolResult(content[:limit] or "(no result)")
        except (OSError, ValueError, TypeError, KeyError, SyntaxError, ZeroDivisionError, OverflowError, re.error) as error:
            return ToolResult(f"tool failed: {type(error).__name__}", False)


    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Run a permitted tool using this Agent's fixed grants and config."""
        request = ToolRequest(self.agent_id, name, arguments)
        if request.name not in {"web_fetch", "url_to_md", "bash"}:
            return self.execute_sync(request)
        if request.name not in self.grants:
            return ToolResult("tool is not granted", False)
        args = request.arguments
        if not isinstance(args, dict):
            return ToolResult("invalid tool arguments", False)
        settings = self.config["tool_runtime"]
        try:
            if request.name in {"web_fetch", "url_to_md"}:
                url = args["url"]
                if not isinstance(url, str) or len(url) > settings["max_url_chars"]:
                    raise ValueError("invalid URL")
                content = await _fetch_public(url, self.config)
                if request.name == "web_fetch":
                    length = max(1, min(int(args.get("max_length", settings["max_result_chars"])), settings["max_result_chars"]))
                    return ToolResult(content[:length] or "(empty page)")
                path = _path(_workspace(self.config), args.get("output_path") or "web-page.md")
                if path.exists() and not args.get("overwrite", False):
                    raise ValueError("output file already exists")
                markdown = f"# 网页内容\n\n来源：{url}\n\n{content}\n"
                if len(markdown.encode("utf-8")) > settings["max_file_bytes"]:
                    raise ValueError("page exceeds file limit")
                path.parent.mkdir(parents=True, exist_ok=True)
                _replace_file(path, markdown)
                return ToolResult(f"Saved {path.relative_to(_workspace(self.config))}")
            if settings.get("allow_shell") is not True:
                return ToolResult("bash is disabled; set tool_runtime.allow_shell = true", False)
            command = args["command"]
            if not isinstance(command, str) or not command.strip() or len(command) > settings["max_command_chars"]:
                raise ValueError("invalid command")
            cwd = _path(_workspace(self.config), args.get("cwd", "."))
            if not cwd.is_dir():
                raise ValueError("invalid cwd")
            timeout = max(1, min(int(args.get("timeout", settings["shell_timeout_seconds"])), settings["shell_timeout_seconds"]))
            shell_env = {name: os.environ[name] for name in settings["shell_env_allowlist"] if name in os.environ}
            process = await asyncio.create_subprocess_exec("/bin/sh", "-c", command, cwd=str(cwd), env=shell_env,
                                                           stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr, _ = await asyncio.wait_for(asyncio.gather(
                    _drain(process.stdout, settings["max_result_chars"]),
                    _drain(process.stderr, settings["max_result_chars"]), process.wait()), timeout=timeout)
            except TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult("command timed out", False)
            content = f"returncode: {process.returncode}\nstdout:\n{stdout.decode(errors='replace')}\nstderr:\n{stderr.decode(errors='replace')}"
            return ToolResult(content[:settings["max_result_chars"]], process.returncode == 0)
        except (OSError, ValueError, TypeError, KeyError, httpx.HTTPError) as error:
            return ToolResult(f"tool failed: {type(error).__name__}", False)


def execute(request: ToolRequest, grants: list[str], config: dict) -> ToolResult:
    """Compatibility entry point for synchronous tool callers."""
    return ToolRegistry(request.agent_id, grants, config).execute_sync(request)


async def execute_async(request: ToolRequest, grants: list[str], config: dict) -> ToolResult:
    """Compatibility entry point for asynchronous tool callers."""
    return await ToolRegistry(request.agent_id, grants, config).execute(request.name, request.arguments)
