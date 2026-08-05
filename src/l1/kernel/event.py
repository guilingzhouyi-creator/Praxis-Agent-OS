"""Kernel event bus — publish/subscribe with history and async dispatch."""
from __future__ import annotations

import logging
import time as _time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum, auto
from threading import RLock
from typing import Any

from .params.kernel import EVENT_BUS_MAX_QUEUED, EVENT_BUS_WORKERS, EVENT_MAX_HISTORY, EVENT_QUERY_LIMIT

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """SignalType — enum of TASK_ASSIGN, TASK_CANCEL, REVIEW_RESULT, CONSTITUTION_UPDATE...."""
    # L3 → Agent
    TASK_ASSIGN = auto()
    TASK_CANCEL = auto()
    REVIEW_RESULT = auto()
    CONSTITUTION_UPDATE = auto()
    # Agent → L3
    TASK_DONE = auto()
    TASK_ACCEPT = auto()
    TASK_ERROR = auto()
    DISPUTE_RAISE = auto()
    AGENT_CRASH = auto()
    STATE_CHANGE = auto()
    # Agent ↔ Agent
    CROSS_REVIEW_REQ = auto()
    CROSS_REVIEW_RESP = auto()
    TERRITORY_QUERY = auto()
    # Scout
    SCOUT_DONE = auto()
    # System
    REVIEW_REQUESTED = auto()
    TOKEN_USAGE = auto()       # Token usage event (Cell/Agent → CentralCollector)
    # File change events (Sandbox → Cell/Agent)
    FILE_CHANGED = auto()      # A file was written to sandbox
    # Card / approval flow events (Card layer → EventBus → SSE/WS push)
    CARD_PENDING = auto()      # Card entered the pending queue
    APPROVAL_REQUIRED = auto() # Card blocked by the approval gate
    APPROVAL_RESPONDED = auto()  # Approval response committed


# Extensible signal type registry — register custom signals by name
_SIGNAL_TYPE_REGISTRY: dict[str, SignalType] = {}


def register_signal_type(name: str) -> SignalType:
    """Register a custom signal type.  Returns a new SignalType member."""
    if name in _SIGNAL_TYPE_REGISTRY:
        return _SIGNAL_TYPE_REGISTRY[name]
    if hasattr(SignalType, name):
        raise ValueError(f"SignalType.{name} already exists as a built-in member")
    # Dynamically extend the enum (Python 3.11+)
    count = max(m.value for m in SignalType) + 1 if SignalType.__members__ else 1
    new_member = object.__new__(SignalType)
    new_member._name_ = name
    new_member._value_ = count
    SignalType._member_map_[name] = new_member
    _SIGNAL_TYPE_REGISTRY[name] = new_member
    return new_member


@dataclass
class Signal:
    """Signal — signal record (type, data, sender, target, timestamp)."""
    type: SignalType
    data: dict = field(default_factory=dict)
    sender: str = ""
    target: str = ""
    timestamp: float = field(default_factory=_time.time)

    def to_dict(self) -> dict:
        return {"type": self.type.name, "data": self.data, "sender": self.sender,
                "target": self.target, "timestamp": self.timestamp}


