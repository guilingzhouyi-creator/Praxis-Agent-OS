"""L3A — SessionTaskTable tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestSessionTaskTable:
    def test_track_and_list(self):
        from l3.cell.peers.l3a.task_table import SessionTaskTable

        t = SessionTaskTable("s1")
        t.track("card-1", title="one", turn=0)
        t.track("card-2", title="two", turn=1)
        assert t.pending_count() == 2
        assert len(t.all()) == 2
        items = t.list_tasks()
        assert items[0]["card_id"] == "card-1"
        assert items[0]["status"] == "queued"

    def test_update_status(self):
        from l3.cell.peers.l3a.task_table import SessionTaskTable

        t = SessionTaskTable("s1")
        t.track("card-1", title="one", turn=0)
        t.update("card-1", "completed", {"summary": "done"})
        rec = t.get("card-1")
        assert rec.status == "completed"
        assert rec.completed_at is not None
        assert rec.result == {"summary": "done"}
        assert t.pending_count() == 0

    def test_status_filter(self):
        from l3.cell.peers.l3a.task_table import SessionTaskTable

        t = SessionTaskTable("s1")
        t.track("card-1", turn=0)
        t.track("card-2", turn=1)
        t.update("card-2", "failed", {"error": "boom"})
        done = t.list_tasks(status="failed")
        assert len(done) == 1
        assert done[0]["card_id"] == "card-2"
        assert t.list_tasks(status="queued")[0]["card_id"] == "card-1"

    def test_persist_roundtrip(self):
        from l3.cell.peers.l3a.task_table import SessionTaskTable

        t1 = SessionTaskTable("s1")
        t1.track("card-1", title="one", turn=0)
        t1.update("card-1", "completed", {"summary": "x"})
        t1.track("card-2", turn=1)
        data = t1.to_dict()
        t2 = SessionTaskTable("s2")
        t2.from_dict(data)
        assert len(t2.all()) == 2
        assert t2.get("card-1").status == "completed"
        assert t2.pending_count() == 1

    def test_remove_and_clear(self):
        from l3.cell.peers.l3a.task_table import SessionTaskTable

        t = SessionTaskTable("s1")
        t.track("card-1", turn=0)
        t.remove("card-1")
        assert len(t.all()) == 0
        t.track("card-2", turn=1)
        t.clear()
        assert t.pending_count() == 0
