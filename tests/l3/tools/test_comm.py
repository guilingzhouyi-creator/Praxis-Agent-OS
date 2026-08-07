"""Communication tool tests — context-aware ask_user/confirm (L3A awaiting vs headless degrade)."""

from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestAskUserDegrade:
    """Headless cell peer context: no L3A session, must not block."""

    def test_requires_question(self):
        from l3.tools._comm import ask_user

        r = ask_user({}, "agent-a")
        assert r["success"] is False

    def test_degrade_mode_notify_only(self):
        from l3.tools._comm import ask_user

        with mock.patch("l3.tools._comm._log_pending_question") as log:
            r = ask_user({"question": "Target platform?"}, "agent-a")
        assert r["success"] is True
        assert r["mode"] == "notify_only"
        assert r["pending"] is True
        assert "Do NOT wait" in r["instruction"]
        log.assert_called_once()

    def test_confirm_degrade(self):
        from l3.tools._comm import confirm

        with mock.patch("l3.tools._comm._log_pending_question"):
            r = confirm({"message": "Proceed?"}, "agent-b")
        assert r["success"] is True
        assert r["mode"] == "notify_only"
        assert r["pending"] is True


class TestAskUserL3A:
    """L3A session context: routes into the awaiting flow."""

    def _make_l3a_session(self):
        from l3.cell.peers.l3a.session import Session

        return Session(session_id="l3a-comm", title="t")

    def test_routes_to_active_l3a_session(self):
        from l3.cell.peers.l3a import get_daemon
        from l3.cell.peers.l3a.session import SessionManager
        from l3.tools._comm import ask_user

        s = self._make_l3a_session()
        d = get_daemon()
        mgr = SessionManager()
        with mgr._lock:
            mgr._sessions[s.id] = s
        with mock.patch.object(d, "manager", mgr):
            r = ask_user({"question": "Deploy target?"}, "l3a")
        assert r["success"] is True
        assert r["awaiting_input"] is True
        assert r["asked"] == 1
        assert s._ask is not None
        assert s._ask.status == "awaiting"
        assert s._ask.questions[0].question == "Deploy target?"

    def test_route_with_options(self):
        from l3.cell.peers.l3a import get_daemon
        from l3.cell.peers.l3a.session import SessionManager
        from l3.tools._comm import ask_user

        s = self._make_l3a_session()
        mgr = SessionManager()
        with mgr._lock:
            mgr._sessions[s.id] = s
        with mock.patch.object(get_daemon(), "manager", mgr):
            r = ask_user({"question": "Env?", "options": ["dev", "prod"]}, "l3a")
        assert r["success"] is True
        assert s._ask.questions[0].options == ["dev", "prod"]

    def test_non_l3a_agent_not_routed(self):
        from l3.tools._comm import ask_user

        with mock.patch("l3.tools._comm._log_pending_question") as log:
            r = ask_user({"question": "Q?"}, "agent-c")
        assert r["mode"] == "notify_only"
        assert r.get("awaiting_input") is None
        log.assert_called_once()

    def test_confirm_routes_to_l3a(self):
        from l3.cell.peers.l3a import get_daemon
        from l3.cell.peers.l3a.session import SessionManager
        from l3.tools._comm import confirm

        s = self._make_l3a_session()
        mgr = SessionManager()
        with mgr._lock:
            mgr._sessions[s.id] = s
        with mock.patch.object(get_daemon(), "manager", mgr):
            r = confirm({"message": "Approve the plan?"}, "l3a")
        assert r["success"] is True
        assert r["awaiting_input"] is True
        assert s._ask.questions[0].question == "Approve the plan?"

    def test_no_active_session_falls_back_to_degrade(self):
        from l3.cell.peers.l3a import get_daemon
        from l3.cell.peers.l3a.session import SessionManager
        from l3.tools._comm import ask_user

        mgr = SessionManager()
        with mock.patch.object(get_daemon(), "manager", mgr):
            with mock.patch("l3.tools._comm._log_pending_question"):
                r = ask_user({"question": "Q?"}, "l3a")
        assert r["mode"] == "notify_only"


class TestPendingQuestions:
    def test_pending_questions_queries_memory(self):
        from l3.tools._comm import pending_questions

        with mock.patch("l3.memory.central_memory.get_l3a_memory") as gm:
            gm.return_value.recall.return_value = [
                mock.Mock(content='{"agent_id": "agent-a", "question": "Q?", "asked_at": 1}'),
            ]
            items = pending_questions("agent-a")
        assert len(items) == 1
        assert items[0]["question"] == "Q?"

    def test_pending_questions_survives_memory_failure(self):
        from l3.tools._comm import pending_questions

        with mock.patch("l3.memory.central_memory.get_l3a_memory", side_effect=Exception("boom")):
            assert pending_questions() == []


class TestOtherComm:
    def test_notify(self):
        from l3.tools._comm import notify

        with mock.patch("l4.notify.send_notification"):
            r = notify({"message": "hi"}, "agent-a")
        assert r["success"] is True

    def test_user_delete(self):
        from l3.tools._comm import user_delete

        r = user_delete({"user_id": "u1"}, "agent-a")
        assert r["success"] is True
        assert "approval gate" in r["message"]
