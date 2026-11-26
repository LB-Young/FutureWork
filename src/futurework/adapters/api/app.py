"""Create the headless API adapter with optional configured bearer-key access."""

import hmac
import os

from fastapi.responses import JSONResponse

from futurework.api.app import create_app as create_core_app
from futurework.home import ensure_home
from futurework.config import load_config


def create_app(home=None, db_path=None):
    """Expose the same API resources without mounting the Web interface."""
    selected_home = ensure_home(home)
    config = load_config(selected_home)
    app = create_core_app(selected_home, db_path, include_web=False, source="public_api")
    key_name = config.get("entrypoints", {}).get("api", {}).get("key_env", "FUTUREWORK_API_KEY")
    expected = os.environ.get(key_name, "")
    if not expected:
        raise ValueError(f"headless API requires {key_name}")

    @app.middleware("http")
    async def authenticate(request, call_next):
        if request.url.path in {"/health", "/api/v1/health"}:
            return await call_next(request)
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied, expected):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    return app
