"""Read explicitly enabled user Skill instructions without executing their code."""

import re
from pathlib import Path


SKILL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def load_skills(home: Path, skill_ids: list[str], max_chars: int) -> str:
    """Return bounded SKILL.md text for one Agent from the selected user home."""
    if max_chars <= 0:
        raise ValueError("max_skill_chars must be positive")
    parts = []
    for skill_id in skill_ids:
        if not isinstance(skill_id, str) or not SKILL_ID.fullmatch(skill_id):
            raise ValueError(f"invalid Skill ID: {skill_id!r}")
        path = home / "skills" / skill_id / "SKILL.md"
        if not path.resolve().is_relative_to((home / "skills").resolve()):
            raise ValueError(f"Skill path escapes user home: {skill_id}")
        if not path.is_file():
            raise ValueError(f"missing Skill: {path}")
        content = path.read_text(encoding="utf-8")
        parts.append(f"Skill {skill_id}:\n{content}")
    result = "\n\n".join(parts)
    if len(result) > max_chars:
        raise ValueError("enabled Skill instructions exceed max_skill_chars")
    return result
