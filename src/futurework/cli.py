"""Expose the init, paths, doctor, and serve commands for local use."""

import argparse

from futurework.bootstrap import validate_home
from futurework.home import ensure_home


def main(argv: list[str] | None = None) -> int:
    """Parse a command, initialize the selected home, and run its entry point."""
    parser = argparse.ArgumentParser(prog="futurework")
    parser.add_argument("--home", help="Override ~/.futurework")
    parser.add_argument("command", nargs="?", choices=("init", "paths", "doctor", "serve"), default="serve")
    args = parser.parse_args(argv)
    home = ensure_home(args.home)
    if args.command in {"init", "paths"}:
        print(home)
        return 0
    configuration = validate_home(home)
    if args.command == "doctor":
        print(f"FutureWork configuration is valid: {home}")
        return 0
    from futurework.api.app import create_app
    import uvicorn

    server = configuration["app"]["server"]
    uvicorn.run(create_app(home), host=server["host"], port=server["port"])
    return 0
