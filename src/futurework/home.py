"""Resolve and initialize the user-owned FutureWork directory without overwrites."""

import os
from importlib.resources import files
from pathlib import Path


DIRECTORIES = {
    "": "用户配置和运行数据的根目录。",
    "agents": "人工编写或应用生成的 Agent 好友 TOML 配置；assistant.toml 定义小未。",
    "teams": "人工编写或应用生成的 Team 与群聊 TOML 配置。",
    "prompts": "由 Agent TOML 显式引用的提示词文件。",
    "skills": "用户人工安装的 Skill 包，每个包以 SKILL.md 为入口。",
    "workflows": "用户人工编写或安装的 Workflow 定义。",
    "mcp": "用户配置的 MCP 连接定义，不保存明文密钥。",
    "memory": "按会话作用域隔离的记忆文件。",
    "memory/assistant": "小未与用户私聊的专属记忆。",
    "memory/agents": "每位 Agent 好友各自的私聊记忆子目录。",
    "memory/teams": "每个 Team 各自的群共享记忆子目录。",
    "data": "SQLite、任务产物与其他持久运行数据。",
    "logs": "脱敏后的运行日志。",
    "cache": "可以重新生成的缓存。",
    "workspace": "Agent 内置文件工具允许读取的用户工作区。",
}


def home_path(override: str | Path | None = None) -> Path:
    """Choose an explicit home, FUTUREWORK_HOME, or ~/.futurework."""
    selected = override if override is not None else os.environ.get("FUTUREWORK_HOME")
    return Path(selected).expanduser().resolve() if selected else Path.home() / ".futurework"


def ensure_home(override: str | Path | None = None) -> Path:
    """Create documented directories and missing bundled defaults on first use."""
    home = home_path(override)
    resource_root = files("futurework").joinpath("defaults")
    for relative, purpose in DIRECTORIES.items():
        directory = home / relative
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        explanation = directory / "README.md"
        if not explanation.exists():
            explanation.write_text(f"# {directory.name}\n\n{purpose}\n", encoding="utf-8")
    for source in resource_root.iterdir():
        if not source.name.endswith(".toml"):
            continue
        target = home / source.name
        if not target.exists():
            target.write_bytes(source.read_bytes())
    for category in ("agents", "teams"):
        target_dir = home / category
        if not any(target_dir.glob("*.toml")):
            for source in resource_root.joinpath(category).iterdir():
                if source.name.endswith(".toml"):
                    (target_dir / source.name).write_bytes(source.read_bytes())
        memory_root = home / "memory" / category
        for definition in target_dir.glob("*.toml"):
            if category == "agents" and definition.stem == "assistant":
                continue
            memory_dir = memory_root / definition.stem
            memory_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            explanation = memory_dir / "README.md"
            if not explanation.exists():
                explanation.write_text(
                    f"# {definition.stem}\n\nPrivate memory for this {category[:-1]} scope.\n", encoding="utf-8"
                )
    return home
