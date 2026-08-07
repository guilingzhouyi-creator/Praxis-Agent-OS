"""Tests: l1.kernel.persist — append-only SQLite event store."""

from __future__ import annotations

import os
import tempfile

import pytest

from l1.kernel.persist import (
    append,
    append_many,
    count,
    last_seq,
    query,
    restore,
    save,
)


@pytest.fixture(autouse=True)
def _reset_persist():
    """Reset persist module globals before each test and use a temp DB."""
    import l1.kernel.persist as _p

    # Redirect DB path to a temporary file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        _p._DB_PATH = tmp.name
    # Close & reset connections
    if _p._DB is not None:
        _p._DB.close()
        _p._DB = None
    for c in _p._READ_DBS:
        c.close()
    _p._READ_DBS = []
    # Ensure the database and events table exist before any test runs
    # so query / count work without a prior append call.
    _p._get_write_db()
    yield
    # Cleanup temp file
    from contextlib import suppress

    with suppress(OSError):
        os.unlink(tmp.name)


class TestAppend:
    def test_append_returns_seq(self):
        seq = append("test.event", {"key": "value"})
        assert isinstance(seq, int)
        assert seq > 0

    def test_append_increments(self):
        s1 = append("event.a", {"n": 1})
        s2 = append("event.a", {"n": 2})
        assert s2 == s1 + 1

    def test_append_none_payload(self):
        seq = append("event.no_payload")
        assert seq > 0


class TestAppendMany:
    def test_append_many_returns_seqs(self):
        seqs = append_many(
            [
                ("evt.1", {"x": 1}),
                ("evt.2", {"x": 2}),
                ("evt.3", {"x": 3}),
            ]
        )
        assert len(seqs) == 3
        assert seqs[2] == seqs[0] + 2

    def test_append_many_empty(self):
        assert append_many([]) == []


class TestQuery:
    def test_query_all(self):
        append("alpha", {"v": 1})
        append("beta", {"v": 2})
        rows = query()
        assert len(rows) == 2
        assert rows[0]["event"] == "alpha"
        assert rows[1]["event"] == "beta"

    def test_query_by_type(self):
        append("type.a", {"v": 1})
        append("type.b", {"v": 2})
        append("type.a", {"v": 3})
        rows = query(event_type="type.a")
        assert len(rows) == 2
        assert all(r["event"] == "type.a" for r in rows)

    def test_query_after_seq(self):
        append("e.1")
        s = append("e.2")
        append("e.3")
        rows = query(after_seq=s)
        assert len(rows) == 1
        assert rows[0]["event"] == "e.3"

    def test_query_limit(self):
        for i in range(10):
            append(f"e.{i}")
        rows = query(limit=3)
        assert len(rows) == 3

    def test_query_payload_roundtrip(self):
        payload = {"name": "test", "count": 42, "nested": {"a": [1, 2]}}
        append("complex", payload)
        rows = query()
        assert rows[0]["payload"] == payload


class TestCount:
    def test_count_all(self):
        append("a")
        append("b")
        assert count() == 2

    def test_count_by_type(self):
        append("x")
        append("y")
        append("x")
        assert count("x") == 2
        assert count("y") == 1

    def test_count_empty(self):
        assert count() == 0


class TestLastSeq:
    def test_last_seq_initial(self):
        assert last_seq() == 0

    def test_last_seq_after_append(self):
        append("e")
        assert last_seq() == 1

    def test_last_seq_after_multiple(self):
        for i in range(5):
            append(f"e.{i}")
        assert last_seq() == 5


class TestSaveRestore:
    """Verify save() / restore() cycle works — append audit records then replay."""

    def test_save_no_audit(self):
        """save() with empty audit log should succeed without errors."""
        result = save()
        assert result["success"] is True
        assert isinstance(result["events_appended"], int)

    def test_save_and_restore(self):
        """Write audit records via save(), then verify restore() replays them."""
        # The real save() dumps the kernel audit log, which is empty in tests.
        # We directly append audit events and verify replay works.
        append("audit.record", {"op": "test", "agent_id": "tester", "success": True})
        append("audit.record", {"op": "test2", "agent_id": "tester", "success": True})
        result = restore()
        assert result["success"] is True
        assert result["events"] >= 2
        assert result["audit"] >= 2
