"""Persist and run user-owned scheduled assistant requests while the service runs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from futurework.abilities.tools.management import atomic_text


class ScheduleStore:
    """Manage one-shot or interval jobs as separate atomic JSON documents."""

    def __init__(self, home: Path, settings: dict) -> None:
        self.directory = home / "data" / "schedules"
        self.settings = settings

    def create(self, prompt: str, run_at: str, interval_seconds: int | None = None) -> dict:
        """Persist a bounded task and its next UTC execution time."""
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > self.settings["max_prompt_chars"]:
            raise ValueError("invalid scheduled prompt")
        when = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
        if when.tzinfo is None or when <= datetime.now(timezone.utc):
            raise ValueError("run_at must be a future timezone-aware ISO timestamp")
        if interval_seconds is not None and (type(interval_seconds) is not int or
                                             interval_seconds < self.settings["min_interval_seconds"]):
            raise ValueError("interval is below the configured minimum")
        job = {"id": str(uuid4()), "prompt": prompt.strip(), "run_at": when.astimezone(timezone.utc).isoformat(),
               "interval_seconds": interval_seconds, "status": "active", "last_run_at": None,
               "last_error": None}
        atomic_text(self.directory / f"{job['id']}.json", json.dumps(job, ensure_ascii=False, indent=2))
        return job

    def list(self) -> list[dict]:
        """List persisted jobs in chronological order."""
        jobs = [json.loads(path.read_text(encoding="utf-8")) for path in self.directory.glob("*.json")]
        return sorted(jobs, key=lambda item: item["run_at"])

    async def run_due(self, callback) -> int:
        """Claim due jobs before invoking the assistant request callback."""
        now = datetime.now(timezone.utc)
        count = 0
        for job in self.list():
            if job["status"] != "active" or datetime.fromisoformat(job["run_at"]) > now:
                continue
            count += 1
            next_at = job["run_at"]
            interval = job["interval_seconds"]
            if interval:
                while datetime.fromisoformat(next_at) <= now:
                    next_at = (datetime.fromisoformat(next_at) + timedelta(seconds=interval)).isoformat()
                job["run_at"] = next_at
            else:
                job["status"] = "completed"
            job["last_run_at"] = now.isoformat()
            atomic_text(self.directory / f"{job['id']}.json", json.dumps(job, ensure_ascii=False, indent=2))
            try:
                await callback(job)
            except Exception as error:
                job["last_error"] = type(error).__name__
                atomic_text(self.directory / f"{job['id']}.json", json.dumps(job, ensure_ascii=False, indent=2))
        return count
