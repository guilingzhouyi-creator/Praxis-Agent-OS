"""Danger-action broadcast port — supervisory notifications for risky operations.

High-danger tool calls (auto-approved by harness downgrade or human
approval) and blocked attempts broadcast through ``NotifyPort`` so the
operator can be reached outside the process — future adapters may deliver
to webhooks, phone push, or other media via the API channel. The default
adapter keeps an in-memory queue and mirrors events on the EventBus for
SSE/WS push; wiring may replace it at boot with ``register_port("notify",
adapter)``.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Any

from l1.kernel.event import Signal, SignalType, get_bus
from l1.kernel.params.system import NOTIFY_QUEUE_MAX

logger = logging.getLogger(__name__)


class NotifyPort(ABC):
    """Abstract outbound notification channel for supervisory events."""

    @abstractmethod
    def broadcast(self, topic: str, payload: dict[str, Any]) -> None:
        """Deliver a supervisory event to the operator channel (never raises)."""


class LocalNotifyAdapter(NotifyPort):
    """In-process default adapter: bounded queue + EventBus mirror.

    The queue stays queryable for the pull API; the EventBus mirror feeds
    the SSE/WS push path. Delivery failures are logged, never raised — the
    protected path must not break because a notification failed.
    """

    def __init__(self) -> None:
        self._queue: deque[dict[str, Any]] = deque(maxlen=NOTIFY_QUEUE_MAX)
        self._lock = threading.RLock()

    def broadcast(self, topic: str, payload: dict[str, Any]) -> None:
        entry = {
            "topic": topic,
            "payload": payload,
            "ts": time.time(),
        }
        with self._lock:
            self._queue.append(entry)
        try:
            get_bus().emit(
                Signal(
                    type=SignalType.REVIEW_REQUESTED,
                    sender="notify",
                    target="l3",
                    data={"topic": topic, "payload": payload},
                )
            )
        except Exception:
            logger.warning("notify: event bus mirror failed for topic %s", topic)
        logger.info("notify: broadcast topic=%s", topic)

    def recent(self, limit: int = 0) -> list[dict[str, Any]]:
        """Return recent notifications (newest first); 0 limit = all buffered."""
        with self._lock:
            items = list(self._queue)
        items.reverse()
        if limit > 0:
            items = items[:limit]
        return items


_default_adapter = LocalNotifyAdapter()
_notify_lock = threading.Lock()


def get_notify() -> NotifyPort:
    """Return the active NotifyPort (wiring-registered adapter or default)."""
    try:
        from l1.kernel.ports import get_port

        adapter = get_port("notify")
        if adapter is not None:
            return adapter  # type: ignore[return-value]
    except KeyError:
        pass
    return _default_adapter


def reset_notify() -> None:
    """Reset the default adapter queue (tests / hot reset)."""
    global _default_adapter
    with _notify_lock:
        _default_adapter = LocalNotifyAdapter()
