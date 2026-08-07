"""SessionTaskTable — per-session card task tracking (system-managed).

Each L3A Session tracks the cards it spawns:
  track(card_id, title, turn)          → card enters table (QUEUED)
  update(card_id, status, result)      → status sync (from callback or watcher)
  list(status) / pending_count()       → queryable task buffer
  persist() / restore()                → survives session restart

Reconciliation: L3ADaemon.tick() calls sync_from_registry() to reconcile
table statuses with CardRegistry — the background watcher.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from l3.error_bus import capture  # noqa: E402


@dataclass
class SessionTask:
    """SessionTask — session task record (card_id, title, status, turn, created_at)."""

    card_id: str = ""
    title: str = ""
    status: str = "queued"
    turn: int = 0
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    result: dict | None = None

    def to_dict(self) -> dict:
        """Serialize the task record to a dict."""
        return {
            "card_id": self.card_id,
            "title": self.title,
            "status": self.status,
            "turn": self.turn,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "result": self.result,
        }


class SessionTaskTable:
    """Thread-safe per-session task buffer with status tracking."""

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._tasks: dict[str, SessionTask] = {}
        self._lock = threading.RLock()

    # ── Write ──

    def track(self, card_id: str, title: str = "", turn: int = 0) -> None:
        """Register a card in the table, creating or refreshing its entry."""
        with self._lock:
            if card_id not in self._tasks:
                self._tasks[card_id] = SessionTask(card_id=card_id, title=title, turn=turn)
            else:
                self._tasks[card_id].title = title or self._tasks[card_id].title

    def update(self, card_id: str, status: str, result: dict | None = None) -> None:
        """Update a card's status and optional result, stamping completion time."""
        with self._lock:
            t = self._tasks.get(card_id)
            if not t:
                return
            t.status = status.lower()
            if status.lower() in ("completed", "failed", "cancelled"):
                t.completed_at = time.time()
            if result:
                t.result = result

    def remove(self, card_id: str) -> None:
        """Remove a card entry from the table."""
        with self._lock:
            self._tasks.pop(card_id, None)

    # ── Read ──

    def get(self, card_id: str) -> SessionTask | None:
        """Return the task for a card id, or None when absent."""
        with self._lock:
            return self._tasks.get(card_id)

    def list_tasks(self, status: str = "") -> list[dict]:
        """Return task dicts, optionally filtered by status, oldest first."""
        with self._lock:
            tasks = list(self._tasks.values())
        if status:
            status = status.lower()
            tasks = [t for t in tasks if t.status == status]
        return [t.to_dict() for t in sorted(tasks, key=lambda t: t.created_at)]

    def pending_count(self) -> int:
        """Return the count of tasks still in a non-terminal status."""
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.status in ("queued", "dispatched", "running"))

    def all(self) -> list[SessionTask]:
        """Return all tracked task objects."""
        with self._lock:
            return list(self._tasks.values())

    def clear(self) -> None:
        """Remove all tracked tasks."""
        with self._lock:
            self._tasks.clear()

    # ── Persistence (session snapshot) ──

    def to_dict(self) -> dict:
        """Serialize the whole table as a card-id to dict map."""
        with self._lock:
            return {cid: t.to_dict() for cid, t in self._tasks.items()}

    def from_dict(self, data: dict) -> None:
        """Restore the table from a serialized card-id to dict map."""
        with self._lock:
            self._tasks.clear()
            for cid, td in (data or {}).items():
                self._tasks[cid] = SessionTask(**{k: v for k, v in td.items() if k in SessionTask.__dataclass_fields__})

    # ── Reconciliation (watcher): sync with CardRegistry ──

    def sync_from_registry(self) -> int:
        """Reconcile task statuses with CardRegistry state. Returns updated count."""
        from l3.card.card_registry import get_registry

        try:
            reg = get_registry()
        except Exception as e:
            capture(
                "task_table: registry unavailable", error_code="E_L3A_TASKS", component="l3a", context={"error": str(e)}
            )
            logger.debug("task_table: registry unavailable: %s", e)
            return 0
        updated = 0
        with self._lock:
            for card_id, task in self._tasks.items():
                try:
                    rec = reg.get(card_id)
                except Exception:
                    capture(
                        "task_table: card lookup failed",
                        error_code="E_L3A_TASKS",
                        component="l3a",
                        context={"card_id": card_id},
                    )
                    continue
                if not rec:
                    continue
                state = rec.state.value if hasattr(rec, "state") else ""
                if state and state.lower() != task.status:
                    task.status = state.lower()
                    if state.lower() in ("completed", "failed", "cancelled"):
                        task.completed_at = time.time()
                    updated += 1
        return updated
