"""Condense committed replies into bounded, source-linked Markdown experience notes."""

import re


class ExperienceSummarizer:
    """Produce a deterministic extract while preserving raw text in JSONL."""

    def __init__(self, settings: dict) -> None:
        self.settings = settings

    def summarize(self, text: str) -> str:
        """Select useful answer lines within the configured prompt budget."""
        lines = []
        for raw in text.splitlines():
            line = re.sub(r"^(?:#{1,6}\s+|[-*]\s+)", "", raw.strip()).strip()
            if line and line not in lines:
                lines.append(line)
            if len(lines) >= self.settings["max_experience_lines"]:
                break
        result = "；".join(lines)
        return result[:self.settings["max_experience_entry_chars"]] or "（无可提取内容）"
