"""Expose the reviewed arithmetic evaluator used by the built-in dispatcher."""

import ast

from futurework.runtime.tool_dispatch import _calculate


def calculate(expression: str) -> int | float:
    """Evaluate a bounded arithmetic expression without Python execution."""
    if not isinstance(expression, str) or len(expression) > 100:
        raise ValueError("invalid expression")
    return _calculate(ast.parse(expression, mode="eval").body)
