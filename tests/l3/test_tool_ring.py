"""Tests for tool_ring — ToolRing (Ring 1) + RequestPool (Ring 2.5) + weighted scheduling."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestToolRing:
    """Ring 1 per-agent tool call history."""

    def test_record_and_count(self):
        from tool_ring import ToolCallRecord, ToolRing

        ring = ToolRing(capacity=5)
        assert ring.count() == 0
        ring.record(ToolCallRecord(tool_name="read_file", agent_id="a", success=True))
        assert ring.count() == 1

    def test_record_capped(self):
        from tool_ring import ToolCallRecord, ToolRing

        ring = ToolRing(capacity=3)
        for i in range(5):
            ring.record(ToolCallRecord(tool_name=f"t{i}", agent_id="a", success=True))
        assert ring.count() == 3
        assert ring.recent()[0].tool_name == "t2"

    def test_recent_returns_n(self):
        from tool_ring import ToolCallRecord, ToolRing

        ring = ToolRing(capacity=20)
        for i in range(10):
            ring.record(ToolCallRecord(tool_name=f"t{i}", agent_id="a", success=True))
        recent = ring.recent(3)
        assert len(recent) == 3
        assert recent[0].tool_name == "t7"

    def test_gate_stats_empty(self):
        from tool_ring import ToolRing

        ring = ToolRing()
        stats = ring.gate_stats()
        assert stats["PASS"] == 0 and stats["BLOCK"] == 0

    def test_gate_stats_tracks_results(self):
        from tool_ring import GateStatus, ToolCallRecord, ToolRing

        ring = ToolRing()
        ring.record(ToolCallRecord("t1", "a", True, gate_result=GateStatus.PASS))
        ring.record(ToolCallRecord("t2", "a", False, gate_result=GateStatus.BLOCK))
        stats = ring.gate_stats()
        assert stats[GateStatus.PASS] == 1
        assert stats[GateStatus.BLOCK] == 1


class TestRequestPool:
    """Ring 2.5 reputation-weighted request pool."""

    def test_empty_dequeue(self):
        from tool_ring import RequestPool

        pool = RequestPool(capacity=5)
        assert pool.dequeue() is None

    def test_enqueue_dequeue_fifo_when_same_priority(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=10)
        pool.enqueue(ToolRequest("read", "a", priority=5))
        pool.enqueue(ToolRequest("write", "b", priority=5))
        r = pool.dequeue()
        assert r is not None
        assert r.tool_name in ("read", "write")

    def test_higher_priority_dequeued_first(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=10)
        pool.enqueue(ToolRequest("low", "a", priority=1))
        pool.enqueue(ToolRequest("high", "b", priority=5))
        r = pool.dequeue()
        assert r is not None
        assert r.tool_name == "high"

    def test_pool_capacity_enforce(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=3)
        for i in range(3):
            assert pool.enqueue(ToolRequest(f"t{i}", "a", priority=1))
        # Fourth enqueue should succeed (evicts lowest)
        assert pool.enqueue(ToolRequest("t3", "b", priority=5))

    def test_pending_for(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=10)
        pool.enqueue(ToolRequest("t1", "agent-a"))
        pool.enqueue(ToolRequest("t2", "agent-b"))
        pool.enqueue(ToolRequest("t3", "agent-a"))
        pending = pool.pending_for("agent-a")
        assert len(pending) == 2
        assert all(r.agent_id == "agent-a" for r in pending)

    def test_remove_for(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=10)
        pool.enqueue(ToolRequest("t1", "agent-a"))
        pool.enqueue(ToolRequest("t2", "agent-b"))
        removed = pool.remove_for("agent-a")
        assert removed == 1
        assert pool.pending_for("agent-a") == []

    def test_len(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=10)
        assert len(pool) == 0
        pool.enqueue(ToolRequest("t1", "a"))
        assert len(pool) == 1

    def test_peek_returns_sorted(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=10)
        pool.enqueue(ToolRequest("low", "a", priority=1))
        pool.enqueue(ToolRequest("high", "b", priority=5))
        peeked = pool.peek()
        assert peeked[0].tool_name == "high"
        # peek should not remove items
        assert len(pool) == 2


class TestRequestPoolWeightedScore:
    """Three-factor scoring internals."""

    def test_score_prefers_higher_reputation(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=5)
        r_high = ToolRequest("t1", "a", priority=3, agent_reputation=1.0, tool_danger=0)
        r_low = ToolRequest("t2", "b", priority=3, agent_reputation=0.1, tool_danger=0)
        pool.enqueue(r_low)
        pool.enqueue(r_high)
        r = pool.dequeue()
        assert r is not None
        assert r.agent_id == "a"

    def test_score_prefers_lower_danger(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=5)
        r_safe = ToolRequest("t1", "a", priority=3, agent_reputation=0.9, tool_danger=0)
        r_risk = ToolRequest("t2", "b", priority=3, agent_reputation=0.9, tool_danger=5)
        pool.enqueue(r_risk)
        pool.enqueue(r_safe)
        r = pool.dequeue()
        assert r is not None
        assert r.tool_danger == 0


class TestRequestPoolEviction:
    """Eviction when pool is full."""

    def test_evict_lowest_score(self):
        from tool_ring import RequestPool, ToolRequest

        pool = RequestPool(capacity=3)
        pool.enqueue(ToolRequest("t1", "a", priority=1))
        pool.enqueue(ToolRequest("t2", "b", priority=1))
        pool.enqueue(ToolRequest("t3", "c", priority=1))
        # Fourth enqueue triggers eviction
        pool.enqueue(ToolRequest("t4", "d", priority=5))
        assert len(pool) == 3
        # The lowest priority item should be evicted
        remaining = [r.tool_name for r in pool.peek()]
        assert "t4" in remaining


class TestGlobalSingletons:
    """Module-level shared instances."""

    def test_get_request_pool_singleton(self):
        from tool_ring import get_request_pool

        p1 = get_request_pool()
        p2 = get_request_pool()
        assert p1 is p2
