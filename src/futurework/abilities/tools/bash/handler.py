"""Run an explicitly enabled shell command from the configured workspace."""

import asyncio
import os

from futurework.abilities.tools.common import within, workspace


async def _drain(reader: asyncio.StreamReader, limit: int) -> bytes:
    """Drain output while retaining only a bounded prefix."""
    parts = []
    kept = 0
    while chunk := await reader.read(4096):
        if kept < limit:
            part = chunk[:limit - kept]
            parts.append(part)
            kept += len(part)
    return b"".join(parts)


async def run(args: dict, config: dict) -> tuple[str, bool]:
    """Execute under the configured shell gate, timeout and environment allowlist."""
    settings = config["tool_runtime"]
    if settings.get("allow_shell") is not True:
        return "bash is disabled; set tool_runtime.allow_shell = true", False
    command = args["command"]
    if not isinstance(command, str) or not command.strip() or len(command) > settings["max_command_chars"]:
        raise ValueError("invalid command")
    cwd = within(workspace(config), args.get("cwd", "."))
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
        return "command timed out", False
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    content = f"returncode: {process.returncode}\nstdout:\n{stdout.decode(errors='replace')}\nstderr:\n{stderr.decode(errors='replace')}"
    return content[:settings["max_result_chars"]], process.returncode == 0
