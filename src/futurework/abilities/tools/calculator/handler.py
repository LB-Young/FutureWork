"""Expose the reviewed arithmetic evaluator used by the built-in dispatcher."""

import ast
import operator

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _evaluate(node: ast.AST) -> int | float:
    """Recursively evaluate a limited arithmetic AST."""
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if abs(left) > 1e12 or abs(right) > 1e12 or isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("calculation exceeds limit")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.operand))
    raise ValueError("unsupported expression")


def calculate(expression: str, max_chars: int = 100) -> int | float:
    """Evaluate a bounded arithmetic expression without Python execution."""
    if not isinstance(expression, str) or len(expression) > max_chars:
        raise ValueError("invalid expression")
    return _evaluate(ast.parse(expression, mode="eval").body)


def run(args: dict, config: dict) -> str:
    """Evaluate an expression using the configured input length limit."""
    return str(calculate(args["expression"], config["tool_runtime"]["max_expression_chars"]))
