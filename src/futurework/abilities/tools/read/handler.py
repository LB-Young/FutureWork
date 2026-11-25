"""Read bounded UTF-8 lines from one workspace file."""

from futurework.abilities.tools.common import within, workspace


def run(args: dict, config: dict) -> str:
    """Return selected lines while enforcing workspace and file size limits."""
    root = workspace(config)
    path = within(root, args["path"])
    settings = config["tool_runtime"]
    if not path.is_file() or path.stat().st_size > settings["max_file_bytes"]:
        raise ValueError("file unavailable or too large")
    offset = max(0, int(args.get("offset", 0)))
    count = max(1, min(int(args.get("limit", 100)), settings["max_lines"]))
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[offset:offset + count])
