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
        self._data: list = []
        self._maxlen = maxlen
        self._pos = 0
        self._on_evict = on_evict

    def push(self, item: Any) -> None:
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
        if not key:
            return self._data.pop() if self._data else None
        for i, item in enumerate(self._data):
            if isinstance(item, dict) and item.get("card_id") == key:
                return self._data.pop(i)
        return None

    def get(self, key: str) -> Any | None:
        for item in self._data:
            if isinstance(item, dict) and item.get("card_id") == key:
                return item
        return None

    def remove(self, key: str) -> bool:
        for i, item in enumerate(self._data):
            if isinstance(item, dict) and item.get("card_id") == key:
                self._data.pop(i)
                return True
        return False

    def all(self) -> list:
        return list(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        return iter(self._data)
