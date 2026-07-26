"""Context manager — Agent's working register (LLM context window).

Manages the hot memory that is fed into the LLM on each inference.
Three layers:
  Register:   Current inference context (< 4K tokens, reconstructed per call)
  Cache:      Ring 1 (working memory, hot reload)
  Storage:    Ring 2+3 (backing store, cold)

Flow:
  inference_start() → build register from cache/storage → LLM call → inference_end() → write back to cache
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l3.memory import get_memory
from l1.kernel.params.system import CONTEXT_MAX_REGISTER_TOKENS as MAX_REGISTER_TOKENS

logger = logging.getLogger(__name__)


_ROLE_TOOL = "tool"
_ROLE_ASSISTANT = "assistant"


@dataclass
class RegisterEntry:
    role: str        # system | user | assistant | tool | memory
    content: str
    tokens: int = 0
    source: str = ""  # memory entry ID or tool name
    timestamp: float = field(default_factory=time.time)


class ContextManager:
    """Manages the LLM context window (register).

    On each inference:
      1. Load recent working memory into register
      2. Agent runs inference
      3. Save new observations back to memory
    """

    def __init__(self, max_tokens: int = MAX_REGISTER_TOKENS):
        self.max_tokens = max_tokens
        self._register: list[RegisterEntry] = []
        self._token_count = 0
        self._lock = threading.Lock()
        self._mem = get_memory()
        self._agent_id: str = ""
        self._current_task: str = ""

    def begin(self, agent_id: str, task: str = "") -> dict:
        """Start an inference cycle: load context into register."""
        self._agent_id = agent_id
        self._current_task = task
        with self._lock:
            self._register.clear()
            self._token_count = 0

        # Load context from memory
        context = self._mem.build_context(agent_id, max_tokens=self.max_tokens)
        if context:
            self._push("memory", context, source="memory:working")
            logger.info("context loaded: %d tokens for %s", self._token_count, agent_id)

        return {"success": True, "tokens": self._token_count, "agent_id": agent_id}

    def push(self, role: str, content: str, source: str = "") -> dict:
        """Add an entry to the register (budget-checked)."""
        entry = RegisterEntry(role=role, content=content, source=source)
        with self._lock:
            # Estimate tokens
            entry.tokens = max(1, len(content) // 4)
            if self._token_count + entry.tokens > self.max_tokens:
                # Evict oldest memory entries first
                self._evict(entry.tokens)
            self._register.append(entry)
            self._token_count += entry.tokens
        return {"success": True, "tokens": self._token_count}

    def end(self, success: bool = True, summary: str = "") -> dict:
        """End an inference cycle: save register summary to memory."""
        mem = self._mem
        # Summarize what happened
        tool_calls = [e for e in self._register if e.role == _ROLE_TOOL]
        decisions = [e for e in self._register if e.role == _ROLE_ASSISTANT]

        # Store tool calls in Ring 1
        for tc in tool_calls[-10:]:
            mem.remember(
                agent_id=self._agent_id, entry_type="tool_call",
                content=tc.content[:500], tags=["tool_call"],
                source=tc.source, ring=1,
            )

        # Store decisions in Ring 2
        for d in decisions[-3:]:
            mem.remember(
                agent_id=self._agent_id, entry_type="decision",
                content=d.content[:500], tags=["decision", self._current_task],
                source=d.source, importance=0.7, ring=2,
            )

        # Store summary in Ring 3
        if summary:
            mem.remember(
                agent_id=self._agent_id, entry_type="summary",
                content=summary[:1000], tags=["summary", self._current_task],
                importance=0.9, ring=3,
            )

        with self._lock:
            count = len(self._register)
            tokens = self._token_count
            self._register.clear()
            self._token_count = 0

        logger.info("context saved: %d entries, %d tokens → memory", count, tokens)
        return {"success": True, "entries": count, "tokens": tokens, "saved": success}

    def snapshot(self) -> dict:
        """Current register contents (for UI display)."""
        with self._lock:
            entries = [{"role": e.role, "content": e.content[:100],
                        "tokens": e.tokens, "source": e.source}
                       for e in self._register]
            return {
                "agent_id": self._agent_id,
                "task": self._current_task,
                "tokens": self._token_count,
                "budget": self.max_tokens,
                "usage_pct": round(self._token_count / self.max_tokens * 100, 1),
                "entries": entries,
            }

    def _push(self, role: str, content: str, source: str = "") -> None:
        entry = RegisterEntry(role=role, content=content, source=source)
        entry.tokens = max(1, len(content) // 4)
        self._register.append(entry)
        self._token_count += entry.tokens

    def _evict(self, needed: int) -> None:
        """Evict oldest memory entries to make room."""
        while self._token_count + needed > self.max_tokens and self._register:
            for i, e in enumerate(self._register):
                if e.role != "tool":
                    self._token_count -= e.tokens
                    self._register.pop(i)
                    break
            else:
                removed = self._register.pop(0)
                self._token_count -= removed.tokens

    def token_count(self) -> int:
        """Return current register token count (for Cell merger)."""
        return self._token_count


# ── Legacy singleton (obsoleted by ContextPool) ──

_context: ContextManager | None = None


def get_context(max_tokens: int = MAX_REGISTER_TOKENS) -> ContextManager:
    global _context
    if _context is None:
        _context = ContextManager(max_tokens)
    return _context


def reset_context() -> None:
    global _context
    _context = None
