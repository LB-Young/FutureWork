"""Install optional example Agents and Teams only for tests that require them."""

from pathlib import Path
from shutil import copy2

from futurework.home import ensure_home


FIXTURES = Path(__file__).parent / "fixtures"


def sample_home(path: Path) -> Path:
    """Prepare user-owned examples without changing package defaults."""
    home = ensure_home(path)
    for category, target in (("sample_agents", "agents"), ("sample_teams", "teams")):
        for source in (FIXTURES / category).glob("*.toml"):
            destination = home / target / source.name
            if not destination.exists():
                copy2(source, destination)
    return ensure_home(home)
