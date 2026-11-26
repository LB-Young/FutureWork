"""Expose local administration, Web, desktop App, headless API, and chat entries."""

import argparse
import asyncio

from futurework.bootstrap import validate_home
from futurework.home import ensure_home


def main(argv: list[str] | None = None) -> int:
    """Parse a command, initialize the selected home, and run its entry point."""
    parser = argparse.ArgumentParser(prog="futurework")
    parser.add_argument("--home", help="Override ~/.FutureWork")
    parser.add_argument("command", nargs="?", choices=("init", "paths", "doctor", "serve", "app", "api", "chat"), default="serve")
    parser.add_argument("--conversation", default="assistant", help="Conversation ID for chat")
    parser.add_argument("--message", help="One chat message")
    args = parser.parse_args(argv)
    home = ensure_home(args.home)
    if args.command in {"init", "paths"}:
        print(home)
        return 0
    configuration = validate_home(home)
    if args.command == "doctor":
        print(f"FutureWork configuration is valid: {home}")
        from futurework.config import load_config
        from futurework.integrations.agent_backends import AgentBackendRegistry

        config = load_config(home)
        backends = AgentBackendRegistry(config)

        async def inspect_backends() -> bool:
            healthy = True
            for agent_id, execution in config["agent_execution"].items():
                backend = backends.for_agent(agent_id)
                if backend is None:
                    continue
                try:
                    result = await backend.health()
                except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as error:
                    result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
                label = "ready" if result["ok"] else "unavailable"
                print(f"{agent_id} ({execution['kind']}): {label}")
                if not result["ok"]:
                    print(f"  {result.get('error', 'health check failed')}")
                    healthy = False
            return healthy

        healthy = asyncio.run(inspect_backends())
        print("CLI checks do not test model account balance or a full Agent turn.")
        return 0 if healthy else 1
    if args.command == "chat":
        if not args.message:
            parser.error("chat requires --message")
        from futurework.adapters.cli.chat import run
        print(run(home, args.conversation, args.message))
        return 0
    if args.command == "app":
        from futurework.adapters.app.main import launch
        launch(home)
        return 0
    if args.command == "api":
        from futurework.adapters.api.app import create_app
    else:
        from futurework.adapters.web.app import create_app
    import uvicorn

    server = configuration["app"]["server"]
    uvicorn.run(create_app(home), host=server["host"], port=server["port"])
    return 0
