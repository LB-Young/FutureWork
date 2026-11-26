"""Classify failures consistently at task, Agent, Team and tool boundaries."""

import asyncio
import httpx


class UncertainOutcomeError(RuntimeError):
    """A prior tool or external Agent may already have changed outside state."""


def retryable(error: BaseException) -> bool:
    """Retry only transport failures without an uncertain side effect."""
    if isinstance(error, (UncertainOutcomeError, PermissionError, ValueError, KeyError, TypeError,
                          asyncio.CancelledError)):
        return False
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {408, 429, 500, 502, 503, 504}
    return isinstance(error, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError,
                              TimeoutError, ConnectionError))


async def retry_operation(operation, policy: dict):
    """Apply one configured bounded retry budget to a replay-safe operation."""
    attempts = policy["max_attempts"]
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception as error:
            if attempt + 1 >= attempts or not retryable(error):
                raise
            await asyncio.sleep(min(policy["max_backoff_seconds"],
                                    policy["base_backoff_seconds"] * 2 ** attempt))
