"""Load canonical kind values from the packaged defaults TOML once."""

import tomllib
from importlib.resources import files

with files("futurework").joinpath("defaults", "kinds.toml").open("rb") as source:
    KINDS = tomllib.load(source)

ASSISTANT = KINDS["conversation"]["assistant"]
FRIEND = KINDS["conversation"]["friend"]
TEAM = KINDS["conversation"]["team"]
SWARM = KINDS["team_mode"]["swarm"]
CONTROLLED = KINDS["team_mode"]["controlled"]
NATIVE = KINDS["execution"]["native"]
CODEX = KINDS["execution"]["codex"]
OPENCLAW = KINDS["execution"]["openclaw"]
CLAUDE_CODE = KINDS["execution"]["claude_code"]
PROCESS = KINDS["execution"]["process"]
HTTP = KINDS["execution"]["http"]
EXECUTION_KINDS = frozenset(KINDS["execution"].values())
DELEGATION_AUTO = KINDS["delegation_target"]["auto"]
