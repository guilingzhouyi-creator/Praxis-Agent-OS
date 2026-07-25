"""Kernel IPC — low-level message passing for cross-process sync primitives.

Architecture:
  LockChannel carries LockMessage between processes.
  Each Mutex/Semaphore has a dedicated IPC channel for remote waiters.

  sync.py uses this as optional backend:
    thread-safe (default):   threading.Lock (same-process)
    cross-process (opt-in):  LockChannel over IPC bus (multi-process)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

from .params import IPC_DEFAULT_PRIORITY, IPC_MSG_ID_LENGTH, IPC_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class LockOp(Enum):
    ACQUIRE = auto()
    RELEASE = auto()
    STATUS = auto()
    BOOST = auto()


@dataclass
class LockMessage:
    op: LockOp
    lock_name: str
    agent_id: str = ""
    priority: float = IPC_DEFAULT_PRIORITY
    reply_to: str = ""
    timestamp: float = field(default_factory=time.time)
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:IPC_MSG_ID_LENGTH])


class LockChannel:
    """Dedicated IPC channel for lock operations on a single sync primitive.

    Thread-safe.  Each Mutex / Semaphore can own one LockChannel.
    """

    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self._queue: deque[LockMessage] = deque()
        self._responses: dict[str, Any] = {}
        self._response_events: dict[str, threading.Event] = {}
        self._handlers: list[Callable[[LockMessage], Any]] = []

    def send(self, msg: LockMessage) -> str:
        with self._lock:
            self._queue.append(msg)
            for handler in self._handlers:
                try:
                    reply = handler(msg)
                    if reply is not None:
                        self._responses[msg.msg_id] = reply
                        ev = self._response_events.pop(msg.msg_id, None)
                        if ev:
                            ev.set()
                except Exception as e:
                    logger.error("LockChannel handler error: %s", e)
        return msg.msg_id

    def request(self, msg: LockMessage, timeout: float = IPC_REQUEST_TIMEOUT) -> Any:
        event = threading.Event()
        with self._lock:
            self._response_events[msg.msg_id] = event
            self._queue.append(msg)
        event.wait(timeout=timeout)
        # Always clean up our registration so abandoned request events
        # do not accumulate in _response_events (memory leak).
        with self._lock:
            self._response_events.pop(msg.msg_id, None)
            return self._responses.pop(msg.msg_id, {})

    def respond(self, msg_id: str, data: Any) -> None:
        with self._lock:
            self._responses[msg_id] = data
            ev = self._response_events.pop(msg_id, None)
            if ev:
                ev.set()

    def register_handler(self, handler: Callable[[LockMessage], Any]) -> None:
        with self._lock:
            self._handlers.append(handler)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)


class LockBus:
    """Central IPC registry for lock channels — cross-process sync backbone."""

    def __init__(self):
        self._channels: dict[str, LockChannel] = {}
        self._lock = threading.Lock()

    def get_channel(self, name: str) -> LockChannel:
        with self._lock:
            if name not in self._channels:
                self._channels[name] = LockChannel(name)
            return self._channels[name]

    def channel_exists(self, name: str) -> bool:
        with self._lock:
            return name in self._channels

    def stats(self) -> dict:
        with self._lock:
            return {n: ch.pending_count() for n, ch in self._channels.items()}


_lock_bus: LockBus | None = None


def get_lock_bus() -> LockBus:
    global _lock_bus
    if _lock_bus is None:
        _lock_bus = LockBus()
    return _lock_bus


def reset_lock_bus() -> None:
    global _lock_bus
    _lock_bus = None
