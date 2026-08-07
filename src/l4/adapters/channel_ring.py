"""ChannelPort adapter — fixed-capacity ring buffer with backpressure.

Thread-safe producer-consumer channel backed by a pre-allocated array.
Supports blocking put/get with timeout, non-destructive peek, and
overwrite-oldest mode.

Usage:
    from l4.adapters.channel_ring import RingChannel
    ch = RingChannel(capacity=CHANNEL_RING_CAPACITY)
    ch.put({"type": "ping"})
    msg = ch.get(timeout=5.0)
"""

from __future__ import annotations

import threading
import time
from typing import Any

from l1.kernel.ports import ChannelPort


class RingChannel(ChannelPort):
    """Fixed-capacity ring-buffer channel with backpressure.

    Thread-safety: single Lock + two Conditions (not_full, not_empty).
    """

    def __init__(self, capacity: int = 1024, overwrite: bool = False) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity: int = capacity
        self._overwrite: bool = overwrite
        self._buffer: list[Any | None] = [None] * capacity
        self._head: int = 0   # next read position
        self._tail: int = 0   # next write position
        self._count: int = 0
        self._closed: bool = False
        self._lock = threading.Lock()
        self._not_full = threading.Condition(self._lock)
        self._not_empty = threading.Condition(self._lock)

    # ── ChannelPort interface ─────────────────────────────────────────────

    def put(self, item: Any, timeout: float | None = None) -> bool:
        """Enqueue *item*. Returns False if full and *timeout* elapsed.

        In *overwrite* mode, drops the oldest item instead of blocking.
        """
        if self._closed:
            return False
        if self._overwrite and self._count == self._capacity:
            # Drop oldest — advance head, overwrite tail in-place
            with self._lock:
                if self._count == self._capacity:
                    self._head = (self._head + 1) % self._capacity
                    self._count -= 1
                    # One slot freed — notify producers
                    self._not_full.notify()

        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while self._count == self._capacity and not self._closed:
                remaining = deadline - time.monotonic() if deadline else None
                if remaining is not None and remaining <= 0:
                    return False
                self._not_full.wait(timeout=remaining)
            if self._closed:
                return False
            self._buffer[self._tail] = item
            self._tail = (self._tail + 1) % self._capacity
            self._count += 1
            self._not_empty.notify()
            return True

    def get(self, timeout: float | None = None) -> Any | None:
        """Dequeue an item. Returns None if empty and *timeout* elapsed."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while self._count == 0 and not self._closed:
                remaining = deadline - time.monotonic() if deadline else None
                if remaining is not None and remaining <= 0:
                    return None
                self._not_empty.wait(timeout=remaining)
            if self._count == 0:
                return None  # closed and empty
            item = self._buffer[self._head]
            self._buffer[self._head] = None  # release reference
            self._head = (self._head + 1) % self._capacity
            self._count -= 1
            self._not_full.notify()
            return item

    def size(self) -> int:
        """Return the number of buffered items."""
        with self._lock:
            return self._count

    def capacity(self) -> int:
        return self._capacity

    def close(self) -> None:
        """Close the channel, waking any blocked producers/consumers."""
        with self._lock:
            self._closed = True
            self._not_empty.notify_all()
            self._not_full.notify_all()

    # ── Extended API (non-Port) ──

    def peek(self, timeout: float | None = None) -> Any | None:
        """Read the next item without removing it."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while self._count == 0 and not self._closed:
                remaining = deadline - time.monotonic() if deadline else None
                if remaining is not None and remaining <= 0:
                    return None
                self._not_empty.wait(timeout=remaining)
            if self._count == 0:
                return None
            return self._buffer[self._head]

    def drain(self) -> list[Any]:
        """Remove and return all buffered items (non-blocking)."""
        items: list[Any] = []
        with self._lock:
            while self._count > 0:
                item = self._buffer[self._head]
                self._buffer[self._head] = None
                self._head = (self._head + 1) % self._capacity
                self._count -= 1
                items.append(item)
            self._not_full.notify()
        return items

    def utilization(self) -> float:
        """Return fraction of capacity in use [0.0, 1.0]."""
        with self._lock:
            return self._count / self._capacity if self._capacity else 0.0

    def is_closed(self) -> bool:
        """Return True once the channel has been closed."""
        with self._lock:
            return self._closed
