"""ResourceBufferManager — high-level API for tools._files and file_editor."""

from __future__ import annotations

import logging

from .ring import RingBuffer

logger = logging.getLogger(__name__)


class ResourceBufferManager:
    """Resource manager high-level entry — unified stage/commit/read/diff/discard."""

    def __init__(self):
        self._ring = RingBuffer()
        self._ring.recover()

    def stage(self, path: str, content: str, op: str = "edit") -> dict:
        """Stage a new content snapshot for a path."""
        return self._ring.stage(path, content, op)

    def commit(self, path: str = "") -> dict:
        """Commit staged changes for a path, or all paths if empty."""
        if path:
            return self._ring.commit(path)
        return self._ring.commit_all()

    def commit_all(self) -> dict:
        """Commit all staged changes."""
        return self._ring.commit_all()

    def discard(self, path: str = "") -> dict:
        """Discard staged changes for a path, or error if no path given."""
        if path:
            return self._ring.discard(path)
        return {"success": False, "error": "path required"}

    def read(self, path: str) -> str:
        """Read the current (possibly staged) content of a path."""
        return self._ring.read(path)

    def diff(self, path: str) -> dict:
        """Return the staged diff for a path."""
        return self._ring.diff(path)

    def status(self) -> dict:
        """Return the buffer status from the ring."""
        return self._ring.status()


# ── Singleton ──

_manager: ResourceBufferManager | None = None


def get_manager() -> ResourceBufferManager:
    """Get the ResourceBufferManager singleton, creating it on first call."""
    global _manager
    if _manager is None:
        _manager = ResourceBufferManager()
    return _manager


def reset_manager() -> None:
    """Stop and clear the ResourceBufferManager singleton."""
    global _manager
    if _manager:
        _manager._ring.stop()
    _manager = None
