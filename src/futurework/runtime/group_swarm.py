"""Select bounded Team members for Swarm replies without a central Agent."""


def responders(members: list[dict], text: str, limit: int) -> list[dict]:
    """Honor explicit mentions or let active members each take one turn."""
    active = [member for member in members if member and member["status"] == "active"]
    mentioned = [member for member in active if f"@{member['name']}" in text]
    return (mentioned or active)[:limit]
