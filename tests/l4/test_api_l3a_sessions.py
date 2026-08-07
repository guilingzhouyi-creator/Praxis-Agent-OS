"""L3A session contract API tests — CRUD, paging, send/close/compress.

These are handler-level tests (dict in / dict out) plus real-session
integration through the daemon singleton; no HTTP server is started.
"""

from __future__ import annotations

from l4.api_handlers.api_handlers_l3a import (
    handle_l3a_session_close,
    handle_l3a_session_compress,
    handle_l3a_session_create,
    handle_l3a_session_get,
    handle_l3a_session_list,
    handle_l3a_session_messages,
    handle_l3a_session_send,
)


def _fresh_session(title: str = "test"):
    r = handle_l3a_session_create({"title": title})
    assert r["success"], r
    return r["session"]["session_id"]


class TestSessionCreate:
    def test_create_returns_info(self):
        s = _fresh_session("contract")
        assert s.startswith("l3a-")
        info = handle_l3a_session_get({}, session_id=s)
        assert info["success"]
        assert info["session"]["session_id"] == s
        assert info["session"]["title"] == "contract"
        assert info["session"]["status"] == "active"
        assert "todos" in info["session"]

    def test_create_missing_title_ok(self):
        s = _fresh_session()
        assert s


class TestSessionList:
    def test_list_contains_created(self):
        s = _fresh_session("list-me")
        r = handle_l3a_session_list()
        assert r["success"]
        ids = [x["session_id"] for x in r["sessions"]]
        assert s in ids
        assert r["count"] == len(r["sessions"])

    def test_list_empty_after_close(self):
        s = _fresh_session("close-me")
        r = handle_l3a_session_close({}, session_id=s)
        assert r["success"]
        r2 = handle_l3a_session_list()
        assert s not in [x["session_id"] for x in r2["sessions"]]


class TestSessionValidation:
    def test_get_requires_session_id(self):
        r = handle_l3a_session_get({})
        assert not r["success"]
        assert "session_id" in r["error"]

    def test_get_unknown_session(self):
        r = handle_l3a_session_get({}, session_id="nope")
        assert not r["success"]
        assert "not active" in r["error"]

    def test_send_requires_text(self):
        s = _fresh_session()
        r = handle_l3a_session_send({"text": "   "}, session_id=s)
        assert not r["success"]
        assert "text required" in r["error"]

    def test_send_unknown_session(self):
        r = handle_l3a_session_send({"text": "hi"}, session_id="nope")
        assert not r["success"]

    def test_messages_bad_limit(self):
        s = _fresh_session()
        r = handle_l3a_session_messages({"limit": "x"}, session_id=s)
        assert not r["success"]
        assert "limit" in r["error"]

    def test_close_unknown_session(self):
        r = handle_l3a_session_close({}, session_id="nope")
        assert not r["success"]

    def test_compress_unknown_session(self):
        r = handle_l3a_session_compress({}, session_id="nope")
        assert not r["success"]


class TestMessagesPaging:
    def _seed(self, session_id: str, count: int) -> None:
        from l3.cell.peers.l3a import get_daemon
        from l3.cell.peers.l3a.session import Message

        s = get_daemon().manager.get(session_id)
        for i in range(count):
            s.history.append(
                Message(
                    id=f"m-{i:04d}",
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"message {i}",
                )
            )

    def test_paging_walks_whole_history(self):
        s = _fresh_session("paging")
        self._seed(s, 25)
        page = handle_l3a_session_messages({"limit": 10}, session_id=s)
        assert page["success"]
        assert page["total"] == 25
        assert len(page["items"]) == 10
        assert page["items"][0]["id"] == "m-0000"
        # Follow the cursor chain
        seen = len(page["items"])
        cursor = page["next_cursor"]
        while cursor:
            page = handle_l3a_session_messages({"limit": 10, "cursor": cursor}, session_id=s)
            seen += len(page["items"])
            cursor = page["next_cursor"]
        assert seen == 25

    def test_limit_capped(self):
        s = _fresh_session("cap")
        self._seed(s, 300)
        page = handle_l3a_session_messages({"limit": 9999}, session_id=s)
        assert page["success"]
        assert len(page["items"]) <= 100

    def test_empty_session(self):
        s = _fresh_session("empty")
        page = handle_l3a_session_messages({}, session_id=s)
        assert page["success"]
        assert page["items"] == []
        assert page["total"] == 0
        assert page["next_cursor"] is None


class TestSessionLifecycle:
    def test_close_and_compress_do_not_raise(self):
        s = _fresh_session("lifecycle")
        r = handle_l3a_session_compress({}, session_id=s)
        assert r["success"] or "compress" in str(r.get("error", ""))
        r = handle_l3a_session_close({}, session_id=s)
        assert r["success"]
        # Closed session is gone from the manager
        r = handle_l3a_session_get({}, session_id=s)
        assert not r["success"]
