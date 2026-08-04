"""Transaction Area — card queue between L3A and Cell, auto-persisted.

L3A writes cards → pushes to Transaction Area → sits in queue
  → Human reviews / edits / approves / postpones / deletes
  → Auto-mode: auto-push after configurable delay
  → Dispatched to Cell

No card can bypass the Transaction Area — not even auto-approval.

Persistence: JSON file at get_paths().transaction_area, auto-saved every 30s.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto

from l1.kernel.params.system import LOG_TRUNC_50, LOG_TRUNC_60, TRANSACTION_AREA_AUTO_SAVE
from l1.kernel.paths import get_paths as _gp
from l3._base import BaseService
from l3._persistable import PersistableMixin

logger = logging.getLogger(__name__)


class CardStatus(Enum):
    """CardStatus — enum of PENDING, APPROVED, DISPATCHED, POSTPONED...."""
    PENDING = auto()       # In queue, waiting for decision
    APPROVED = auto()      # Approved, ready to dispatch
    DISPATCHED = auto()    # Sent to Cell
    POSTPONED = auto()     # Postponed by human
    CANCELLED = auto()     # Cancelled by human
    FAILED = auto()        # Dispatch failed


@dataclass
class TransactionCard:
    """A card in the transaction area queue."""
    card_id: str
    intent: str
    domain: str
    card_type: str              # execution | issue | composite
    size: str                   # small | medium | large
    priority: int = 3
    status: CardStatus = CardStatus.PENDING
    created_at: float = field(default_factory=time.time)
    approved_at: float = 0.0
    dispatched_at: float = 0.0
    source: str = "l3a"         # Who created the card
    auto_approve: bool = False  # Auto-mode flag
    auto_delay: float = 5.0     # Auto-approve delay in seconds
    metadata: dict = field(default_factory=dict)


class TransactionArea(BaseService, PersistableMixin):
    """Transaction Area — card queue with human-in-the-loop, auto-persisted.

    Queue rules:
      - All cards enter the queue, no bypass
      - Auto-approval is on-demand, not timer-based:
        Small cards → auto-approve immediately
        Medium cards → auto-approve after priority check
        Large cards → human approval required
      - Human can intervene at any time: approve, postpone, cancel, edit
      - Dispatched cards are removed from the queue
    """

    persistence_kind = "transaction_area"

    def __init__(self, max_queue: int = 100, persist_path: str = ""):
        super().__init__("transaction_area")
        self._queue: dict[str, TransactionCard] = {}
        self._history: list[TransactionCard] = []
        self._lock = threading.RLock()
        self._max_queue = max_queue
        self._dispatched_count = 0
        self._init_persistence(persist_path or _gp().transaction_area, TRANSACTION_AREA_AUTO_SAVE)
        self._restore()
        if TRANSACTION_AREA_AUTO_SAVE > 0:
            self._start_auto_save()

    def _serialize(self) -> dict:
        def _card_dict(c: TransactionCard) -> dict:
            return {
                "card_id": c.card_id, "intent": c.intent, "domain": c.domain,
                "card_type": c.card_type, "size": c.size, "priority": c.priority,
                "status": c.status.name, "created_at": c.created_at,
                "approved_at": c.approved_at, "dispatched_at": c.dispatched_at,
                "source": c.source, "auto_approve": c.auto_approve,
                "auto_delay": c.auto_delay, "metadata": c.metadata,
            }
        return {
            "queue": {cid: _card_dict(c) for cid, c in self._queue.items()},
            "history": [_card_dict(c) for c in self._history],
            "dispatched_count": self._dispatched_count,
            "max_queue": self._max_queue,
        }

    def _deserialize(self, data: dict) -> bool:
        self._queue.clear()
        self._history.clear()
        self._dispatched_count = data.get("dispatched_count", 0)
        self._max_queue = data.get("max_queue", 100)
        for cid, d in data.get("queue", {}).items():
            self._queue[cid] = TransactionCard(
                card_id=d["card_id"], intent=d.get("intent", ""),
                domain=d.get("domain", ""), card_type=d.get("card_type", "execution"),
                size=d.get("size", "small"), priority=d.get("priority", 3),
                status=CardStatus[d["status"]],
                created_at=d.get("created_at", 0.0),
                approved_at=d.get("approved_at", 0.0),
                dispatched_at=d.get("dispatched_at", 0.0),
                source=d.get("source", "l3a"),
                auto_approve=d.get("auto_approve", False),
                auto_delay=d.get("auto_delay", 5.0),
                metadata=d.get("metadata", {}),
            )
        for d in data.get("history", []):
            self._history.append(TransactionCard(
                card_id=d["card_id"], intent=d.get("intent", ""),
                domain=d.get("domain", ""), card_type=d.get("card_type", "execution"),
                size=d.get("size", "small"), priority=d.get("priority", 3),
                status=CardStatus[d["status"]],
                created_at=d.get("created_at", 0.0),
                approved_at=d.get("approved_at", 0.0),
                dispatched_at=d.get("dispatched_at", 0.0),
                source=d.get("source", "l3a"),
                auto_approve=d.get("auto_approve", False),
                auto_delay=d.get("auto_delay", 5.0),
                metadata=d.get("metadata", {}),
            ))
        return True

    def _on_start(self) -> dict:
        return {"success": True, "max_queue": self._max_queue}

    def _on_stop(self) -> dict:
        self._persist()
        with self._lock:
            self._queue.clear()
        return {"success": True}

    def enqueue(self, intent: str, domain: str,
                card_type: str = "execution",
                size: str = "small",
                priority: int = 3,
                source: str = "l3a",
                auto_approve: bool = True) -> dict:
        """L3A pushes a card to the transaction queue.
        
        Auto-approval is on-demand (not timer-based):
          Small cards → auto-approve immediately if auto_approve=True
          Medium cards → auto-approve after priority check
          Large cards → always require human approval
        """
        card_id = f"card-{uuid.uuid4().hex[:6]}"

        # Determine auto-approval eligibility
        can_auto = auto_approve and size != "large"
        if can_auto and size == "medium" and priority > 5:
            can_auto = False  # High-priority medium cards need human review

        card = TransactionCard(
            card_id=card_id, intent=intent, domain=domain,
            card_type=card_type, size=size, priority=priority,
            source=source, auto_approve=can_auto,
        )
        with self._lock:
            if len(self._queue) >= self._max_queue:
                return {"success": False, "error": "transaction queue full"}
            self._queue[card_id] = card

        # On-demand auto-approval for small cards
        if can_auto and size == "small":
            card.status = CardStatus.APPROVED
            card.approved_at = time.time()
            logger.info("card auto-approved (small): %s — %s", card_id, intent[:LOG_TRUNC_50])
            return {"success": True, "card_id": card_id, "status": "approved", "auto": True}

        if can_auto and size == "medium":
            card.status = CardStatus.APPROVED
            card.approved_at = time.time()
            logger.info("card auto-approved (medium): %s — %s", card_id, intent[:LOG_TRUNC_50])
            return {"success": True, "card_id": card_id, "status": "approved", "auto": True}

        logger.info("card enqueued: %s — %s (%s, waiting human)", card_id, intent[:LOG_TRUNC_50], size)
        return {"success": True, "card_id": card_id, "status": "pending"}

    def approve(self, card_id: str) -> dict:
        """Approve a card (human or auto)."""
        with self._lock:
            card = self._queue.get(card_id)
            if not card:
                return {"success": False, "error": "card not found"}
            if card.status != CardStatus.PENDING:
                return {"success": False, "error": f"card status is {card.status.name}"}
            card.status = CardStatus.APPROVED
            card.approved_at = time.time()
        logger.info("card approved: %s", card_id)
        return {"success": True, "card_id": card_id, "status": "approved"}

    def postpone(self, card_id: str, delay: float = 60.0) -> dict:
        """Postpone a card."""
        with self._lock:
            card = self._queue.get(card_id)
            if not card:
                return {"success": False, "error": "card not found"}
            card.status = CardStatus.POSTPONED
        logger.info("card postponed: %s", card_id)
        return {"success": True, "card_id": card_id, "status": "postponed", "delay": delay}

    def cancel(self, card_id: str) -> dict:
        """Cancel a card."""
        with self._lock:
            card = self._queue.pop(card_id, None)
            if not card:
                return {"success": False, "error": "card not found"}
            card.status = CardStatus.CANCELLED
            self._history.append(card)
        logger.info("card cancelled: %s", card_id)
        return {"success": True, "card_id": card_id}

    def dispatch(self, card_id: str) -> dict:
        """Dispatch a card to Cell. Removes from queue."""
        with self._lock:
            card = self._queue.get(card_id)
            if not card:
                return {"success": False, "error": "card not found"}
            if card.status != CardStatus.APPROVED:
                return {"success": False, "error": f"card not approved (status={card.status.name})"}
            card.status = CardStatus.DISPATCHED
            card.dispatched_at = time.time()
            self._queue.pop(card_id)
            self._history.append(card)
            self._dispatched_count += 1
        logger.info("card dispatched: %s → Cell", card_id)
        return {"success": True, "card_id": card_id, "dispatched": True, "intent": card.intent}

    def auto_tick(self) -> list[str]:
        """Auto-approve cards that have passed their auto_delay.
        Called periodically by the scheduler.
        """
        approved = []
        now = time.time()
        with self._lock:
            for card_id, card in list(self._queue.items()):
                if card.auto_approve and card.status == CardStatus.PENDING:
                    if now - card.created_at >= card.auto_delay:
                        card.status = CardStatus.APPROVED
                        card.approved_at = now
                        approved.append(card_id)
        if approved:
            logger.info("auto-approved %d cards", len(approved))
        return approved

    def list_queue(self, status: str | None = None) -> dict:
        """List cards in the queue."""
        with self._lock:
            cards = list(self._queue.values())
        if status:
            status_enum = getattr(CardStatus, status.upper(), None)
            if status_enum:
                cards = [c for c in cards if c.status == status_enum]
        return {
            "success": True,
            "cards": [{"card_id": c.card_id, "intent": c.intent[:LOG_TRUNC_60],
                       "domain": c.domain, "size": c.size, "priority": c.priority,
                       "status": c.status.name, "created_at": c.created_at}
                      for c in sorted(cards, key=lambda x: -x.priority)],
            "count": len(cards),
        }

    def stats(self) -> dict:
        with self._lock:
            pending = sum(1 for c in self._queue.values() if c.status == CardStatus.PENDING)
            approved = sum(1 for c in self._queue.values() if c.status == CardStatus.APPROVED)
            return {
                "queue_size": len(self._queue),
                "pending": pending,
                "approved_awaiting_dispatch": approved,
                "dispatched_total": self._dispatched_count,
                "history_size": len(self._history),
            }


_service: TransactionArea | None = None


def get_service() -> TransactionArea:
    global _service
    if _service is None:
        _service = TransactionArea()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None
