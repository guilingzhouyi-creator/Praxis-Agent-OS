"""Buffer API handlers — /api/buffer/* endpoints."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def handle_buffer_status(body: dict | None = None) -> dict:
    """Handle /api/buffer/status — return the buffer manager status."""
    from .manager import get_manager
    return get_manager().status()


def handle_buffer_commit(body: dict | None = None) -> dict:
    """Handle /api/buffer/commit — commit a staged path or all paths."""
    path = (body or {}).get("path", "")
    from .manager import get_manager
    if path:
        return get_manager().commit(path)
    return get_manager().commit_all()


def handle_buffer_discard(body: dict | None = None) -> dict:
    """Handle /api/buffer/discard — discard a staged path's changes."""
    path = (body or {}).get("path", "")
    if not path:
        return {"success": False, "error": "path required"}
    from .manager import get_manager
    return get_manager().discard(path)


def handle_buffer_diff(body: dict | None = None) -> dict:
    """Handle /api/buffer/diff — return the staged diff for a path."""
    path = (body or {}).get("path", "")
    if not path:
        return {"success": False, "error": "path required"}
    from .manager import get_manager
    return get_manager().diff(path)
