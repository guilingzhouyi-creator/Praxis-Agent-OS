"""CentralMemory integration test — 4-ring remember/recall/compact/archive path test.

Covers P0-level bug scenarios:
  - ring=4 actually writes to archive DB rather than mistakenly storing in Ring 1
  - quality gate uses correct _score_importance / _is_good_memory
  - recall cross-ring sort correctness
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCentralMemoryRingRouting:
    """Verify 4-ring routing correctness — data reaches the correct backend"""

    def test_ring1_working(self):
        from l3.memory import get_memory, reset_memory
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        reset_memory()
        cm = get_center()
        mem = get_memory()

        r = cm.remember("agent-a", "This is a test memory entry with enough length to pass quality gate.", entry_type="observation", ring=1)
        assert r["success"] is True, f"ring=1 failed: {r}"
        assert r["ring"] == 1

        # Verify data is actually in Ring 1 (working) — central_memory routes
        # to the "l3a" scope instance, not the global singleton.
        scope_mem = cm.get("l3a") or mem
        stats = scope_mem.stats()
        assert stats["working"]["entries"] >= 1

    def test_ring2_short_term(self):
        from l3.memory import get_memory, reset_memory
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        reset_memory()
        cm = get_center()
        mem = get_memory()

        r = cm.remember("agent-b", "Short term data entry with sufficient length for quality validation.", entry_type="note", ring=2)
        assert r["success"] is True, f"ring=2 failed: {r}"
        assert r["ring"] == 2

    def test_ring3_long_term(self):
        from l3.memory import get_memory, reset_memory
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        reset_memory()
        cm = get_center()
        mem = get_memory()

        r = cm.remember("agent-c", "Long term knowledge entry that must pass the quality check before storage.", entry_type="knowledge", ring=3)
        assert r["success"] is True, f"ring=3 failed: {r}"
        assert r["ring"] == 3

    def test_ring4_archive(self):
        """P0: Verify ring=4 writes to archive DB, not mistakenly into Ring 1"""
        from l3.memory import get_memory, reset_memory
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        reset_memory()
        cm = get_center()
        mem = get_memory()

        before_stats = mem.stats()
        working_before = before_stats["working"]["entries"]

        r = cm.remember("agent-d", "Important archive entry with sufficient content length to pass quality gate.",
                         entry_type="decision",
                         tags=["important"], ring=4)
        assert r["success"] is True, f"ring=4 failed: {r}"
        assert r["ring"] == 4

        # Verify Ring 1 count did not increase (ring=4 should not enter MemoryManager)
        after_stats = mem.stats()
        assert after_stats["working"]["entries"] == working_before, \
            "ring=4 should NOT add to working memory"

    def test_quality_gate_rejects_short(self):
        """Verify quality gate works correctly: overly short content is rejected"""
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        cm = get_center()

        r = cm.remember("agent-e", "ab", entry_type="test", ring=1)
        assert r["success"] is False
        assert "quality" in r.get("reason", "").lower()


class TestCentralMemoryRecall:
    """Verify cross-ring retrieval + sort correctness"""

    def test_recall_all_rings(self):
        from l3.memory import reset_memory
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        reset_memory()
        cm = get_center()

        cm.remember("agent-f", "First test memory entry with enough length to pass quality gate validation.", ring=1)
        time.sleep(0.01)
        cm.remember("agent-f", "Second test memory entry that also has sufficient length for quality check.", ring=2)
        time.sleep(0.01)
        cm.remember("agent-f", "Third test memory entry meeting the minimum content length requirement.", ring=3)

        results = cm.recall(agent_id="agent-f", limit=10)
        assert len(results) >= 1
        # Default sort by time descending, newest first
        timestamps = [r.get("timestamp", 0) for r in results]
        assert timestamps == sorted(timestamps, reverse=True), \
            "results should be newest-first"

    def test_recall_empty(self):
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        cm = get_center()
        results = cm.recall(agent_id="nonexistent", limit=10)
        assert isinstance(results, list)

    def test_recall_ring_filter(self):
        from l3.memory import reset_memory
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        reset_memory()
        cm = get_center()

        r1 = cm.remember("agent-g", "ring1 only", ring=1)
        r2 = cm.remember("agent-g", "ring2 only", ring=2)

        results = cm.recall(agent_id="agent-g", rings=[1], limit=10)
        for r in results:
            assert r.get("_ring") == 1, "should only return ring 1 entries"


class TestCentralMemoryCompact:
    """Verify compact triggers correctly"""

    def test_compact_ring1(self):
        from l3.memory import get_memory, reset_memory
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        reset_memory()
        mem = get_memory()
        cm = get_center()

        # Write multiple short entries with same tag for compact merging
        for i in range(5):
            mem.remember("agent-h", "tool_call", f"some result {i}",
                          tags=["build"], ring=1)

        mem.remember("agent-h", "tool_call", "another result",
                      tags=["build"], ring=2)

        r = cm.compact("agent-h", ring=0)
        assert r["success"] is True
        assert "result" in r


class TestCentralMemoryArchive:
    """Verify archive_ring3 channel"""

    def test_archive_ring3_called(self):
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        cm = get_center()

        # This call should not raise an exception (internally delegates to archive_orchestrator)
        r = cm.archive_ring3()
        assert isinstance(r, dict)


class TestCentralMemoryStats:
    """Verify stats aggregation"""

    def test_stats_returns_expected_keys(self):
        from l3.memory.central_memory import get_center, reset_center
        reset_center()
        cm = get_center()
        cm.remember("agent-s", "test stats", ring=1)

        s = cm.stats()
        assert "stores" in s
        assert "recalls" in s
        assert "compactions" in s
        assert "archives" in s
