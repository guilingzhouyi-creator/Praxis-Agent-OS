"""File lock tools — extracted from tools_os.py for modularity."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from kernel.params import TOOL_FILE_LOCK_TTL

logger = logging.getLogger(__name__)

_file_locks: dict[str, dict[str, Any]] = {}
_file_lock_lock = threading.Lock()
_FILE_LOCK_TTL = TOOL_FILE_LOCK_TTL


def cmd_lock_acquire(path: str, agent_id: str, ttl: int = 0) -> dict:
    ttl = ttl or _FILE_LOCK_TTL
    if not path:
        return {"success": False, "error": "path is required"}
    resolved = os.path.abspath(path)
    now = time.time()
    with _file_lock_lock:
        existing = _file_locks.get(resolved)
        if existing:
            if now - existing["acquired_at"] < existing.get("ttl", _FILE_LOCK_TTL):
                return {"success": False, "error": f"locked by {existing['agent_id']}",
                        "data": {"locked_by": existing["agent_id"], "since": existing["acquired_at"]}}
            logger.info("[Lock] %s lock on %s expired, reassigning to %s", existing["agent_id"], resolved, agent_id)
        _file_locks[resolved] = {"agent_id": agent_id, "acquired_at": now, "ttl": ttl}
    return {"success": True, "data": {"path": resolved, "acquired": True, "ttl": ttl}}


def cmd_lock_release(path: str, agent_id: str) -> dict:
    if not path:
        return {"success": False, "error": "path is required"}
    resolved = os.path.abspath(path)
    with _file_lock_lock:
        existing = _file_locks.get(resolved)
        if not existing:
            return {"success": True, "data": {"path": resolved, "was_locked": False}}
        if existing["agent_id"] != agent_id:
            return {"success": False, "error": f"locked by {existing['agent_id']}, not you"}
        del _file_locks[resolved]
    return {"success": True, "data": {"path": resolved, "released": True}}


def cmd_lock_status() -> dict:
    now = time.time()
    with _file_lock_lock:
        locks = {}
        for path, info in list(_file_locks.items()):
            expired = now - info["acquired_at"] > info.get("ttl", _FILE_LOCK_TTL)
            if expired:
                del _file_locks[path]
                continue
            locks[path] = {"locked_by": info["agent_id"], "since": info["acquired_at"],
                           "ttl_remaining": max(0, info["ttl"] - (now - info["acquired_at"]))}
        return {"success": True, "data": {"locks": locks, "count": len(locks)}}
