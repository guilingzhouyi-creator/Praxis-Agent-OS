"""PendingQueue — message queue for held cards awaiting human/convention decision.

Dual-layer card queue architecture:
  CardRegistry._queue        → dispatch queue (ready to execute)
  PendingQueue               → pending queue (held for approval)

Flow:
  Card Gate (large/disputed) → enqueue → PendingQueue
  Human approves             → dequeue → CardRegistry._queue (re-added)
  Human rejects              → dequeue → card CANCELLED
  Convention escalate        → dequeue → ConventionProtocol

Exposes full CRUD API for TUI, monitoring, and external tools.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.params.agent import HUMAN_SENDER, SIGNAL_TARGET_L3
from l1.kernel.params.kernel import WitnessStatus
from l1.kernel.params.system import (
    CARD_DEFAULT_PRIORITY,
    CARD_DEFAULT_SIZE,
    HASH_TRUNC_SHORT,
    LOG_TRUNC_60,
    LOG_TRUNC_80,
    LOG_TRUNC_120,
    LOG_TRUNC_200,
    PENDING_QUEUE_AUTO_SAVE,
)
from l1.kernel.paths import get_paths as _gp
from l3._persistable import PersistableMixin

logger = logging.getLogger(__name__)


class PendingStatus(Enum):
    """PendingStatus — enum of PENDING, APPROVED, REJECTED, ESCALATED...."""
    PENDING = auto()
    APPROVED = auto()
    REJECTED = auto()
    ESCALATED = auto()
    EXPIRED = auto()


@dataclass
class PendingMessage:
    """PendingMessage — pending message record (id, card_id, intent, domain, size)."""
    id: str = ""
    card_id: str = ""
    intent: str = ""
    domain: str = ""
    size: str = ""           # large | disputed
    status: PendingStatus = PendingStatus.PENDING
    priority: int = CARD_DEFAULT_PRIORITY
    created_at: float = field(default_factory=time.time)
    resolved_at: float = 0.0
    response: str = ""
    metadata: dict = field(default_factory=dict)


class PendingQueue(PersistableMixin):
    """Persistent message queue for held cards."""

    persistence_kind = "pending_queue"

    def __init__(self, persist_path: str = ""):
        self._items: dict[str, PendingMessage] = {}
        self._lock = threading.RLock()
        self._on_approve: Any = None  # callback(card_id) → restores placeholder in CardRegistry
        self._init_persistence(persist_path or _gp().pending_queue, PENDING_QUEUE_AUTO_SAVE)
        self._restore()
        if PENDING_QUEUE_AUTO_SAVE > 0:
            self._start_auto_save()

    def set_on_approve(self, callback: Any) -> None:
        """Set callback for when a card is approved. Called with card_id."""
        self._on_approve = callback

    # ── Persistence ──

    def _serialize(self) -> dict:
        return {
            "items": {mid: {
                "id": m.id, "card_id": m.card_id,
                "intent": m.intent, "domain": m.domain,
                "size": m.size, "status": m.status.name,
                "priority": m.priority,
                "created_at": m.created_at, "resolved_at": m.resolved_at,
                "response": m.response, "metadata": m.metadata,
            } for mid, m in self._items.items()},
        }

    def _deserialize(self, data: dict) -> bool:
        self._items.clear()
        for mid, d in data.get("items", {}).items():
            self._items[mid] = PendingMessage(
                id=d["id"], card_id=d.get("card_id", ""),
                intent=d.get("intent", ""), domain=d.get("domain", ""),
                size=d.get("size", ""),
                status=PendingStatus[d["status"]],
                priority=d.get("priority", 5),
                created_at=d.get("created_at", 0.0),
                resolved_at=d.get("resolved_at", 0.0),
                response=d.get("response", ""),
                metadata=d.get("metadata", {}),
            )
        return True

    # ── Public API ──

    def enqueue(self, card_id: str, intent: str = "", domain: str = "",
                size: str = CARD_DEFAULT_SIZE, priority: int = CARD_DEFAULT_PRIORITY) -> str:
        """Add a card to the pending queue. Returns message id."""
        mid = f"pend-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        msg = PendingMessage(
            id=mid, card_id=card_id, intent=intent, domain=domain,
            size=size, priority=priority,
        )
        with self._lock:
            self._items[mid] = msg
            self._persist()
        emit_signal(EVENT_TASK_ASSIGN, sender="pending_queue", target=SIGNAL_TARGET_L3,
                     data={"card_id": card_id, "msg_id": mid, "event": "enqueued", "size": size})
        # Frontend notification chain: card entered the pending queue
        emit_signal("CARD_PENDING", sender="pending_queue", target=SIGNAL_TARGET_L3,
                     data={"card_id": card_id, "msg_id": mid, "event": "enqueued", "size": size})
        logger.info("pending enqueued: %s — %s (%s)", mid, intent[:LOG_TRUNC_60], size)
        return mid

    def dequeue(self, msg_id: str) -> PendingMessage | None:
        """Remove and return a message. Returns None if not found."""
        with self._lock:
            msg = self._items.pop(msg_id, None)
            if msg:
                self._persist()
            return msg

    def _stamp_card(self, card_id: str, status: str, by: str) -> None:
        try:
            from .card_registry import get_registry
            card = get_registry()._cards.get(card_id)
            if card:
                card.approval_status = status
                card.approval_at = time.time()
                card.approval_by = by
        except Exception:
            logger.debug("pending_queue: approval set failed")

    def approve(self, msg_id: str, response: str = "") -> dict:
        """Approve a pending card. Restores placeholder in CardRegistry."""
        card_id = ""
        with self._lock:
            msg = self._items.get(msg_id)
            if not msg:
                return {"success": False, "error": f"unknown message: {msg_id}"}
            if msg.status != PendingStatus.PENDING:
                return {"success": False, "error": f"message {msg.status.name}"}
            msg.status = PendingStatus.APPROVED
            msg.resolved_at = time.time()
            msg.response = response[:LOG_TRUNC_200]
            card_id = msg.card_id
            self._persist()

        # Stamp approval trail
        if card_id:
            self._stamp_card(card_id, "human_approved", HUMAN_SENDER)

        # Restore placeholder in CardRegistry
        if card_id and self._on_approve:
            try:
                self._on_approve(card_id)
            except Exception as e:
                logger.warning("pending_queue on_approve callback failed: %s", e)

        emit_signal(EVENT_TASK_ASSIGN, sender="pending_queue", target=SIGNAL_TARGET_L3,
                     data={"card_id": card_id, "msg_id": msg_id, "event": "approved"})
        return {"success": True, "card_id": card_id,
                "intent": msg.intent[:LOG_TRUNC_60] if msg else "", "size": msg.size if msg else ""}

    def reject(self, msg_id: str, response: str = "") -> dict:
        """Reject a pending card."""
        with self._lock:
            msg = self._items.get(msg_id)
            if not msg:
                return {"success": False, "error": f"unknown message: {msg_id}"}
            if msg.status != PendingStatus.PENDING:
                return {"success": False, "error": f"message {msg.status.name}"}
            msg.status = PendingStatus.REJECTED
            msg.resolved_at = time.time()
            msg.response = response[:LOG_TRUNC_200]
            self._persist()
        emit_signal(EVENT_TASK_ASSIGN, sender="pending_queue", target=SIGNAL_TARGET_L3,
                     data={"card_id": msg.card_id, "msg_id": msg_id, "event": "rejected"})
        return {"success": True, "card_id": msg.card_id}

    def escalate(self, msg_id: str) -> dict:
        """Escalate a pending card to convention."""
        with self._lock:
            msg = self._items.get(msg_id)
            if not msg:
                return {"success": False, "error": f"unknown message: {msg_id}"}
            if msg.status != PendingStatus.PENDING:
                return {"success": False, "error": f"message {msg.status.name}"}
            msg.status = PendingStatus.ESCALATED
            msg.resolved_at = time.time()
            self._persist()
        emit_signal(EVENT_TASK_ASSIGN, sender="pending_queue", target=SIGNAL_TARGET_L3,
                     data={"card_id": msg.card_id, "msg_id": msg_id, "event": "escalated"})
        return {"success": True, "card_id": msg.card_id, "action": "convention"}

    def list(self, status: str = "", limit: int = 50) -> list[dict]:
        """List pending messages, optionally filtered by status."""
        with self._lock:
            result = []
            for m in sorted(self._items.values(), key=lambda x: (x.priority, x.created_at)):
                if status and m.status.name != status.upper():
                    continue
                result.append({
                    "id": m.id, "card_id": m.card_id,
                    "intent": m.intent[:LOG_TRUNC_80], "domain": m.domain,
                    "size": m.size, "status": m.status.name,
                    "priority": m.priority, "created_at": m.created_at,
                })
                if len(result) >= limit:
                    break
            return result

    def get(self, msg_id: str) -> dict | None:
        """Return a serialized witness message or None if not found."""
        with self._lock:
            m = self._items.get(msg_id)
            if not m:
                return None
            return {
                "id": m.id, "card_id": m.card_id,
                "intent": m.intent[:LOG_TRUNC_120], "domain": m.domain,
                "size": m.size, "status": m.status.name,
                "priority": m.priority,
                "created_at": m.created_at, "resolved_at": m.resolved_at,
                "response": m.response, "metadata": m.metadata,
            }

    def stats(self) -> dict:
        """Return queue size and per-status counts."""
        with self._lock:
            counts: dict[str, int] = {}
            for m in self._items.values():
                counts[m.status.name] = counts.get(m.status.name, 0) + 1
            return {
                "total": len(self._items),
                "by_status": counts,
                "pending": counts.get(WitnessStatus.PENDING, 0),
            }

    def set_priority(self, msg_id: str, priority: int) -> dict:
        """Update the priority of a message and persist the change."""
        with self._lock:
            m = self._items.get(msg_id)
            if not m:
                return {"success": False, "error": f"unknown: {msg_id}"}
            m.priority = max(1, min(10, priority))
            self._persist()
            return {"success": True, "msg_id": msg_id, "priority": m.priority}


# ── Singleton ──

_queue: PendingQueue | None = None


def get_queue() -> PendingQueue:
    """Return the global PendingQueue singleton, creating it if needed."""
    global _queue
    if _queue is None:
        _queue = PendingQueue()
    return _queue


def reset_queue() -> None:
    """Reset the PendingQueue singleton to None."""
    global _queue
    _queue = None
