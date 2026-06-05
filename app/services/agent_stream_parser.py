from __future__ import annotations

import json
import re
from typing import Any


class AgentStreamParser:
    def __init__(self, *, visible_tags: set[str]):
        self.visible_tags = visible_tags
        self.raw_text = ""
        self._visible_tag: str | None = None
        self._pending = ""

    def feed(self, chunk: str) -> list[str]:
        self.raw_text += chunk
        self._pending += chunk
        output: list[str] = []

        while self._pending:
            if self._visible_tag:
                close = f"</{self._visible_tag}>"
                close_index = self._pending.find(close)
                if close_index == -1:
                    possible_tag_index = self._pending.rfind("<")
                    emit_until = len(self._pending) if possible_tag_index == -1 else possible_tag_index
                    if emit_until:
                        output.append(self._pending[:emit_until])
                        self._pending = self._pending[emit_until:]
                    break
                if close_index:
                    output.append(self._pending[:close_index])
                self._pending = self._pending[close_index + len(close):]
                self._visible_tag = None
                continue

            open_match = re.search(r"<([a-z_]+)>", self._pending)
            if not open_match:
                keep = min(len(self._pending), 64)
                self._pending = self._pending[-keep:]
                break
            tag = open_match.group(1)
            self._pending = self._pending[open_match.end():]
            if tag in self.visible_tags:
                self._visible_tag = tag

        return [item for item in output if item]


class QuestionJSONStreamExtractor:
    """Extract completed <question_json> tags from an incremental LLM stream."""

    def __init__(self):
        self._buffer = ""
        self._scan_start = 0

    def feed(self, chunk: str) -> list[dict[str, Any]]:
        self._buffer += chunk
        output: list[dict[str, Any]] = []
        open_tag = "<question_json>"
        close_tag = "</question_json>"

        while True:
            open_index = self._buffer.find(open_tag, self._scan_start)
            if open_index == -1:
                self._trim_buffer(keep_from=max(0, len(self._buffer) - len(open_tag)))
                break

            content_start = open_index + len(open_tag)
            close_index = self._buffer.find(close_tag, content_start)
            if close_index == -1:
                self._trim_buffer(keep_from=open_index)
                break

            content = self._buffer[content_start:close_index].strip()
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                output.append(parsed)

            self._scan_start = close_index + len(close_tag)

        return output

    def _trim_buffer(self, *, keep_from: int) -> None:
        if keep_from <= 0:
            return
        self._buffer = self._buffer[keep_from:]
        self._scan_start = max(0, self._scan_start - keep_from)


def parse_conversation_tag_payload(text: str) -> dict[str, Any]:
    if not _has_any_tag(text, {"reply", "action", "draft_json", "question_json", "questions_json"}):
        fallback = _json_object(text)
        if isinstance(fallback, dict):
            return {
                "action": fallback.get("action") or "chat",
                "reply": fallback.get("reply") or "",
                "draft": fallback.get("draft") or {},
                "questions": fallback.get("questions") or [],
            }
        return {
            "action": "chat",
            "reply": text.strip(),
            "draft": {},
            "questions": [],
        }
    return {
        "action": _tag(text, "action") or "chat",
        "reply": _tag(text, "reply") or "",
        "draft": _json_tag(text, "draft_json", default={}),
        "questions": _question_tags(text) or _json_tag(text, "questions_json", default=[]),
    }


def parse_draft_tag_payload(text: str) -> dict[str, Any]:
    if not _has_any_tag(text, {"draft_reply", "draft_json"}):
        fallback = _json_object(text)
        if isinstance(fallback, dict):
            return {
                "reply": fallback.get("reply") or fallback.get("draft_reply") or "",
                "draft": fallback.get("draft") or {},
            }
        return {
            "reply": text.strip(),
            "draft": {},
        }
    return {
        "reply": _tag(text, "draft_reply") or "",
        "draft": _json_tag(text, "draft_json", default={}),
    }


def _tag(text: str, name: str) -> str | None:
    match = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    if not match:
        return None
    return match.group(1).strip()


def _json_tag(text: str, name: str, *, default: Any) -> Any:
    value = _tag(text, name)
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _question_tags(text: str) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for match in re.finditer(r"<question_json>(.*?)</question_json>", text, re.S):
        try:
            parsed = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            questions.append(parsed)
    return questions


def _has_any_tag(text: str, names: set[str]) -> bool:
    return any(f"<{name}>" in text for name in names)


def _json_object(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start:end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None