class EventBus:
    """Publish/subscribe event bus with async dispatch."""

    def __init__(self, max_history: int = EVENT_MAX_HISTORY):
        self._listeners: dict[SignalType, list[Callable]] = {}
        self._history: deque[Signal] = deque(maxlen=max_history)
        self._wildcard_listeners: list[Callable] = []
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=EVENT_BUS_WORKERS, thread_name_prefix="evt")
        self._shutdown = False
        self._MAX_EVT_QUEUED = EVENT_BUS_MAX_QUEUED
        """Max pending tasks in executor queue; beyond this, new tasks are dropped."""

    def on(self, st: SignalType, cb: Callable) -> None:
        with self._lock:
            self._listeners.setdefault(st, []).append(cb)

    def on_any(self, cb: Callable) -> None:
        with self._lock:
            self._wildcard_listeners.append(cb)

    def off_any(self, cb: Callable) -> None:
        """Unsubscribe a wildcard listener previously added via on_any()."""
        with self._lock:
            if cb in self._wildcard_listeners:
                self._wildcard_listeners.remove(cb)

    def off(self, st: SignalType, cb: Callable | None = None) -> None:
        with self._lock:
            if cb:
                self._listeners[st] = [l for l in self._listeners.get(st, []) if l != cb]
            else:
                self._listeners.pop(st, None)

    def emit(self, signal: Signal) -> int:
        """Emit a signal — record to history synchronously, dispatch callbacks asynchronously.

        Returns the number of callbacks queued. Callbacks run in a thread pool so that
        a slow or blocking callback cannot block the emitter or other subscribers.
        If the bus has been shut down, callbacks are dispatched synchronously instead.
        """
        if self._shutdown:
            # Fall back to synchronous dispatch after shutdown
            with self._lock:
                self._history.append(signal)
                callbacks = list(self._listeners.get(signal.type, []))
                wildcards = list(self._wildcard_listeners)
            for cb in callbacks:
                self._safe_call(cb, signal)
            for cb in wildcards:
                self._safe_call(cb, signal)
            return len(callbacks) + len(wildcards)

        with self._lock:
            self._history.append(signal)
            callbacks = list(self._listeners.get(signal.type, []))
            wildcards = list(self._wildcard_listeners)

        count = len(callbacks) + len(wildcards)
        for cb in callbacks:
            self._bounded_submit(self._safe_call, cb, signal)
        for cb in wildcards:
            self._bounded_submit(self._safe_call, cb, signal)
        return count

    def _bounded_submit(self, fn: Callable, *args: Any) -> None:
        """Submit a task to the executor, dropping if the work queue is too deep."""
        if self._executor._work_queue.qsize() >= self._MAX_EVT_QUEUED:
            logger.warning("event_bus: executor queue full (%d), dropping task", self._MAX_EVT_QUEUED)
            return
        self._executor.submit(fn, *args)

    @staticmethod
    def _safe_call(cb: Callable, signal: Signal) -> None:
        try:
            cb(signal)
        except Exception as e:
            logger.warning("event handler: %s", e)

    # ── String-based convenience API (for extensibility, cross-platform) ──

    def emit_event(self, event_type: str, data: dict | None = None,
                   source: str = "") -> int:
        """Emit an event by string type name.  Extensible — no enum needed."""
        st = _SIGNAL_TYPE_REGISTRY.get(event_type)
        if st is None:
            st = register_signal_type(event_type)
        signal = Signal(type=st, data=data or {}, sender=source)
        return self.emit(signal)

    def on_event(self, event_type: str, callback: Callable) -> None:
        """Subscribe to an event by string type name."""
        st = _SIGNAL_TYPE_REGISTRY.get(event_type)
        if st is None:
            st = register_signal_type(event_type)
        self.on(st, callback)

    def off_event(self, event_type: str, callback: Callable | None = None) -> None:
        """Unsubscribe from an event by string type name."""
        st = _SIGNAL_TYPE_REGISTRY.get(event_type)
        if st:
            self.off(st, callback)

    def history(self, signal_type: SignalType | None = None,
                limit: int = EVENT_QUERY_LIMIT) -> list[dict]:
        with self._lock:
            safe_slice = list(self._history)[-limit * 2:]
        if signal_type:
            safe_slice = [s for s in safe_slice if s.type == signal_type]
        return [s.to_dict() for s in safe_slice[-limit:]]

    def stats(self) -> dict:
        with self._lock:
            return {
                "signal_types": len(self._listeners),
                "listeners": sum(len(v) for v in self._listeners.values()),
                "history": len(self._history),
                "wildcard_listeners": len(self._wildcard_listeners),
                "queue_depth": self._executor._work_queue.qsize(),
                "queue_max": self._MAX_EVT_QUEUED,
            }

    def shutdown(self) -> None:
        """Shut down the async dispatch executor. Idempotent."""
        if self._shutdown:
            return
        self._shutdown = True
        self._executor.shutdown(wait=False)


_bus = EventBus()


def get_bus() -> EventBus:
    return _bus


def reset_bus() -> None:
    """Reset the global event bus singleton. Used by tests."""
    global _bus
    if _bus:
        _bus.shutdown()
    _bus = EventBus()
