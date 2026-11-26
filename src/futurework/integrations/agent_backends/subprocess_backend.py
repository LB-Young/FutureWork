"""Execute bounded local Agent CLIs with explicit arguments and scoped input."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import tempfile
from uuid import NAMESPACE_URL, uuid5

from .base import AgentRequest


class SubprocessBackend:
    """Dispatch Codex, OpenClaw or JSON-line process profiles."""

    def __init__(self, kind: str, profile: dict):
        self.kind = kind
        self.profile = profile

    def _binary(self) -> str:
        name = self.profile.get("executable", {"codex_cli": "codex", "openclaw": "openclaw"}.get(self.kind))
        if not name or not (path := shutil.which(name)):
            raise RuntimeError(f"{self.kind} executable is unavailable: {name}")
        return path

    def _environment(self, binary: str) -> dict[str, str]:
        allowed = self.profile.get("environment", ["PATH", "HOME", "LANG", "TMPDIR"])
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        node_bin = self.profile.get("node_bin") or (str(Path(binary).parent) if self.kind == "openclaw" else None)
        if node_bin:
            env["PATH"] = f"{node_bin}:{env.get('PATH', '')}"
        return env

    async def health(self) -> dict:
        binary = self._binary()
        command = [binary, "config", "validate"] if self.kind == "openclaw" else [binary, "--version"]
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE, env=self._environment(binary))
        stdout, stderr = await asyncio.wait_for(process.communicate(), self.profile.get("health_timeout_seconds", 10))
        return {"ok": process.returncode == 0, "version": stdout.decode(errors="replace").strip() if process.returncode == 0 else "",
                "error": stderr.decode(errors="replace")[-1000:] if process.returncode else ""}

    async def run(self, request: AgentRequest) -> str:
        binary = self._binary()
        history_limit = self.profile.get("history_messages", 20)
        history = request.history[-history_limit:]
        prompt = (f"你是{request.name}。职责：{request.role}。仅依据以下当前会话材料完成请求。\n"
                  + "\n".join(f"{item.get('speaker', item.get('from', '消息'))}: {item.get('text', '')}"
                              for item in history)
                  + f"\n当前请求：{request.prompt}")
        if len(prompt) > self.profile.get("max_input_chars", 40000):
            raise ValueError("external Agent input exceeds configured limit")
        timeout = self.profile.get("timeout_seconds", 120)
        workdir = Path(self.profile.get("workdir", tempfile.gettempdir())).expanduser().resolve()
        if not workdir.is_dir():
            raise ValueError(f"external Agent workdir does not exist: {workdir}")
        with tempfile.TemporaryDirectory(prefix="futurework-agent-") as temporary:
            result_file = Path(temporary) / "last.txt"
            if self.kind == "codex_cli":
                sandbox = self.profile.get("sandbox", "read-only")
                if sandbox not in {"read-only", "workspace-write"}:
                    raise ValueError("Codex sandbox must be read-only or workspace-write")
                command = [binary, "exec", "--skip-git-repo-check", "-s", sandbox, "-C", str(workdir),
                           "-o", str(result_file), prompt]
            elif self.kind == "openclaw":
                session = str(uuid5(NAMESPACE_URL, f"futurework:{request.agent_id}:{request.scope_type}:{request.scope_id}"))
                command = [binary, "agent", "--local", "--json", "--session-id", session,
                           "--timeout", str(timeout), "--message", prompt]
                if self.profile.get("openclaw_agent_id"):
                    command += ["--agent", self.profile["openclaw_agent_id"]]
            else:
                command = [binary, *self.profile.get("arguments", [])]
            process = await asyncio.create_subprocess_exec(*command, cwd=workdir, env=self._environment(binary),
                                                            stdin=asyncio.subprocess.PIPE if self.kind == "process" else asyncio.subprocess.DEVNULL,
                                                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            payload = json.dumps({"protocol": "futurework-agent-v1", "agent_id": request.agent_id,
                                  "scope": {"type": request.scope_type, "id": request.scope_id},
                                  "message": request.prompt, "history": history}, ensure_ascii=False).encode() + b"\n"
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(payload if self.kind == "process" else None), timeout)
            except asyncio.TimeoutError as error:
                process.kill()
                await process.communicate()
                raise RuntimeError(f"{self.kind} timed out") from error
            limit = self.profile.get("max_output_bytes", 1000000)
            if len(stdout) > limit or len(stderr) > limit:
                raise RuntimeError(f"{self.kind} output exceeds configured limit")
            if process.returncode:
                raise RuntimeError(f"{self.kind} failed (exit {process.returncode}): {stderr.decode(errors='replace')[-500:]}")
            if self.kind == "codex_cli":
                answer = result_file.read_text(encoding="utf-8") if result_file.exists() else ""
            else:
                try:
                    raw = stdout.decode().strip()
                    result = json.loads(raw if self.kind == "openclaw" else raw.splitlines()[-1])
                except (ValueError, IndexError) as error:
                    raise RuntimeError(f"{self.kind} returned invalid JSON") from error
                if self.kind == "openclaw":
                    if result.get("status") in {"error", "failed"}:
                        raise RuntimeError("OpenClaw reported a failed Agent turn")
                    payloads = result.get("result", {}).get("payloads", result.get("payloads", []))
                    answer = "\n".join(part.get("text", "") for part in payloads if isinstance(part, dict))
                    if not answer:
                        answer = result.get("text", "")
                else:
                    answer = result.get("text", "")
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError(f"{self.kind} returned no answer")
            return answer.strip()[:self.profile.get("max_answer_chars", 50000)]
