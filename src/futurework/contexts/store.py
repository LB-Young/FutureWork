"""Mirror committed messages into scoped JSONL and maintain editable Markdown memory."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import tomllib
from pathlib import Path

from futurework.contexts.summarizer import ExperienceSummarizer
from futurework.contexts.types import ScopeKey


class MemoryStore:
    """Keep raw source logs separate from per-scope experience and profile files."""

    def __init__(self, home: Path, settings: dict | None = None, assistant_name: str = "小未") -> None:
        self.home = home
        self.settings = settings or {}
        self.assistant_name = assistant_name
        self.summarizer = ExperienceSummarizer(self.settings)
        self.lock = threading.RLock()
        self.seen_ids: set[str] = set()
        self.cursor = 0
        self.last_user: dict[str, str] = {}
        for path in (home / "memory").rglob("messages.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    self.seen_ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

    def directory(self, scope: ScopeKey) -> Path:
        """Resolve one validated scope below the user memory directory."""
        if scope.kind == "assistant":
            return self.home / "memory" / "assistant"
        category = "agents" if scope.kind == "agent" else "teams"
        return self.home / "memory" / category / scope.id

    def profile_path(self, scope: ScopeKey) -> Path:
        """Keep long-term identity beside the matching TOML definition."""
        category = "teams" if scope.kind == "group" else "agents"
        return self.home / category / f"{scope.id}.md"

    def ensure_profiles(self) -> None:
        """Create missing identity Markdown without replacing user edits."""
        for category, kind in (("agents", "agent"), ("teams", "group")):
            for path in sorted((self.home / category).glob("*.toml")):
                scope = ScopeKey("assistant" if path.stem == "assistant" else kind, path.stem)
                self.ensure_profile(scope)

    def ensure_profile(self, scope: ScopeKey) -> None:
        """Initialize a profile from TOML only when its Markdown is absent."""
        target = self.profile_path(scope)
        if target.exists():
            self._ensure_scope_files(scope)
            return
        source = target.with_suffix(".toml")
        if not source.is_file():
            return
        with source.open("rb") as handle:
            definition = tomllib.load(handle)
        name = definition.get("name", scope.id)
        role = definition.get("role", "、".join(definition.get("members", [])))
        if scope.kind == "group":
            content = (f"# {name} · 群聊长期记忆\n\n"
                       f"- 群 ID：{scope.id}\n- 主要职责：{definition.get('purpose', role) or '待补充'}\n"
                       f"- 协作模式：{definition.get('mode', 'controlled')}\n"
                       f"- 成员：{'、'.join(definition.get('members', []))}\n\n"
                       "## 协作约定\n\n待补充。\n")
        else:
            capabilities = "、".join(definition.get("capabilities", {}))
            content = (f"# {name} · 人物长期记忆\n\n"
                       f"- 人物 ID：{scope.id}\n- 角色：{role}\n"
                       f"- 性格：{definition.get('personality', '待补充')}\n"
                       f"- 主要职责：{definition.get('responsibilities', role)}\n"
                       f"- 擅长能力：{capabilities or '待补充'}\n\n"
                       "## 稳定偏好与工作方式\n\n待补充。\n")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(content)
        except FileExistsError:
            pass
        self._ensure_scope_files(scope)

    def _ensure_scope_files(self, scope: ScopeKey) -> None:
        """Create empty source logs and editable knowledge templates once."""
        directory = self.directory(scope)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        (directory / "messages.jsonl").touch(exist_ok=True)
        target = directory / ("overview.md" if scope.kind == "group" else "experiences.md")
        if not target.exists():
            heading = "# 群聊话题与经验索引\n\n" if scope.kind == "group" else "# 对话经验与结果\n\n"
            try:
                with target.open("x", encoding="utf-8") as handle:
                    handle.write(heading)
            except FileExistsError:
                pass
        if scope.kind == "group":
            (directory / "topics").mkdir(exist_ok=True, mode=0o700)

    def sync(self, connection) -> None:
        """Replay committed SQLite rows; IDs make restart recovery idempotent."""
        with self.lock:
            rows = connection.execute("SELECT rowid, * FROM messages WHERE rowid>? ORDER BY rowid", (self.cursor,)).fetchall()
            for row in rows:
                message = dict(row)
                scope = self._scope(message["conversation_id"], connection)
                self.ensure_profile(scope)
                key = f"{scope.kind}:{scope.id}"
                if message["sender_kind"] == "user":
                    self.last_user[key] = message["text"]
                if message["id"] not in self.seen_ids:
                    self._append_jsonl(self.directory(scope) / "messages.jsonl", {
                        "schema_version": 1, "type": "message", "scope": key,
                        "id": message["id"], "created_at": message["created_at"],
                        "sender_kind": message["sender_kind"], "speaker": message["speaker"],
                        "text": message["text"], "client_message_id": message["client_message_id"],
                        "approval_id": message["approval_id"], "task_id": message["task_id"],
                    })
                    self.seen_ids.add(message["id"])
                if message["sender_kind"] == "agent":
                    self._record_experience(scope, message, self.last_user.get(key, ""), connection)
                self.cursor = row["rowid"]

    def _scope(self, conversation_id: str, connection) -> ScopeKey:
        if conversation_id == "assistant":
            return ScopeKey("assistant", "assistant")
        if connection.execute("SELECT 1 FROM groups WHERE id=?", (conversation_id,)).fetchone():
            return ScopeKey("group", conversation_id)
        if connection.execute("SELECT 1 FROM agents WHERE id=?", (conversation_id,)).fetchone():
            return ScopeKey("agent", conversation_id)
        raise ValueError(f"message has unknown conversation scope: {conversation_id}")

    def _record_experience(self, scope: ScopeKey, message: dict, user_text: str, connection) -> None:
        if not user_text:
            return
        marker = f"<!-- source: {message['id']} -->"
        excerpt = self.summarizer.summarize(message["text"])
        request = user_text.strip().replace("\n", " ")[:self.settings["max_topic_chars"]]
        if scope.kind == "group":
            topic = request or "群聊协作"
            slug = self._topic_slug(topic)
            topic_dir = self.directory(scope) / "topics" / slug
            speaker = message["speaker"]
            row = connection.execute("SELECT id FROM agents WHERE name=?", (speaker,)).fetchone()
            person_id = "assistant" if speaker == self.assistant_name else row["id"] if row else self._topic_slug(speaker)
            path = topic_dir / f"{person_id}.md"
            self._append_once(path, f"# {topic} · {speaker} 的经验\n\n", marker,
                              f"## {message['created_at']}\n\n- 问题：{request}\n- 参与者：{speaker}\n- 处理结果：\n\n{excerpt}\n\n{marker}\n\n")
            overview = self.directory(scope) / "overview.md"
            index_marker = f"<!-- topic: {slug} -->"
            self._append_once(overview, "# 群聊话题与经验索引\n\n", index_marker,
                              f"- [{topic}](topics/{slug}/index.md) · 按参与者查看经验 {index_marker}\n")
            topic_index = topic_dir / "index.md"
            self._append_once(topic_index, f"# {topic}\n\n", marker,
                              f"- [{speaker} 的经验]({person_id}.md) {marker}\n")
        else:
            path = self.directory(scope) / "experiences.md"
            self._append_once(path, "# 对话经验与结果\n\n", marker,
                              f"## {message['created_at']} · {message['speaker']}\n\n"
                              f"- 问题：{request}\n- 处理结果：\n\n{excerpt}\n\n{marker}\n\n")

    def _topic_slug(self, topic: str) -> str:
        base = re.sub(r"[^\w-]+", "-", topic, flags=re.UNICODE).strip("_-")[:self.settings["max_topic_slug_chars"]]
        return f"{base or 'topic'}-{hashlib.sha256(topic.encode()).hexdigest()[:8]}"

    @staticmethod
    def _append_jsonl(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def _append_once(path: Path, heading: str, marker: str, entry: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if marker in existing:
            return
        with path.open("a", encoding="utf-8") as handle:
            if not existing:
                handle.write(heading)
            handle.write(entry)

    def prompt_context(self, scope: ScopeKey, actor_id: str) -> str:
        """Load only the selected scope's experiences plus allowed identity files."""
        sections = []
        if actor_id == "assistant":
            for category in ("agents", "teams"):
                for profile in sorted((self.home / category).glob("*.md")):
                    if not profile.with_suffix(".toml").is_file():
                        continue
                    sections.append(f"【{category}/{profile.name}】\n{profile.read_text(encoding='utf-8')}")
        else:
            profile = self.home / "agents" / f"{actor_id}.md"
            if profile.is_file():
                sections.append(f"【{profile.name}】\n{profile.read_text(encoding='utf-8')}")
        if scope.kind == "group":
            directory = self.directory(scope)
            profile = self.profile_path(scope)
            if actor_id != "assistant" and profile.is_file():
                sections.append(f"【{profile.name}】\n{profile.read_text(encoding='utf-8')}")
            paths = [directory / "overview.md"]
            topic_files = sorted((directory / "topics").glob("*/*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
            paths.extend(topic_files[:self.settings["max_group_topic_files"]])
        else:
            paths = [self.directory(scope) / "experiences.md"]
        remaining = self.settings["max_prompt_memory_chars"]
        for path in paths:
            if path.is_file():
                content = path.read_text(encoding="utf-8")[:remaining]
                sections.append(f"【{path.relative_to(self.home)}】\n{content}")
                remaining -= len(content)
                if remaining <= 0:
                    break
        return "\n\n".join(sections)
