"""DialogueSession — multi-turn dialogue state machine for Agent OS, auto-persisted.

Each session tracks:
  - State machine: IDLE → ACTIVE → WAITING → COMPLETED / FAILED
  - Turn history (messages + tool calls per turn)
  - Context persistence across turns (via MemoryService + JSON file)
  - Token budget tracking per turn

Usage:
  session = DialogueSession(agent_id="agent-a", task="Fix bug in login")
  session.start()
  # ... LLM inference round 1 ...
  session.record_turn(prompt, response, tool_calls)
  session.push_context("scout_result", "...")
  # ... LLM inference round 2 ...
  session.record_turn(prompt, result, [])
  session.complete()
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto

from l1.kernel.params.system import (
    DIALOGUE_IDLE_TIMEOUT,
    DIALOGUE_MAX_CONTEXT_TOKENS,
    DIALOGUE_MAX_TURNS,
    DIALOGUE_PERSIST_EVERY,
    DIALOGUE_SESSION_AUTO_SAVE,
    HASH_TRUNC_SHORT,
    LOG_TRUNC_60,
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    LOG_TRUNC_500,
    LOG_TRUNC_1000,
)
from l1.kernel.paths import get_paths as _gp

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """SessionState — enum of IDLE, ACTIVE, WAITING, COMPLETED...."""
    IDLE = auto()        # Created, not started
    ACTIVE = auto()      # In multi-turn dialogue
    WAITING = auto()     # Awaiting external tool result
    COMPLETED = auto()   # Task finished successfully
    FAILED = auto()      # Task failed or aborted


@dataclass
class TurnRecord:
    """A single turn in the dialogue session."""
    turn: int
    prompt: str = ""
    response: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    context_snapshot: list[dict] = field(default_factory=list)
    elapsed: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionConfig:
    """SessionConfig — session config record (max_turns, max_context_tokens, idle_timeout, persist_after)."""
    max_turns: int = DIALOGUE_MAX_TURNS
    max_context_tokens: int = DIALOGUE_MAX_CONTEXT_TOKENS
    idle_timeout: float = DIALOGUE_IDLE_TIMEOUT  # 5 min
    persist_after: int = DIALOGUE_PERSIST_EVERY  # persist to memory every N turns


class DialogueSession:
    """Multi-turn dialogue session with state machine and dual persistence."""

    def __init__(self, agent_id: str, task: str = "",
                 config: SessionConfig | None = None,
                 persist_path: str = ""):
        self.session_id = f"session-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        self.agent_id = agent_id
        self.task = task
        self.config = config or SessionConfig()
        self.state = SessionState.IDLE
        self._turns: list[TurnRecord] = []
        self._context_entries: list[dict] = []
        self._token_budget: int = self.config.max_context_tokens
        self._lock = threading.Lock()
        self._created_at = time.time()
        self._last_activity = time.time()
        self._persist_path = persist_path or _gp().dialogue_session
        self._auto_save_interval = DIALOGUE_SESSION_AUTO_SAVE

    # ── Lifecycle ──

    def start(self) -> dict:
        """Begin the session."""
        with self._lock:
            if self.state not in (SessionState.IDLE, SessionState.COMPLETED):
                return {"success": False, "error": f"session in state {self.state.name}"}
            self.state = SessionState.ACTIVE
            self._turns = []
            self._context_entries = []
            self._last_activity = time.time()
        logger.info("session %s started: agent=%s task=%s",
                    self.session_id, self.agent_id, self.task[:LOG_TRUNC_60])
        return {"success": True, "session_id": self.session_id}

    def complete(self, summary: str = "") -> dict:
        """End the session successfully."""
        with self._lock:
            self.state = SessionState.COMPLETED
            self._last_activity = time.time()
        self._persist(summary)
        logger.info("session %s completed: %d turns", self.session_id, len(self._turns))
        return {"success": True, "turns": len(self._turns)}

    def fail(self, error: str = "") -> dict:
        """Mark the session as failed."""
        with self._lock:
            self.state = SessionState.FAILED
        logger.warning("session %s failed: %s", self.session_id, error[:LOG_TRUNC_100])
        return {"success": False, "error": error, "turns": len(self._turns)}

    # ── Turn management ──

    def record_turn(self, prompt: str = "", response: str = "",
                    tool_calls: list[dict] | None = None) -> TurnRecord:
        """Record one inference turn and return the snapshot."""
        with self._lock:
            turn_num = len(self._turns) + 1
            record = TurnRecord(
                turn=turn_num,
                prompt=prompt[:LOG_TRUNC_500],
                response=response[:LOG_TRUNC_1000],
                tool_calls=[{"name": tc.get("name", ""),
                             "args": str(tc.get("args", {}))[:LOG_TRUNC_200]}
                            for tc in (tool_calls or [])],
                context_snapshot=list(self._context_entries[-10:]),
                timestamp=time.time(),
            )
            self._turns.append(record)
            self._last_activity = time.time()
            self.state = SessionState.WAITING if tool_calls else SessionState.ACTIVE

        # Auto-persist every N turns
        if turn_num % self.config.persist_after == 0:
            self._persist()
        return record

    def push_context(self, role: str, content: str,
                     source: str = "") -> dict:
        """Inject context for the next inference turn."""
        entry = {"role": role, "content": content[:LOG_TRUNC_500],
                 "source": source, "ts": time.time()}
        with self._lock:
            est_tokens = max(1, len(content) // 4)
            if self._token_budget - est_tokens < 0:
                # Evict oldest non-tool entries
                before = len(self._context_entries)
                self._context_entries = [e for e in self._context_entries
                                         if e["role"] == "tool"][-5:]
                evicted = before - len(self._context_entries)
                self._token_budget = self.config.max_context_tokens - sum(
                    max(1, len(e["content"]) // 4) for e in self._context_entries
                )
                logger.debug("session %s evicted %d context entries", self.session_id, evicted)
            self._context_entries.append(entry)
            self._token_budget -= est_tokens
        return {"success": True, "tokens_used": self.config.max_context_tokens - self._token_budget}

    def build_context(self) -> str:
        """Assemble all context entries into a string for the next LLM call."""
        with self._lock:
            parts = []
            for entry in self._context_entries:
                parts.append(f"[{entry['role']}]\n{entry['content']}")
            if parts:
                return "\n\n".join(parts)
            return ""

    def turn_summary(self) -> list[dict]:
        """Return summary of all turns (for UI / reporting)."""
        with self._lock:
            return [{
                "turn": t.turn,
                "tool_calls": len(t.tool_calls),
                "elapsed": round(t.elapsed, 2),
                "ts": t.timestamp,
                "prompt_preview": t.prompt[:LOG_TRUNC_60],
                "response_preview": t.response[:LOG_TRUNC_60],
            } for t in self._turns]

    def stats(self) -> dict:
        """Return a stats summary of the session."""
        with self._lock:
            return {
                "session_id": self.session_id,
                "agent_id": self.agent_id,
                "state": self.state.name,
                "turns": len(self._turns),
                "context_entries": len(self._context_entries),
                "token_budget_used": self.config.max_context_tokens - self._token_budget,
                "token_budget_max": self.config.max_context_tokens,
                "elapsed": round(time.time() - self._created_at, 1),
                "task": self.task[:LOG_TRUNC_60],
            }

    # ── Persistence ──

    def _json_persist(self) -> dict:
        """Save full session state to JSON file."""
        data = {
            "session_id": self.session_id, "agent_id": self.agent_id,
            "task": self.task, "state": self.state.name,
            "turns": [{
                "turn": t.turn, "prompt": t.prompt, "response": t.response,
                "tool_calls": t.tool_calls,
                "context_snapshot": t.context_snapshot,
                "elapsed": t.elapsed, "timestamp": t.timestamp,
            } for t in self._turns],
            "context_entries": list(self._context_entries),
            "token_budget": self._token_budget,
            "created_at": self._created_at,
            "last_activity": self._last_activity,
            "_version": 1,
        }
        path = self._persist_path.replace(".json", f"_{self.session_id}.json")
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, path)
            return {"success": True}
        except Exception as e:
            logger.warning("session json persist failed: %s", e)
            return {"success": False, "error": str(e)}

    @staticmethod
    def restore_from_json(agent_id: str, session_id: str,
                          persist_path: str = "") -> DialogueSession | None:
        """Restore a session from its JSON file."""
        base = persist_path or _gp().dialogue_session
        path = base.replace(".json", f"_{session_id}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        if data.get("_version", 0) < 1:
            return None
        config = SessionConfig()
        session = DialogueSession.__new__(DialogueSession)
        session.session_id = data["session_id"]
        session.agent_id = data["agent_id"]
        session.task = data.get("task", "")
        session.config = config
        session.state = SessionState[data["state"]]
        session._turns = []
        session._context_entries = data.get("context_entries", [])
        session._token_budget = data.get("token_budget", config.max_context_tokens)
        session._lock = threading.Lock()
        session._created_at = data.get("created_at", 0.0)
        session._last_activity = data.get("last_activity", 0.0)
        session._persist_path = persist_path or _gp().dialogue_session
        session._auto_save_interval = DIALOGUE_SESSION_AUTO_SAVE
        for td in data.get("turns", []):
            session._turns.append(TurnRecord(
                turn=td["turn"], prompt=td.get("prompt", ""),
                response=td.get("response", ""),
                tool_calls=td.get("tool_calls", []),
                context_snapshot=td.get("context_snapshot", []),
                elapsed=td.get("elapsed", 0.0),
                timestamp=td.get("timestamp", 0.0),
            ))
        return session

    def _persist(self, summary: str = "") -> None:
        """Save session state to memory for recovery across restarts."""
        try:
            from .memory.memory import get_memory
            mem = get_memory()
            data = {
                "session_id": self.session_id,
                "agent_id": self.agent_id,
                "task": self.task,
                "state": self.state.name,
                "turns": [{
                    "turn": t.turn, "prompt": t.prompt, "response": t.response,
                    "tool_calls": t.tool_calls, "elapsed": t.elapsed,
                } for t in self._turns[-self.config.persist_after:]],
                "summary": summary[:LOG_TRUNC_500],
            }
            mem.remember(
                agent_id=self.agent_id,
                entry_type="session",
                content=json.dumps(data, default=str),
                tags=["session", self.session_id],
                ring=2,  # Short-term memory
            )
        except Exception as e:
            logger.warning("session persist failed: %s", e)


# ── Session registry ──

_sessions: dict[str, DialogueSession] = {}
_sessions_lock = threading.Lock()


def create_session(agent_id: str, task: str = "",
                   config: SessionConfig | None = None) -> DialogueSession:
    """Create and register a new dialogue session."""
    session = DialogueSession(agent_id, task, config)
    with _sessions_lock:
        _sessions[session.session_id] = session
    return session


def get_session(session_id: str) -> DialogueSession | None:
    """Return the session with the given ID, or None if not found."""
    with _sessions_lock:
        return _sessions.get(session_id)


def list_sessions(agent_id: str = "") -> list[dict]:
    """Return stats for all sessions, optionally filtered by agent."""
    with _sessions_lock:
        return [s.stats() for s in _sessions.values()
                if not agent_id or s.agent_id == agent_id]


def close_session(session_id: str) -> None:
    """Close and remove the session with the given ID."""
    with _sessions_lock:
        _sessions.pop(session_id, None)
