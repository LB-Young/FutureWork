"""Create a validated, user-owned Skill package without overwriting existing files."""

import json
import re
import shutil
from pathlib import Path


SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def run(args: dict, config: dict) -> str:
    """Install one Skill under the user abilities directory after tool approval."""
    name = args["name"]
    description = args["description"].strip()
    instructions = args["instructions"].strip()
    limits = config["skill_creator"]
    if not isinstance(name, str) or len(name) > limits["max_name_chars"] or not SKILL_NAME.fullmatch(name):
        raise ValueError("Skill ID 只能使用小写字母、数字和连字符")
    if not 1 <= len(description) <= limits["max_description_chars"] or "\n" in description:
        raise ValueError("Skill 描述为空、过长或包含换行")
    if not 1 <= len(instructions) <= limits["max_instructions_chars"]:
        raise ValueError("Skill 说明为空或过长")
    home = Path(config["home"]).resolve()
    root = (home / "abilities" / "skills").resolve()
    if not root.is_relative_to(home):
        raise PermissionError("Skill 安装目录超出用户目录")
    path = root / name
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Skill {name} 已存在；请先审查原文件")
    path.mkdir(parents=True, mode=0o700)
    try:
        frontmatter = ("---\nname: " + name + "\ndescription: "
                       + json.dumps(description, ensure_ascii=False)
                       + "\nuser-invocable: true\n---\n\n")
        (path / "SKILL.md").write_text(frontmatter + instructions + "\n", encoding="utf-8")
        manifest = ("# 用户创建的 Skill；安装不会自动为任何 Agent 启用。\n"
                    "schema_version = 1\nid = " + json.dumps(name) + "\nversion = \"0.1.0\"\nkind = \"skill\"\nenabled = true\n")
        (path / "manifest.toml").write_text(manifest, encoding="utf-8")
    except Exception:
        shutil.rmtree(path)
        raise
    return json.dumps({"id": name, "path": str(path), "enabled_for_agents": False}, ensure_ascii=False)
