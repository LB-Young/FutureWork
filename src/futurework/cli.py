"""Expose local administration, Web, desktop App, headless API, and chat entries."""

import argparse

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
        return 0
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
