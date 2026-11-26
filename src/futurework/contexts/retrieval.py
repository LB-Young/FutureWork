"""Search scoped experience Markdown before falling back to raw message JSONL."""

from __future__ import annotations

import json
import math
import re
import tomllib
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from futurework.contexts.store import MemoryStore
from futurework.contexts.types import ScopeKey
from futurework.kinds import ASSISTANT, TEAM


SOURCE_MARKER = re.compile(r"<!-- source: ([^>]+) -->")


@dataclass(frozen=True, slots=True)
class MemoryMatch:
    """A bounded result with a traceable file and optional source message ID."""

    origin: str
    scope: str
    source: str
    content: str
    score: int
    message_id: str = ""
    speaker: str = ""
    created_at: str = ""

    def as_dict(self) -> dict:
        """Render a JSON safe tool result without exposing absolute home paths."""
        return {"origin": self.origin, "scope": self.scope, "source": self.source,
                "content": self.content, "score": self.score, "message_id": self.message_id,
                "speaker": self.speaker, "created_at": self.created_at}


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    """The first successful search tier and its ranked results."""

    tier: str
    scope: ScopeKey
    matches: tuple[MemoryMatch, ...]

    def as_dict(self) -> dict:
        """Keep the fallback decision visible to the calling Agent."""
        return {"tier": self.tier, "scope": f"{self.scope.kind}:{self.scope.id}",
                "matches": [match.as_dict() for match in self.matches]}


