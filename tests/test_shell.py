"""Tests for shell service — session management and terminal operations."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestTerminalSession:
    def test_session_dataclass(self):
        from services.shell_session import TerminalSession
        sess = TerminalSession(id="test-session", pid=12345)
        assert sess.id == "test-session"
        assert sess.pid == 12345
        assert not sess.is_alive()

    def test_kill_no_process(self):
        from services.shell_session import TerminalSession
        sess = TerminalSession(id="no-proc", pid=0)
        sess.kill()


class TestTerminalManager:
    def test_create_and_list(self):
        from services.shell_session import get_manager, reset_manager
        reset_manager()
        mgr = get_manager()
        r = mgr.create(cwd=".")
        assert r.get("success"), f"create failed: {r}"
        assert "id" in r

    def test_get_session(self):
        from services.shell_session import get_manager, reset_manager
        reset_manager()
        mgr = get_manager()
        r = mgr.create()
        sid = r["id"]
        sess = mgr.get(sid)
        assert sess is not None
        assert sess.id == sid

    def test_get_manager_singleton(self):
        from services.shell_session import get_manager, reset_manager
        reset_manager()
        m1 = get_manager()
        m2 = get_manager()
        assert m1 is m2

    def test_shell_helpers_import(self):
        from services.shell import direct_session, start_repl
        assert callable(direct_session)
        assert callable(start_repl)
