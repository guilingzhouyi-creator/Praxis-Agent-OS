"""Buffer API handlers — /api/buffer/* endpoints."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def handle_buffer_status(body: dict | None = None) -> dict:
    from .manager import get_manager
    return get_manager().status()


def handle_buffer_commit(body: dict | None = None) -> dict:
    path = (body or {}).get("path", "")
    from .manager import get_manager
    if path:
        return get_manager().commit(path)
    return get_manager().commit_all()


def handle_buffer_discard(body: dict | None = None) -> dict:
    path = (body or {}).get("path", "")
    if not path:
        return {"success": False, "error": "path required"}
    from .manager import get_manager
    return get_manager().discard(path)


def handle_buffer_diff(body: dict | None = None) -> dict:
    path = (body or {}).get("path", "")
    if not path:
        return {"success": False, "error": "path required"}
    from .manager import get_manager
    return get_manager().diff(path)
