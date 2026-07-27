"""ResourceBufferManager — high-level API for tools._files and file_editor."""

from __future__ import annotations

import logging
from typing import Any

from .ring import RingBuffer

logger = logging.getLogger(__name__)


class ResourceBufferManager:
    """Resource manager high-level entry — unified stage/commit/read/diff/discard."""

    def __init__(self):
        self._ring = RingBuffer()
        self._ring.recover()

    def stage(self, path: str, content: str, op: str = "edit") -> dict:
        return self._ring.stage(path, content, op)

    def commit(self, path: str = "") -> dict:
        if path:
            return self._ring.commit(path)
        return self._ring.commit_all()

    def commit_all(self) -> dict:
        return self._ring.commit_all()

    def discard(self, path: str = "") -> dict:
        if path:
            return self._ring.discard(path)
        return {"success": False, "error": "path required"}

    def read(self, path: str) -> str:
        return self._ring.read(path)

    def diff(self, path: str) -> dict:
        return self._ring.diff(path)

    def status(self) -> dict:
        return self._ring.status()


# ── Singleton ──

_manager: ResourceBufferManager | None = None


def get_manager() -> ResourceBufferManager:
    global _manager
    if _manager is None:
        _manager = ResourceBufferManager()
    return _manager


def reset_manager() -> None:
    global _manager
    if _manager:
        _manager._ring.stop()
    _manager = None
