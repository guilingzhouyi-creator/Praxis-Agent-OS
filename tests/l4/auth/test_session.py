"""Auth + UserSession tests — login, logout, session lifecycle."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestUserSession:
    def test_login(self):
        from l4.user_session import UserSessionManager
        mgr = UserSessionManager()
        r = mgr.login("user-x")
        assert r.get("success")
        assert r.get("user_id") == "user-x"

    def test_get_session(self):
        from l4.user_session import UserSessionManager
        mgr = UserSessionManager()
        r1 = mgr.login("user-y")
        sid = r1.get("session_id")
        r2 = mgr.get_session(sid)
        assert r2 is not None

    def test_logout(self):
        from l4.user_session import UserSessionManager
        mgr = UserSessionManager()
        r = mgr.login("user-z")
        sid = r.get("session_id")
        mgr.logout(sid)

    def test_active_sessions(self):
        from l4.user_session import UserSessionManager
        mgr = UserSessionManager()
        mgr.login("user-a")
        active = mgr.active_sessions()
        assert len(active) >= 1

    def test_assign_agent(self):
        from l4.user_session import UserSessionManager
        mgr = UserSessionManager()
        r = mgr.login("user-b")
        sid = r.get("session_id")
        mgr.assign_agent(sid, "agent-1")

    def test_list_sessions(self):
        from l4.user_session import UserSessionManager
        mgr = UserSessionManager()
        mgr.login("user-c")
        sessions = mgr.list_sessions()
        assert len(sessions) >= 1
