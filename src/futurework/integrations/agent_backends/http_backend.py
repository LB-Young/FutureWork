"""Call a configured HTTP Agent endpoint using the FutureWork Agent v1 envelope."""

import httpx
import os

from .base import AgentRequest


class HttpBackend:
    """Use a fixed, configured endpoint for a self-written or domain Agent."""

    def __init__(self, profile: dict):
        self.profile = profile
        self.endpoint = profile["endpoint"]
        if not self.endpoint.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
            raise ValueError("external Agent endpoint must be loopback or HTTPS")

    def _headers(self) -> dict[str, str]:
        """Resolve a bearer credential at call time without storing it in TOML."""
        if not (key_name := self.profile.get("auth_env")):
            return {}
        secret = os.environ.get(key_name)
        if not secret:
            raise RuntimeError(f"external Agent credential is missing: {key_name}")
        return {"Authorization": f"Bearer {secret}"}

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=self.profile.get("health_timeout_seconds", 10)) as client:
            response = await client.get(self.endpoint.rstrip("/") + "/health", headers=self._headers())
            return {"ok": response.is_success, "status": response.status_code}

    async def run(self, request: AgentRequest) -> str:
        payload = {"protocol": "futurework-agent-v1", "agent_id": request.agent_id,
                   "scope": {"type": request.scope_type, "id": request.scope_id},
                   "message": request.prompt,
                   "history": list(request.history[-self.profile.get("history_messages", 20):])}
        async with httpx.AsyncClient(timeout=self.profile.get("timeout_seconds", 120),
                                     follow_redirects=False) as client:
            response = await client.post(self.endpoint, json=payload, headers=self._headers())
            response.raise_for_status()
            if len(response.content) > self.profile.get("max_output_bytes", 1000000):
                raise RuntimeError("external Agent output exceeds configured limit")
            answer = response.json().get("text")
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError("external Agent returned no answer")
            return answer.strip()[:self.profile.get("max_answer_chars", 50000)]
