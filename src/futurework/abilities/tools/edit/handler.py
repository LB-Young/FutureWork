"""Apply exact text replacements to one bounded workspace file."""

from futurework.abilities.tools.common import replace_file, within, workspace


def run(args: dict, config: dict) -> str:
    """Replace one or several unique strings, then atomically write the result."""
    root = workspace(config)
    path = within(root, args["file_path"])
    maximum = config["tool_runtime"]["max_file_bytes"]
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("file unavailable or too large")
    original = path.read_text(encoding="utf-8")
    mode = args.get("mode", "replace")
    if mode == "replace":
        old, new = args["old_string"], args.get("new_string", "")
        if not isinstance(old, str) or not old or not isinstance(new, str) or old not in original:
            raise ValueError("old_string must match existing text")
        updated = original.replace(old, new, 1)
    elif mode == "multi_replace":
        edits = args["edits"]
        if not isinstance(edits, list) or not edits or any(not isinstance(item, dict) or not item.get("old") or original.count(item["old"]) != 1 for item in edits):
            raise ValueError("each old string must match exactly once")
        updated = original
        for item in edits:
            updated = updated.replace(item["old"], item.get("new", ""), 1)
    else:
        raise ValueError("unsupported edit mode")
    if len(updated.encode("utf-8")) > maximum:
        raise ValueError("edited file exceeds limit")
    replace_file(path, updated)
    return f"Edited {path.relative_to(root)}"
