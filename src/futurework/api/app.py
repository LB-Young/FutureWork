"""Build the initial FastAPI shell and expose configuration health endpoints."""

from pathlib import Path

from fastapi import FastAPI

from futurework.bootstrap import validate_home


def create_app(home: Path) -> FastAPI:
    """Create an API shell after user configuration passes validation."""
    config = validate_home(home)
    app = FastAPI(title="FutureWork", version="0.1.0")

    @app.get("/api/v1/health")
    def health() -> dict:
        """Report that the configuration loaded and the API shell is running."""
        return {"status": "ok", "agents": len(config["agents"]), "teams": len(config["teams"])}

    return app
