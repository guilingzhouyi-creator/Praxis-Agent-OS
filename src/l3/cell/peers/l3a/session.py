"""Session — durable session entity with history, inbox, epoch, and lifecycle.

The Session class composes five domain mixins: prompt (prompt assembly),
ask (clarification state machine), compress (history compression), persist
(archive/resume/close/state), and loop (AgentLoop wiring + memory ingestion).
SessionManager keeps the active-session registry.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from . import params as _p
from .context import ContextEpoch, ContextRegistry
from .inbox import PromptInbox
from .model import L3AModelConfig
from .session_ask import SessionAskMixin
from .session_compress import SessionCompressMixin
from .session_history import Message, Page, SessionHistory, _est_tokens  # noqa: F401 — re-export
from .session_loop import SessionLoopMixin
from .session_persist import SessionPersistMixin
from .session_prompt import SessionPromptMixin
from .task_table import SessionTaskTable

logger = logging.getLogger(__name__)


class Session(
    SessionPromptMixin,
    SessionAskMixin,
    SessionCompressMixin,
    SessionPersistMixin,
    SessionLoopMixin,
):
    """Live L3A session — history, inbox, task table, ask state, model config.

    Cross-mixin protocol methods are delegated explicitly on the concrete
    class so real implementations always win over the ``NotImplementedError``
    protocol stubs declared on the mixins (mypy sees the concrete
    delegations; the runtime never hits a stub).
    """

    # ── Cross-mixin delegation ──

    def _continue_after_ask(self, text: str) -> dict:
        """Resume the loop after clarification answers (SessionAskMixin)."""
        return SessionAskMixin._continue_after_ask(self, text)

    def _report_stats(self) -> None:
        """Emit token/pressure/turn metrics (SessionPromptMixin)."""
        SessionPromptMixin._report_stats(self)

    def _resolve_limits(self) -> dict:
        """Resolve step/time/turn limits (SessionPromptMixin)."""
        return SessionPromptMixin._resolve_limits(self)

    def _resolve_model_config(self) -> dict:
        """Resolve effective model config (SessionPromptMixin)."""
        return SessionPromptMixin._resolve_model_config(self)

    def context_stats(self) -> dict:
        """Compute session context pressure (SessionPromptMixin)."""
        return SessionPromptMixin.context_stats(self)

    def _ensure_epoch(self) -> None:
        """Create the context epoch if absent (SessionPersistMixin)."""
        return SessionPersistMixin._ensure_epoch(self)

    def _ensure_loop(self) -> None:
        """Create the AgentLoop if absent (SessionLoopMixin)."""
        return SessionLoopMixin._ensure_loop(self)

    def _persist_state(self) -> None:
        """Persist session state (SessionPersistMixin)."""
        return SessionPersistMixin._persist_state(self)

    def _ingest_tool_results(self, result: dict, user_text: str) -> None:
        """Ingest tool results into memory (SessionLoopMixin)."""
        return SessionLoopMixin._ingest_tool_results(self, result, user_text)

    def _ingest_reasoning(self, result: dict, user_text: str) -> None:
        """Ingest reasoning into memory (SessionLoopMixin)."""
        return SessionLoopMixin._ingest_reasoning(self, result, user_text)

    def __init__(
        self,
        session_id: str,
        title: str,
        model_config: L3AModelConfig | None = None,
        registry: ContextRegistry | None = None,
        user_id: str = "",
    ):
        self.id = session_id
        self.title = title
        self.user_id = user_id
        self.created_at = time.time()
        self.last_active_at = time.time()
        self.closed_at: float | None = None
        self.turn_count = 0
        self.card_count = 0
        self.status = "active"
        self.history = SessionHistory()
        self.model_config = model_config or L3AModelConfig()
        self.inbox = PromptInbox(session_id)
        self.epoch: ContextEpoch | None = None
        self.registry = registry
        self._lock = threading.RLock()
        self._loop: Any = None
        self._base_system: str = ""
        self._pmu: Any = None
        self._cell_id: str = "l3a"
        self.max_turns: int = 0
        self._model_spec_cache: dict | None = None
        self._subscribed_cards: set[str] = set()
        self.tasks: SessionTaskTable = SessionTaskTable(session_id)
        self._resumed_from: str = ""
        self._resume_todos: list[dict] = []
        self._ask: Any = None

    @classmethod
    def create(
        cls,
        title: str = "",
        model_config: L3AModelConfig | None = None,
        registry: ContextRegistry | None = None,
        user_id: str = "",
    ) -> Session:
        """Create a new session with a fresh epoch and reloaded inbox; return it."""
        sid = f"l3a-{uuid.uuid4().hex[: _p.SID_LENGTH]}"
        title = title or f"Session {time.strftime('%Y-%m-%d %H:%M')}"
        inst = cls(session_id=sid, title=title, model_config=model_config, registry=registry, user_id=user_id)
        inst.epoch = ContextEpoch.create(registry or ContextRegistry())
        inst.inbox.reload()
        logger.info("l3a session: created %s — %s", sid, title)
        try:
            from l3.bus.log import get_service as _ls

            _ls().info(f"Session created: {title}", service="l3a", agent_id=_p.AGENT_ID, task_id=sid)
        except Exception:
            logger.debug("l3a.session: log service unavailable at session create, skipped", exc_info=True)
        return inst

    def set_pmu(self, pmu: Any) -> None:
        """Attach the PMU instance used for session metrics."""
        self._pmu = pmu

    _ctx_window_cache: int = 0

    def messages(self, cursor: str | None = None, limit: int = _p.SESSION_PAGE_SIZE) -> Page:
        """Return a Page of session messages after the given cursor."""
        return self.history.messages_page(cursor=cursor, limit=limit)

    # ── Session TODO table (LLM task list via todowrite tool) ──

    def todos(self) -> dict:
        """Query the session's TodoTracker state (LLM task list)."""
        if not self._loop:
            return {"status": "open", "total_tasks": 0, "by_status": {}, "tasks": [], "note": "loop not created yet"}
        t = self._loop._todo
        stats = t.stats()
        tasks = []
        if hasattr(t, "_items"):
            tasks = [dict(item) for item in t._items]
        stats["tasks"] = tasks
        return stats

    def todos_update(self, content: str, status: str) -> dict:
        """Update a session TODO item (delegate to todowrite handler)."""
        if not self._loop:
            return {"success": False, "error": "loop not created yet"}
        r = self._loop._todo.update(content, status)
        if r.startswith("error"):
            return {"success": False, "error": r}
        return {"success": True, "status": r, "content": content}

    # ── Manual context compression ──

    def info(self) -> dict:
        """Return the session state as a dict for display."""
        with self._lock:
            epoch_info = {}
            if self.epoch:
                epoch_info = {
                    "epoch_id": self.epoch.id,
                    "epoch_created": self.epoch.created_at,
                    "baseline_chars": len(self.epoch.baseline),
                    "snapshot_keys": list(self.epoch.snapshot.keys()),
                    "turn_in_epoch": self.epoch.turn_count,
                }
            return {
                "session_id": self.id,
                "title": self.title,
                "status": self.status,
                "created_at": self.created_at,
                "last_active_at": self.last_active_at,
                "closed_at": self.closed_at,
                "turn_count": self.turn_count,
                "card_count": self.card_count,
                "message_count": self.history.count(),
                "inbox_pending": len(self.inbox.pending()),
                "model": self.model_config.show(),
                "epoch": epoch_info,
                "context": self.context_stats(),
                "tasks": {
                    "pending": self.tasks.pending_count(),
                    "total": len(self.tasks.all()),
                },
                "ask": self._ask.to_dict() if self._ask else None,
            }


class SessionManager:
    """Active-session registry for the L3A daemon."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def create(
        self,
        title: str = "",
        model_config: L3AModelConfig | None = None,
        registry: ContextRegistry | None = None,
        user_id: str = "",
    ) -> Session:
        """Create a session, register it as active, and return it."""
        s = Session.create(title=title, model_config=model_config, registry=registry, user_id=user_id)
        with self._lock:
            self._sessions[s.id] = s
        return s

    def get(self, session_id: str) -> Session | None:
        """Return the active session by id, or None when absent."""
        with self._lock:
            return self._sessions.get(session_id)

    def close(self, session_id: str) -> dict:
        """Close and deregister a session by id, returning the close result."""
        s = self.get(session_id)
        if not s:
            return {"success": False, "error": f"unknown session: {session_id}"}
        r = s.close()
        with self._lock:
            self._sessions.pop(session_id, None)
        return r

    def list_active(self) -> list[dict]:
        """Return info dicts for all sessions with active status."""
        with self._lock:
            return [s.info() for s in self._sessions.values() if s.status == "active"]

    def count(self) -> int:
        """Return the number of active sessions."""
        with self._lock:
            return len(self._sessions)
