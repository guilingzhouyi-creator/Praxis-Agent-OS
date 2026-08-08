"""Session history model — page / message / history — extracted from session.py.

The pure data model behind the L3A ``Session``: ``Page`` (paged listing),
``Message`` (one exchange record) and ``SessionHistory`` (ordered, token-bounded
projection). ``Session`` (in session.py) owns one of these.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import SESSION_MSG_OVERHEAD, TOKEN_CHARS_PER_TOKEN

from . import params as _p

# module-level re-export for session.py compatibility
__all__ = ["Page", "Message", "SessionHistory", "_est_tokens"]


@dataclass
class Page:
    """Page — page record (items, cursor, total)."""

    items: list[dict]
    cursor: str | None = None
    total: int = 0


@dataclass
class Message:
    """Message — message record (id, role, content, tool_calls, reasoning_content)."""

    id: str
    role: str
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    reasoning_content: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class SessionHistory:
    """Ordered session message history with token projection."""

    def __init__(self):
        self._messages: list[Message] = []
        self._lock = threading.RLock()

    def append(self, msg: Message) -> None:
        """Append one message to the history."""
        with self._lock:
            self._messages.append(msg)

    def extend(self, msgs: list[Message]) -> None:
        """Append a list of messages to the history."""
        with self._lock:
            self._messages.extend(msgs)

    def project(
        self, max_tokens: int = _p.SESSION_HISTORY_MAX_TOKENS, keep_last: int = _p.SESSION_HISTORY_TRUNC
    ) -> list[dict]:
        """Project recent messages into a token-bounded list of dicts, newest-first."""
        with self._lock:
            msgs = self._messages[-keep_last:]
        tokens = 0
        projected: list[dict[str, Any]] = []
        for m in reversed(msgs):
            est = len(m.content) // TOKEN_CHARS_PER_TOKEN + SESSION_MSG_OVERHEAD
            if tokens + est > max_tokens and projected:
                break
            tokens += est
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            if m.reasoning_content:
                entry["reasoning_content"] = m.reasoning_content
            projected.append(entry)
        projected.reverse()
        return projected

    def to_context_trail(self) -> list[dict]:
        """Return a double-budget context trail of the history for archiving."""
        return self.project(max_tokens=_p.SESSION_HISTORY_MAX_TOKENS * 2)

    def count(self) -> int:
        """Return the total number of stored messages."""
        with self._lock:
            return len(self._messages)

    def messages_page(self, cursor: str | None = None, limit: int = _p.SESSION_PAGE_SIZE) -> Page:
        """Return a Page of messages starting after cursor with at most limit items."""
        with self._lock:
            msgs = list(self._messages)
        start = 0
        if cursor:
            for i, m in enumerate(msgs):
                if m.id == cursor:
                    start = i + 1
                    break
        chunk = msgs[start : start + limit]
        items = [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "tool_calls": m.tool_calls,
                "created_at": m.created_at,
                "reasoning_content": m.reasoning_content,
            }
            for m in chunk
        ]
        next_cursor = chunk[-1].id if len(chunk) == limit else None
        return Page(items=items, cursor=next_cursor, total=len(msgs))

    def clear(self) -> None:
        """Remove all stored messages."""
        with self._lock:
            self._messages.clear()


def _est_tokens(text: str) -> int:
    return len(text) // TOKEN_CHARS_PER_TOKEN
