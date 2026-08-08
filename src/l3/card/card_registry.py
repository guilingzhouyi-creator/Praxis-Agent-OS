"""CardRegistry — central card queue, status tracking, auto-dispatch, persistent.

Cards enter the registry, are queued by priority, dispatched to Cells
by territory match, executed, and tracked through completion.

Persistence: JSON file at get_paths().card_registry, auto-saved every 30s.

Flow:
  submit(card) → PENDING → DISPATCHED → RUNNING → DONE | FAILED
                                       ↓ (territory match)
                                   Cell.execute_card()

The CardRegistry class composes five domain mixins: execution stats,
convention, persistence (PersistableMixin), dispatch (background poll /
routing / plan), and registry persistence (_serialize/_deserialize).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.params.agent import SIGNAL_TARGET_L3
from l1.kernel.params.system import (
    CARD_QUEUE_PENDING_MAX,
    CARD_REGISTRY_AUTO_SAVE,
    HASH_TRUNC_SHORT,
    LOG_TRUNC_40,
    LOG_TRUNC_60,
    LOG_TRUNC_80,
)
from l1.kernel.paths import get_paths as _gp
from l3._persistable import PersistableMixin

from .card_convention import CardConventionMixin
from .card_dispatch import CardDispatchMixin
from .card_execution_stats import CardExecutionStatsMixin
from .card_persistence import CardPersistenceMixin
from .card_unified import CardLifecycle, CardSummary, CardUnified

logger = logging.getLogger(__name__)


def _card_to_dict(r: CardUnified) -> dict:
    """Convert CardUnified to listing dict (unified format)."""
    elapsed = 0.0
    if r.timestamps.completed_at:
        elapsed = round(r.timestamps.completed_at - r.timestamps.dispatched_at, 2)
    elif r.timestamps.dispatched_at:
        elapsed = round(time.time() - r.timestamps.dispatched_at, 1)
    d = r.to_dict(include_hidden=False)
    d["elapsed"] = elapsed
    d["state"] = r.state.value  # CardLifecycle string value directly
    d["has_plan"] = bool(r.summary.columns or r.phases)
    d["plan_summary"] = r.summary.title[:LOG_TRUNC_80] if r.summary.title else ""
    return d


class CardRegistry(
    CardExecutionStatsMixin,
    CardConventionMixin,
    CardDispatchMixin,
    CardPersistenceMixin,
    PersistableMixin,
):
    """Central card queue — submit, dispatch, track, list, auto-persisted.

    Uses CardUnified as the single card model.
    Background dispatcher thread polls the queue and routes cards to Cells.
    """

    persistence_kind = "card_registry"

    def __init__(self, persist_path: str = ""):
        self._cards: dict[str, CardUnified] = {}
        self._queue: list[str] = []
        self._lock = threading.RLock()
        self._cell_map: dict[str, Any] = {}
        self._cell_resolver: Callable[[str], Any] | None = None
        self._dispatcher_running = False
        self._dispatcher_thread: threading.Thread | None = None
        self._subscribers: dict[str, list[Callable[[str, str, dict], None]]] = {}
        self._completion_listeners: list[Callable[[str, str, dict], None]] = []
        self._init_persistence(persist_path or _gp().card_registry, CARD_REGISTRY_AUTO_SAVE)
        self._restore()
        if CARD_REGISTRY_AUTO_SAVE > 0:
            self._start_auto_save()

    # ── Completion subscription (external closed-loop callbacks) ──

    def register_completion_listener(self, callback: Callable[[str, str, dict], None]) -> None:
        """Register a global completion callback fired for every card completion.

        Unlike ``subscribe`` (per-card, consumed once), global listeners are
        invoked for every COMPLETED/FAILED/CANCELLED card.  Used by system
        services such as the L4 CI review daemon.
        """
        with self._lock:
            self._completion_listeners.append(callback)

    def unregister_completion_listener(self, callback: Callable) -> None:
        """Remove a global completion callback."""
        with self._lock:
            try:
                self._completion_listeners.remove(callback)
            except ValueError:
                logger.debug("card_registry: completion listener not registered")

    def subscribe(self, card_id: str, callback: Callable[[str, str, dict], None]) -> None:
        """Register a completion callback for a card.

        Callback signature: (card_id, state, result) — fired on COMPLETED,
        FAILED, or CANCELLED. Used by L3A sessions to receive card results.
        """
        with self._lock:
            self._subscribers.setdefault(card_id, []).append(callback)

    def unsubscribe(self, card_id: str, callback: Callable | None = None) -> None:
        """Remove a callback for a card (all if callback omitted)."""
        with self._lock:
            if card_id not in self._subscribers:
                return
            if callback is None:
                del self._subscribers[card_id]
            else:
                self._subscribers[card_id] = [cb for cb in self._subscribers[card_id] if cb != callback]

    def _notify_subscribers(self, card_id: str, state: str, result: dict | None = None) -> None:
        with self._lock:
            callbacks = list(self._subscribers.get(card_id, []))
        for cb in callbacks:
            try:
                cb(card_id, state, result or {})
            except Exception as e:
                logger.warning("card %s subscriber callback failed: %s", card_id, e)
            finally:
                self.unsubscribe(card_id, cb)

    # ── Approval (explicit approve/reject for HOLD cards) ──

    def approve(self, card_id: str) -> dict:
        """Approve a held card: restore from placeholder and re-queue.

        Fires dispatch on the next dispatcher tick.
        """
        with self._lock:
            record = self._cards.get(card_id)
            if not record:
                return {"success": False, "error": f"unknown card: {card_id}"}
            if record.state != CardLifecycle.HOLD:
                return {"success": False, "error": f"card {card_id} not in HOLD state"}
            restored = self.restore_card(card_id)
            record.state = CardLifecycle.QUEUED
            if not restored and card_id not in self._queue:
                self._queue.append(card_id)
                self._queue.sort(key=lambda x: self._cards[x].priority if x in self._cards else 5)
        logger.info("card approved: %s", card_id)
        emit_signal(
            EVENT_TASK_ASSIGN,
            sender="registry",
            target=SIGNAL_TARGET_L3,
            data={"card_id": card_id, "event": "approved"},
        )
        return {"success": True, "card_id": card_id, "state": "QUEUED"}

    def reject(self, card_id: str, reason: str = "") -> dict:
        """Reject a held card: cancel it and notify dependents."""
        with self._lock:
            record = self._cards.get(card_id)
            if not record:
                return {"success": False, "error": f"unknown card: {card_id}"}
            if record.state not in (CardLifecycle.HOLD, CardLifecycle.QUEUED):
                return {"success": False, "error": f"card {card_id} not in HOLD/QUEUED state"}
            record.state = CardLifecycle.CANCELLED
            if card_id in self._queue:
                self._queue.remove(card_id)
            if reason:
                record.error = reason[:LOG_TRUNC_80]
        dependents = self._find_dependents(card_id)
        for dep_cid in dependents:
            with self._lock:
                dep = self._cards.get(dep_cid)
                if dep:
                    dep.state = CardLifecycle.CANCELLED
                    if dep_cid in self._queue:
                        self._queue.remove(dep_cid)
        logger.info(
            "card rejected: %s (reason=%s, dependents=%d)", card_id, reason[:LOG_TRUNC_40] or "none", len(dependents)
        )
        emit_signal(
            EVENT_TASK_ASSIGN,
            sender="registry",
            target=SIGNAL_TARGET_L3,
            data={"card_id": card_id, "event": "rejected", "reason": reason[:LOG_TRUNC_80]},
        )
        self._notify_subscribers(card_id, CardLifecycle.CANCELLED.value, {"reason": reason})
        return {"success": True, "card_id": card_id, "state": "CANCELLED", "dependents_cancelled": len(dependents)}

    # ── Placeholder system ──

    @staticmethod
    def _is_placeholder(entry: str) -> bool:
        return entry.startswith("__HOLD__:")

    @staticmethod
    def _placeholder_of(card_id: str) -> str:
        return f"__HOLD__:{card_id}"

    @staticmethod
    def _card_from_placeholder(entry: str) -> str:
        return entry.split(":", 1)[1] if ":" in entry else ""

    def restore_card(self, card_id: str) -> bool:
        """Replace a card's queue placeholder with the real id; True if restored."""
        placeholder = self._placeholder_of(card_id)
        with self._lock:
            for i, entry in enumerate(self._queue):
                if entry == placeholder:
                    self._queue[i] = card_id
                    self._queue.sort(key=lambda x: self._cards[x].priority if x in self._cards else 5)
                    logger.info("card %s restored from placeholder", card_id)
                    return True
        return False

    def hold_card(self, card_id: str) -> None:
        """Put a card on hold: placeholder in queue plus HOLD state."""
        with self._lock:
            for i, entry in enumerate(self._queue):
                if entry == card_id:
                    self._queue[i] = self._placeholder_of(card_id)
                    break
            record = self._cards.get(card_id)
            if record:
                record.state = CardLifecycle.HOLD

    def _find_dependents(self, card_id: str) -> list[str]:
        result = []
        with self._lock:
            for cid, rec in self._cards.items():
                if cid in rec._depends_on and rec.state == CardLifecycle.QUEUED:
                    result.append(cid)
        return result

    # ── Submit ──

    def submit(
        self, intent: str, domain: str = "", priority: int = 5, card_id: str = "", depends_on: list[str] | None = None
    ) -> str:
        """Submit a card to the queue and return its id (empty if the queue is full)."""
        cid = card_id or f"card-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        with self._lock:
            if len(self._queue) >= CARD_QUEUE_PENDING_MAX:
                logger.warning(
                    "card queue full (%d/%d), rejecting: %s",
                    len(self._queue),
                    CARD_QUEUE_PENDING_MAX,
                    intent[:LOG_TRUNC_40],
                )
                return ""
        card = CardUnified(id=cid, priority=priority)
        card.summary = CardSummary(title=intent, description="", columns={"domain": domain})
        card._depends_on = depends_on or []
        card.submit()
        with self._lock:
            self._cards[cid] = card
            self._queue.append(cid)
            self._queue.sort(key=lambda x: self._cards[x].priority if x in self._cards else 5)
        logger.info("card submitted: %s — %s", cid, intent[:LOG_TRUNC_60])
        emit_signal(
            EVENT_TASK_ASSIGN,
            sender="registry",
            target=SIGNAL_TARGET_L3,
            data={"card_id": cid, "intent": intent[:LOG_TRUNC_60], "event": "submitted"},
        )
        try:
            from l3.bus.reference_channel import get_rc as _rc

            _rc().card_lifecycle(cid, intent, "submitted", nature="", size="")
        except Exception:
            logger.debug("card_registry: rc lifecycle submit failed")
        return cid

    # ── Complete / Cancel ──

    def complete(self, card_id: str, result: dict | None = None, error: str = "") -> bool:
        """Complete or fail a card, notify subscribers, and fire lifecycle events."""
        with self._lock:
            record = self._cards.get(card_id)
            if not record:
                return False
            if error:
                record.fail(error)
            else:
                record.complete(summary="executed", changes=[result] if result else [])
            cell = self._cell_map.get(record.summary.columns.get("cell_id", ""))
            if cell:
                cell["active_cards"] = max(0, cell["active_cards"] - 1)
            if card_id in self._queue:
                self._queue.remove(card_id)
        emit_signal(
            EVENT_TASK_ASSIGN,
            sender="registry",
            target=SIGNAL_TARGET_L3,
            data={"card_id": card_id, "state": record.state.value, "event": "completed"},
        )
        # ── Completion subscribers (L3A session closed loop) ──
        self._notify_subscribers(card_id, record.state.value, result or {"error": error})
        # ── Global completion listeners (system services: CI review, ...) ──
        for cb in list(self._completion_listeners):
            try:
                cb(card_id, record.state.value, result or {"error": error})
            except Exception as e:
                logger.warning("card %s completion listener failed: %s", card_id, e)
        # ── Task completion bus: fire webhooks ──
        try:
            from l3.bus.task_bus import get_task_bus

            get_task_bus().dispatch(
                card_id,
                record.state.value,
                {
                    "intent": record.summary.columns.get("intent", record.summary.title) if record.summary else "",
                    "domain": record.summary.columns.get("domain", "") if record.summary else "",
                    "result": result or {},
                    "error": error,
                    "elapsed": time.time() - record.timestamps.created_at if hasattr(record, "timestamps") else 0,
                },
            )
        except Exception as e:
            logger.warning("task_bus dispatch failed: %s", e)
        try:
            from l3.bus.reference_channel import get_rc as _rc

            _rc().card_lifecycle(
                card_id, record.summary.title if record.summary else "", record.state.value, error=error
            )
        except Exception:
            logger.debug("card_registry: rc lifecycle update failed")
        return True

    def cancel(self, card_id: str) -> bool:
        """Cancel a card; returns False if unknown or already in a terminal state."""
        with self._lock:
            record = self._cards.get(card_id)
            if not record or record.state in (CardLifecycle.COMPLETED, CardLifecycle.FAILED, CardLifecycle.CANCELLED):
                return False
            record.state = CardLifecycle.CANCELLED
            if card_id in self._queue:
                self._queue.remove(card_id)
            cell = self._cell_map.get(record.summary.columns.get("cell_id", ""))
            if cell:
                cell["active_cards"] = max(0, cell["active_cards"] - 1)
        self._notify_subscribers(card_id, CardLifecycle.CANCELLED.value, {"reason": "cancelled"})
        return True

    # ── Query ──

    def get(self, card_id: str) -> CardUnified | None:
        """Return the CardUnified for a card, or None if not registered."""
        with self._lock:
            return self._cards.get(card_id)

    def list(
        self, state: CardLifecycle | str | None = None, cell_id: str = "", domain: str = "", limit: int = 50
    ) -> list[dict]:
        """List cards as dicts, filtered by state, cell, and domain, newest first."""
        with self._lock:
            result = []
            for r in sorted(self._cards.values(), key=lambda x: x.timestamps.created_at, reverse=True):
                if state:
                    target = state.value if isinstance(state, CardLifecycle) else state
                    if r.state.value != target:
                        continue
                if cell_id and r.summary.columns.get("cell_id", "") != cell_id:
                    continue
                if domain and r.summary.columns.get("domain", "") != domain:
                    continue
                result.append(_card_to_dict(r))
                if limit and len(result) >= limit:
                    break
            return result

    def pending_count(self) -> int:
        """Return the number of cards currently in the queue."""
        with self._lock:
            return len(self._queue)

    def cell_load(self, cell_id: str) -> dict:
        """Return a Cell's load stats (active cards, territories) or empty stats."""
        with self._lock:
            cell = self._cell_map.get(cell_id)
            if not cell:
                return {"active_cards": 0, "territories": []}
            return dict(cell)

    def stats(self) -> dict:
        """Return registry statistics: totals, queue length, cells, and state counts."""
        with self._lock:
            states: dict[str, int] = {}
            for r in self._cards.values():
                lc_state = r.state.value
                states[lc_state] = states.get(lc_state, 0) + 1
            return {
                "total": len(self._cards),
                "queue": len(self._queue),
                "cells": len(self._cell_map),
                "by_state": states,
            }


_registry: CardRegistry | None = None


def get_registry() -> CardRegistry:
    """Return the CardRegistry singleton, creating it on first call."""
    global _registry
    if _registry is None:
        _registry = CardRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the CardRegistry singleton so the next access re-creates it."""
    global _registry
    _registry = None
