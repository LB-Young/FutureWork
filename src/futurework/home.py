"""Resolve and initialize the user-owned FutureWork directory without overwrites."""

import os
import shutil
import tomlkit
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
    "memory/assistant": "小未个人助理私聊的原始消息 JSONL 与经验 Markdown。",
    "memory/agents": "每位 Agent 好友各自的私聊 JSONL 与经验 Markdown。",
    "memory/teams": "每个群聊独立的消息 JSONL、话题索引与参与者经验 Markdown。",
    "data": "SQLite、任务产物与其他持久运行数据。",
    "logs": "脱敏后的运行日志。",
    "cache": "可以重新生成的缓存。",
    "workspace": "Agent 内置文件工具允许读取的用户工作区。",
    "abilities": "用户自行安装和构建的能力包；与应用内置 abilities 目录分开。",
    "abilities/tools": "用户工具定义与实现。",
    "abilities/skills": "用户 Skill 包。",
    "abilities/mcp": "用户 MCP 连接定义。",
    "abilities/workflows": "用户 Workflow 定义。",
    "abilities/friends": "用户新建的 Agent 好友 TOML。",
    "abilities/teams": "用户新建的群聊 TOML。",
}


def home_path(override: str | Path | None = None) -> Path:
    """Choose an explicit home, FUTUREWORK_HOME, or ~/.FutureWork."""
    selected = override if override is not None else os.environ.get("FUTUREWORK_HOME")
    return Path(selected).expanduser().resolve() if selected else Path.home() / ".FutureWork"


def ensure_home(override: str | Path | None = None) -> Path:
    """Create documented directories and missing bundled defaults on first use."""
    home = home_path(override)
    resource_root = files("futurework").joinpath("defaults")
    abilities_root = files("futurework").joinpath("abilities")
    legacy = Path.home() / ".futurework"
    if override is None and not os.environ.get("FUTUREWORK_HOME") and legacy.is_dir() and not home.exists():
        shutil.copytree(legacy, home, symlinks=True)
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
    assistant_file = home / "agents" / "assistant.toml"
    if assistant_file.is_file() and not any((home / root / "dynamic_plan" / "SKILL.md").is_file()
                                            for root in ("skills", "abilities/skills")):
        assistant_doc = tomlkit.parse(assistant_file.read_text(encoding="utf-8"))
        skills = list(assistant_doc.get("extensions", {}).get("skills", []))
        if "dynamic_plan" in skills:
            skills = [item for item in skills if item != "dynamic_plan"]
            if "skill-creator" not in skills:
                skills.append("skill-creator")
            assistant_doc["extensions"]["skills"] = skills
            tools = list(assistant_doc.get("tools", []))
            if "skill_create" not in tools:
                tools.append("skill_create")
                assistant_doc["tools"] = tools
            from futurework.abilities.tools.management import atomic_text
            atomic_text(assistant_file, tomlkit.dumps(assistant_doc))
    user_profile = home / "user.md"
    user_profile.touch(exist_ok=True)
    for category, source_category in (("agents", "friends"), ("teams", "teams")):
        target_dir = home / category
        for source in abilities_root.joinpath(source_category).iterdir():
            if source.name.endswith(".toml"):
                target = target_dir / source.name
                if not target.exists():
                    target.write_bytes(source.read_bytes())
        memory_root = home / "memory" / category
        for definition in target_dir.glob("*.toml"):
            if category == "agents" and definition.stem == "assistant":
                continue
            memory_dir = memory_root / definition.stem
            memory_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            explanation = memory_dir / "README.md"
            if not explanation.exists():
                explanation.write_text(
                    f"# {definition.stem}\n\n这里存放 {definition.stem} 对应的独立记忆；不同 Agent 或 Team 的内容不得混用。\n", encoding="utf-8"
                )
    from futurework.contexts.store import MemoryStore

    MemoryStore(home).ensure_profiles()
    return home
