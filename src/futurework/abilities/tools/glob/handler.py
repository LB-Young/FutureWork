"""Find workspace files by a bounded glob pattern."""

from itertools import islice
from pathlib import Path

from futurework.abilities.tools.common import within, workspace


def run(args: dict, config: dict) -> str:
    """List matching files without following results outside the workspace."""
    settings = config["tool_runtime"]
    pattern = args["pattern"]
    if not isinstance(pattern, str) or len(pattern) > settings["max_pattern_chars"] or ".." in Path(pattern).parts or Path(pattern).is_absolute():
        raise ValueError("invalid glob")
    root = workspace(config)
    search_root = within(root, args.get("path", "."))
    matches = (path for path in islice(search_root.glob(pattern), settings["max_scanned_files"])
               if path.is_file() and path.resolve().is_relative_to(root))
    count = max(1, min(int(args.get("limit", settings["max_matches"])), settings["max_matches"]))
    return "\n".join(str(path.relative_to(root)) for path in islice(matches, count))
