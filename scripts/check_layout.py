"""Check that every project directory is documented and scripts explain themselves."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", ".pytest_cache", "__pycache__"}


def check() -> list[str]:
    """Return missing README files and script module headers."""
    problems = []
    for directory in ROOT.rglob("*"):
        if not directory.is_dir() or any(part in SKIP or part.endswith(".egg-info") for part in directory.relative_to(ROOT).parts):
            continue
        if not (directory / "README.md").is_file():
            problems.append(f"Missing README.md: {directory.relative_to(ROOT)}")
    for suffix in ("*.py", "*.js"):
        for script in ROOT.rglob(suffix):
            if any(part in SKIP for part in script.relative_to(ROOT).parts):
                continue
            beginning = script.read_text(encoding="utf-8").lstrip()
            if not beginning.startswith(('"""', "/*", "//")):
                problems.append(f"Missing script introduction: {script.relative_to(ROOT)}")
    return problems


if __name__ == "__main__":
    issues = check()
    if issues:
        raise SystemExit("\n".join(issues))
    print("Directory and script descriptions are complete.")
