"""Tests for L3A session management — Session, SessionHistory, Inbox."""

from __future__ import annotations


class TestSessionHistory:
    _MSG_KW = {"id": "m1"}

    def test_append_and_count(self):
        from l3.cell.peers.l3a.session import Message, SessionHistory

        h = SessionHistory()
        assert h.count() == 0
        h.append(Message(id="m1", role="user", content="hello"))
        assert h.count() == 1

    def test_extend_and_project(self):
        from l3.cell.peers.l3a.session import Message, SessionHistory

        h = SessionHistory()
        h.extend(
            [
                Message(id="m1", role="user", content="hi", created_at=1.0),
                Message(id="m2", role="assistant", content="hello", created_at=2.0),
            ]
        )
        assert h.count() == 2
        projected = h.project(max_tokens=32000)
        assert len(projected) == 2

    def test_project_truncation(self):
        from l3.cell.peers.l3a.session import Message, SessionHistory

        h = SessionHistory()
        for i in range(100):
            h.append(Message(id=f"m{i}", role="user", content=f"msg{i}", created_at=float(i)))
        projected = h.project(max_tokens=1)
        assert len(projected) < 100

    def test_to_context_trail(self):
        from l3.cell.peers.l3a.session import Message, SessionHistory

        h = SessionHistory()
        h.append(Message(id="m1", role="user", content="test", created_at=1.0))
        trail = h.to_context_trail()
        assert len(trail) == 1
        assert trail[0]["role"] == "user"

    def test_messages_page_pagination(self):
        from l3.cell.peers.l3a.session import Message, SessionHistory

        h = SessionHistory()
        for i in range(20):
            h.append(Message(id=f"m{i}", role="user", content=f"msg{i}", created_at=float(i)))
        page = h.messages_page(limit=5)
        assert len(page.items) == 5
        assert page.total == 20
        assert page.cursor is not None

    def test_clear(self):
        from l3.cell.peers.l3a.session import Message, SessionHistory

        h = SessionHistory()
        h.append(Message(id="m1", role="user", content="test"))
        h.clear()
        assert h.count() == 0


class TestSession:
    def test_create_and_info(self):
        from l3.cell.peers.l3a.session import Session

        s = Session.create(title="test-session")
        info = s.info()
        assert info["title"] == "test-session"
        assert info["status"] == "active"
        assert info["session_id"] is not None

    def test_close(self):
        from l3.cell.peers.l3a.session import Session

        s = Session.create(title="close-test")
        r = s.close()
        assert r["success"] is True

    def test_messages(self):
        from l3.cell.peers.l3a.session import Session

        s = Session.create(title="msg-test")
        page = s.messages()
        assert page.total == 0
        assert len(page.items) == 0


class TestInbox:
    def test_admit_and_promote(self):
        from l3.cell.peers.l3a.inbox import PromptInbox

        inbox = PromptInbox(session_id="test-sess")
        a = inbox.admit("hello", mode="steer")
        assert a.status == "pending"
        promoted = inbox.promote()
        assert promoted is not None
        assert promoted.status == "promoted"

    def test_peek(self):
        from l3.cell.peers.l3a.inbox import PromptInbox

        inbox = PromptInbox(session_id="test-sess")
        assert inbox.peek() is None
        inbox.admit("hello")
        assert inbox.peek() is not None

    def test_pending_count(self):
        from l3.cell.peers.l3a.inbox import PromptInbox

        inbox = PromptInbox(session_id="test-sess")
        assert inbox.pending_count() == 0
        inbox.admit("task1")
        inbox.admit("task2")
        assert inbox.pending_count() == 2
        inbox.promote()
        assert inbox.pending_count() == 1

    def test_cancel(self):
        from l3.cell.peers.l3a.inbox import PromptInbox

        inbox = PromptInbox(session_id="test-sess")
        a = inbox.admit("cancel-me")
        assert inbox.cancel(a.id) is True
        assert inbox.pending_count() == 0

    def test_cancel_nonexistent(self):
        from l3.cell.peers.l3a.inbox import PromptInbox

        inbox = PromptInbox(session_id="test-sess")
        assert inbox.cancel("nonexistent") is False
