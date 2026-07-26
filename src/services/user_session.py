"""User Session — login/logout/session management for Agent OS.

Manages human user sessions, agent assignment, and session lifecycle.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from services._base import BaseService
from kernel.params.system import SESSION_TIMEOUT

logger = logging.getLogger(__name__)


@dataclass
class UserSession:
    id: str
    user_id: str
    agent_id: str = ""
    cell_id: str = ""
    status: str = "active"  # active | idle | closed
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class UserSessionManager(BaseService):
    """OS-level user session management."""

    def __init__(self):
        super().__init__("user_session")
        self._sessions: dict[str, UserSession] = {}
        self._lock = threading.RLock()
        self._next_id = 0

    def _on_start(self) -> dict:
        return {"success": True}

    def _on_stop(self) -> dict:
        with self._lock:
            self._sessions.clear()
        return {"success": True}

    def login(self, user_id: str, agent_id: str = "",
              cell_id: str = "", metadata: dict | None = None) -> dict:
        """Create a new user session."""
        sid = f"session-{self._next_id}"
        self._next_id += 1
        session = UserSession(
            id=sid, user_id=user_id, agent_id=agent_id,
            cell_id=cell_id, metadata=metadata or {},
        )
        with self._lock:
            self._sessions[sid] = session
        logger.info("session created: %s for %s", sid, user_id)
        return {"success": True, "session_id": sid, "user_id": user_id,
                "agent_id": agent_id, "status": "active"}

    def logout(self, session_id: str) -> dict:
        """Close a user session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"success": False, "error": "session not found"}
            session.status = "closed"
        logger.info("session closed: %s", session_id)
        return {"success": True, "session_id": session_id, "status": "closed"}

    def get_session(self, session_id: str) -> dict:
        """Get session details."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"success": False, "error": "session not found"}
            return {"success": True, "session": {
                "id": session.id, "user_id": session.user_id,
                "agent_id": session.agent_id, "cell_id": session.cell_id,
                "status": session.status, "created_at": session.created_at,
                "last_active": session.last_active,
            }}

    def list_sessions(self, user_id: str | None = None,
                      status: str | None = None) -> dict:
        """List all sessions, optionally filtered."""
        with self._lock:
            sessions = list(self._sessions.values())
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        if status:
            sessions = [s for s in sessions if s.status == status]
        return {"success": True, "sessions": [
            {"id": s.id, "user_id": s.user_id, "agent_id": s.agent_id,
             "status": s.status, "created_at": s.created_at}
            for s in sessions
        ], "count": len(sessions)}

    def active_sessions(self) -> list[str]:
        """Get list of active session IDs."""
        with self._lock:
            return [s.id for s in self._sessions.values() if s.status == "active"]

    def touch(self, session_id: str) -> dict:
        """Update last_active timestamp."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"success": False, "error": "session not found"}
            session.last_active = time.time()
        return {"success": True}

    def assign_agent(self, session_id: str, agent_id: str) -> dict:
        """Assign an agent to a session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"success": False, "error": "session not found"}
            session.agent_id = agent_id
        return {"success": True, "session_id": session_id, "agent_id": agent_id}

    def stats(self) -> dict:
        with self._lock:
            active = sum(1 for s in self._sessions.values() if s.status == "active")
            return {
                "total": len(self._sessions),
                "active": active,
                "closed": len(self._sessions) - active,
            }


_service: UserSessionManager | None = None


def get_service() -> UserSessionManager:
    global _service
    if _service is None:
        _service = UserSessionManager()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None