"""Fetch a public page and save its readable text as workspace Markdown."""

from futurework.abilities.tools.common import replace_file, within, workspace
from futurework.abilities.tools.web_fetch.handler import fetch_public


async def run(args: dict, config: dict) -> str:
    """Write a bounded Markdown capture after URL and workspace validation."""
    url = args["url"]
    content = await fetch_public(url, config)
    root = workspace(config)
    path = within(root, args.get("output_path") or "web-page.md")
    if path.exists() and not args.get("overwrite", False):
        raise ValueError("output file already exists")
    markdown = f"# 网页内容\n\n来源：{url}\n\n{content}\n"
    if len(markdown.encode("utf-8")) > config["tool_runtime"]["max_file_bytes"]:
        raise ValueError("page exceeds file limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_file(path, markdown)
    return f"Saved {path.relative_to(root)}"
