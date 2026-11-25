"""Write a bounded UTF-8 file atomically inside the workspace."""

from futurework.abilities.tools.common import replace_file, within, workspace


def run(args: dict, config: dict) -> str:
    """Create or replace the selected file after validating the content size."""
    content = args["content"]
    if not isinstance(content, str) or len(content.encode("utf-8")) > config["tool_runtime"]["max_file_bytes"]:
        raise ValueError("content exceeds file limit")
    root = workspace(config)
    path = within(root, args["file_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_file(path, content)
    return f"Wrote {path.relative_to(root)}"
