"""Expose a small Bamboo-inspired built-in tool set with per-Agent grants."""

from __future__ import annotations

import ast
from itertools import islice
import operator
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMAS = {
    "calculator": ("Evaluate basic arithmetic.", {"expression": {"type": "string"}}, ["expression"]),
    "read_file": ("Read a UTF-8 file inside the configured workspace.",
                  {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["path"]),
    "glob_files": ("List files matching a glob inside the configured workspace.",
                   {"pattern": {"type": "string"}}, ["pattern"]),
    "grep_files": ("Search workspace text files with a regular expression.",
                   {"pattern": {"type": "string"}, "glob": {"type": "string"}}, ["pattern"]),
}


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


def schemas_for(grants: list[str]) -> list[dict]:
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


def execute(request: ToolRequest, grants: list[str], config: dict) -> ToolResult:
    """Check grants again at dispatch and keep all filesystem reads in workspace."""
    if request.name not in SCHEMAS or request.name not in grants:
        return ToolResult("tool is not granted", False)
    args = request.arguments
    if not isinstance(args, dict):
        return ToolResult("invalid tool arguments", False)
    limit = config["tool_runtime"]["max_result_chars"]
    root = _workspace(config)
    try:
        if request.name == "calculator":
            expression = args["expression"]
            if not isinstance(expression, str) or len(expression) > config["tool_runtime"]["max_expression_chars"]:
                raise ValueError("invalid expression")
            content = str(_calculate(ast.parse(expression, mode="eval").body))
        elif request.name == "read_file":
            path = _path(root, args["path"])
            if not path.is_file() or path.stat().st_size > config["tool_runtime"]["max_file_bytes"]:
                raise ValueError("file unavailable or too large")
            offset = max(0, int(args.get("offset", 0)))
            line_limit = max(1, min(int(args.get("limit", 100)), config["tool_runtime"]["max_lines"]))
            content = "\n".join(path.read_text(encoding="utf-8").splitlines()[offset:offset + line_limit])
        elif request.name == "glob_files":
            pattern = args["pattern"]
            if not isinstance(pattern, str) or len(pattern) > config["tool_runtime"]["max_pattern_chars"] or ".." in Path(pattern).parts or Path(pattern).is_absolute():
                raise ValueError("invalid glob")
            matches = (path for path in islice(root.glob(pattern), config["tool_runtime"]["max_scanned_files"])
                       if path.is_file() and path.resolve().is_relative_to(root))
            content = "\n".join(str(path.relative_to(root)) for path in islice(matches, config["tool_runtime"]["max_matches"]))
        else:
            if not isinstance(args["pattern"], str) or len(args["pattern"]) > config["tool_runtime"]["max_pattern_chars"]:
                raise ValueError("invalid pattern")
            pattern = re.compile(args["pattern"])
            glob = args.get("glob", "**/*")
            if not isinstance(glob, str) or len(glob) > config["tool_runtime"]["max_pattern_chars"] or ".." in Path(glob).parts or Path(glob).is_absolute():
                raise ValueError("invalid glob")
            matches = []
            for path in islice(root.glob(glob), config["tool_runtime"]["max_scanned_files"]):
                if not path.is_file() or not path.resolve().is_relative_to(root) or path.stat().st_size > config["tool_runtime"]["max_file_bytes"]:
                    continue
                try:
                    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                        if pattern.search(line):
                            matches.append(f"{path.relative_to(root)}:{line_no}: {line}")
                        if len(matches) >= config["tool_runtime"]["max_matches"]:
                            break
                except (OSError, UnicodeError):
                    continue
                if len(matches) >= config["tool_runtime"]["max_matches"]:
                    break
            content = "\n".join(matches)
        return ToolResult(content[:limit] or "(no result)")
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, ZeroDivisionError, OverflowError, re.error) as error:
        return ToolResult(f"tool failed: {type(error).__name__}", False)
