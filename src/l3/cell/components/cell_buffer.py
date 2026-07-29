"""CircularBuffer — fixed-size ring buffer extracted from cell.py for reuse."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CircularBuffer:
    """Fixed-size ring buffer. Oldest entries are overwritten when full.

    Used by Cell for rollback context, card history, and file snapshots.
    """

    def __init__(self, maxlen: int = 50, on_evict: Any = None):
        """Initialize the ring buffer with a maximum size and optional evict callback."""
        self._data: list = []
        self._maxlen = maxlen
        self._pos = 0
        self._on_evict = on_evict

    def push(self, item: Any) -> None:
        """Append an item, overwriting the oldest entry when the buffer is full."""
        evicted = None
        if len(self._data) < self._maxlen:
            self._data.append(item)
        else:
            idx = self._pos % self._maxlen
            evicted = self._data[idx]
            self._data[idx] = item
        self._pos += 1
        if evicted is not None and self._on_evict:
            try:
                self._on_evict(evicted)
            except Exception as e:
                logger.warning("CircularBuffer on_evict: %s", e)

    def pop(self, key: str = "") -> Any | None:
        """Remove and return the last item, or the item matching the given card_id."""
        if not key:
            return self._data.pop() if self._data else None
        for i, item in enumerate(self._data):
            if isinstance(item, dict) and item.get("card_id") == key:
                return self._data.pop(i)
        return None

    def get(self, key: str) -> Any | None:
        """Return the first item whose card_id matches the given key."""
        for item in self._data:
            if isinstance(item, dict) and item.get("card_id") == key:
                return item
        return None

    def remove(self, key: str) -> bool:
        """Remove the first item whose card_id matches the given key."""
        for i, item in enumerate(self._data):
            if isinstance(item, dict) and item.get("card_id") == key:
                self._data.pop(i)
                return True
        return False

    def all(self) -> list:
        """Return a shallow copy of all buffered items in insertion order."""
        return list(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        return iter(self._data)
