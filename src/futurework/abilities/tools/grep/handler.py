"""Search bounded workspace text files with a regular expression."""

from itertools import islice
from pathlib import Path
import re

from futurework.abilities.tools.common import within, workspace


def run(args: dict, config: dict) -> str:
    """Return matching lines and optional nearby context with file locations."""
    settings = config["tool_runtime"]
    expression = args["pattern"]
    if not isinstance(expression, str) or len(expression) > settings["max_pattern_chars"]:
        raise ValueError("invalid pattern")
    pattern = re.compile(expression)
    glob = args.get("glob", "**/*")
    if not isinstance(glob, str) or len(glob) > settings["max_pattern_chars"] or ".." in Path(glob).parts or Path(glob).is_absolute():
        raise ValueError("invalid glob")
    root = workspace(config)
    search_root = within(root, args.get("path", "."))
    count = max(1, min(int(args.get("limit", settings["max_matches"])), settings["max_matches"]))
    nearby = min(max(0, int(args.get("context", 0))), settings["max_context_lines"])
    matches = []
    for path in islice(search_root.glob(glob), settings["max_scanned_files"]):
        if not path.is_file() or not path.resolve().is_relative_to(root) or path.stat().st_size > settings["max_file_bytes"]:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for line_no, line in enumerate(lines, 1):
                if pattern.search(line):
                    start = max(0, line_no - 1 - nearby)
                    end = min(len(lines), line_no + nearby)
                    snippet = "\n".join(f"{index + 1}: {lines[index]}" for index in range(start, end))
                    matches.append(f"{path.relative_to(root)}:{line_no}\n{snippet}")
                if len(matches) >= count:
                    break
        except (OSError, UnicodeError):
            continue
        if len(matches) >= count:
            break
    return "\n".join(matches)