class MemoryRetriever:
    """Enforce scope and search specific experience before broader files or JSONL."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.settings = store.settings

    def search(self, query: str, scope: ScopeKey, actor_id: str, *,
               group_id: str | None = None, limit: int = 5) -> MemorySearchResult:
        """Search only the caller's scope or an explicitly named group for XiaoWei."""
        if not isinstance(query, str) or not query.strip() or len(query) > self.settings["search_max_query_chars"]:
            raise ValueError("invalid memory search query")
        if type(limit) is not int or limit < 1:
            raise ValueError("invalid memory search limit")
        limit = min(limit, self.settings["search_max_results"])
        if group_id:
            selected = ScopeKey("group", group_id)
            own_group = scope.kind == TEAM and scope.id == group_id
            assistant_group = (scope.kind == ASSISTANT and actor_id == ASSISTANT
                               and self.store.profile_path(selected).with_suffix(".toml").is_file())
            if not (own_group or assistant_group):
                raise PermissionError("group memory is outside the current scope")
            scope = selected
        root = self.store.directory(scope)
        if scope.kind == TEAM:
            targeted = sorted((root / "topics").glob(f"*/{actor_id}.md"))
            hits = self._search_md(query, scope, targeted, limit)
            if hits:
                return MemorySearchResult("member_experience", scope, tuple(hits))
            broad = [root / "overview.md"]
            broad.extend(path for path in sorted((root / "topics").glob("*/*.md"))
                         if path.name != "index.md" and path not in targeted)
            hits = self._search_md(query, scope, broad, limit)
            if hits:
                # An overview entry is a pointer; return the linked participant notes too.
                expanded = list(hits)
                for hit in hits:
                    if not hit.source.endswith("overview.md"):
                        continue
                    for slug in re.findall(r"topics/([A-Za-z0-9_\u4e00-\u9fff-]+)/index\.md", hit.content):
                        topic_dir = root / "topics" / slug
                        for path in sorted(topic_dir.glob("*.md")):
                            if path.name == "index.md" or not path.resolve().is_relative_to(root.resolve()):
                                continue
                            content = path.read_text(encoding="utf-8")[:self.settings["search_max_result_chars"]]
                            expanded.append(MemoryMatch("experience", f"group:{scope.id}",
                                                        str(path.relative_to(self.store.home)), content, hit.score))
                            if len(expanded) >= limit:
                                break
                        if len(expanded) >= limit:
                            break
                hits = expanded[:limit]
                return MemorySearchResult("group_experience", scope, tuple(hits))
            speaker = self._speaker(actor_id)
            own = self._search_jsonl(query, scope, limit, speaker=speaker) if speaker else []
            if own:
                return MemorySearchResult("member_jsonl", scope, tuple(own))
        else:
            hits = self._search_md(query, scope, [root / "experiences.md"], limit)
            if hits:
                return MemorySearchResult("own_experience", scope, tuple(hits))
        raw = self._search_jsonl(query, scope, limit)
        return MemorySearchResult("jsonl" if raw else "none", scope, tuple(raw))

    def _search_md(self, query: str, scope: ScopeKey, paths: list[Path], limit: int) -> list[MemoryMatch]:
        root = self.store.directory(scope)
        matches = []
        for path in paths[:self.settings["search_max_files"]]:
            if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
                continue
            content = path.read_text(encoding="utf-8")[-self.settings["search_max_file_chars"]:]
            for entry, message_id in self._entries(content):
                score = self._score(query, entry)
                if score < self.settings["search_min_score"]:
                    continue
                matches.append(MemoryMatch(
                    origin="experience", scope=f"{scope.kind}:{scope.id}",
                    source=str(path.relative_to(self.store.home)),
                    content=entry.strip()[:self.settings["search_max_result_chars"]],
                    score=score, message_id=message_id))
        return sorted(matches, key=lambda item: (-item.score, item.source, item.message_id))[:limit]

    @staticmethod
    def _entries(content: str) -> list[tuple[str, str]]:
        matches = list(SOURCE_MARKER.finditer(content))
        if not matches:
            return [(line, "") for line in content.splitlines() if line.strip()]
        entries = []
        start = 0
        for match in matches:
            entries.append((content[start:match.start()], match.group(1).strip()))
            start = match.end()
        tail = content[start:].strip()
        if tail:
            entries.extend((line, "") for line in tail.splitlines() if line.strip())
        return entries

    def _search_jsonl(self, query: str, scope: ScopeKey, limit: int, speaker: str = "") -> list[MemoryMatch]:
        path = self.store.directory(scope) / "messages.jsonl"
        if not path.is_file() or not path.resolve().is_relative_to(self.store.directory(scope).resolve()):
            return []
        with path.open(encoding="utf-8") as handle:
            lines = deque(handle, maxlen=self.settings["search_max_log_lines"])
        matches = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict) or item.get("scope") != f"{scope.kind}:{scope.id}":
                continue
            if speaker and item.get("speaker") != speaker:
                continue
            text = item.get("text", "")
            if not isinstance(text, str):
                continue
            score = self._score(query, text)
            if score < self.settings["search_min_score"]:
                continue
            matches.append(MemoryMatch(
                origin="jsonl", scope=f"{scope.kind}:{scope.id}",
                source=str(path.relative_to(self.store.home)),
                content=text[:self.settings["search_max_result_chars"]], score=score,
                message_id=str(item.get("id", "")), speaker=str(item.get("speaker", "")),
                created_at=str(item.get("created_at", ""))))
        return sorted(matches, key=lambda item: (item.score, item.created_at), reverse=True)[:limit]

    def _speaker(self, actor_id: str) -> str:
        if actor_id == "assistant":
            return self.store.assistant_name
        path = self.store.profile_path(ScopeKey("agent", actor_id)).with_suffix(".toml")
        if not path.is_file():
            return ""
        with path.open("rb") as handle:
            return str(tomllib.load(handle).get("name", ""))

    @staticmethod
    def _score(query: str, content: str) -> int:
        query = query.casefold().strip()
        text = content.casefold()
        if query in text:
            return 10 + text.count(query)
        terms = set(re.findall(r"[a-z0-9_]+", query))
        for block in re.findall(r"[\u4e00-\u9fff]+", query):
            terms.update(block[index:index + 2] for index in range(len(block) - 1))
        matched = {term for term in terms if term and term in text}
        if not terms or len(matched) < math.ceil(len(terms) * 0.6):
            return 0
        return 2 * sum(text.count(term) for term in matched)
