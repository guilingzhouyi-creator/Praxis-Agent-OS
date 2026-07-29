"""EventBusPort adapter — in-memory pub/sub event bus.

Thread-safe subscription and emission.  Supports glob-style pattern matching
on event types for selective subscription.

Usage:
    from l4.adapters.bus_memory import MemoryBusAdapter
    bus = MemoryBusAdapter()
    bus.emit(Event(type="network.peer.join", source="net", severity="info", ...))
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
import uuid
from typing import Any, Callable

from l1.kernel.ports import EventBusPort, Event
from l1.kernel.params.system import HASH_TRUNC_MEDIUM

logger = logging.getLogger(__name__)


class MemoryBusAdapter(EventBusPort):
    """In-memory event bus implementing EventBusPort.

    Thread-safe: all mutations happen under a single RLock.
    Subscriber callbacks are invoked synchronously on the emitter's thread
    (non-blocking contract is met by keeping callbacks cheap).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, tuple[str | None, Callable]] = {}  # sub_id → (pattern, handler)
        self._event_count: int = 0
        self._sub_count: int = 0

    # ── EventBusPort interface ───────────────────────────────────────────

    def emit(self, event: Event) -> None:
        """Publish an event to all matching subscribers."""
        with self._lock:
            self._event_count += 1
            matches = [
                handler
                for sub_id, (pattern, handler) in self._subscribers.items()
                if pattern is None or fnmatch.fnmatch(event.type, pattern)
            ]
        for handler in matches:
            try:
                handler(event)
            except Exception as e:
                logger.warning("event handler error: %s (type=%s)", e, event.type)

    def subscribe(self, handler: Callable | None = None,
                  pattern: str | None = None) -> str:
        """Subscribe *handler* to events matching *pattern* (glob).

        If *pattern* is None, subscribes to ALL events.
        If *handler* is None, a no-op handler is used (for placeholder subs).
        Returns a subscription ID for later ``unsubscribe()``.
        """
        sub_id = uuid.uuid4().hex[:HASH_TRUNC_MEDIUM]
        actual_handler = handler or (lambda _: None)
        with self._lock:
            self._subscribers[sub_id] = (pattern, actual_handler)
            self._sub_count += 1
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        with self._lock:
            if sub_id in self._subscribers:
                del self._subscribers[sub_id]
                return True
            return False

    def stats(self) -> dict:
        with self._lock:
            return {
                "subscribers": len(self._subscribers),
                "total_subscribed": self._sub_count,
                "total_events": self._event_count,
            }

    # ── Extended API ──

    def clear(self) -> int:
        """Remove all subscribers. Returns count of removed subs."""
        with self._lock:
            n = len(self._subscribers)
            self._subscribers.clear()
            return n
