"""Memory three-ring memory system test — store/query/build-context/compact/pressure/quality/persistence"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestRemember:
    """Memory storage"""

    def test_remember_returns_id(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        eid = mem.remember("agent-a", "test", "hello world this is a test memory entry with sufficient length", ring=1)
        assert eid.startswith("mem-")

    def test_remember_ring2(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        eid = mem.remember("agent-b", "note", "important data that is long enough for quality validation", ring=2)
        assert eid.startswith("mem-")

    def test_remember_ring3(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        eid = mem.remember("agent-c", "knowledge", "long term knowledge entry that must pass the quality gate validation", ring=3)
        assert eid.startswith("mem-")

    def test_remember_rejects_short(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        r = mem.remember("agent-a", "test", "ab", ring=1)
        assert "REJECTED" in r


class TestRecall:
    """Memory query"""

    def test_recall_empty(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        results = mem.recall(agent_id="no-data", limit=10)
        assert isinstance(results, list)

    def test_recall_recent(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-x", "chat", "msg1 content that is sufficiently long to pass the quality gate", ring=1)
        mem.remember("agent-x", "chat", "msg2 content that is also long enough for quality validation check", ring=1)
        results = mem.recall(agent_id="agent-x", limit=10)
        assert len(results) == 2, f"expected 2 recalled entries, got {len(results)}: {[e.entry_type for e in results]}"

    def test_recall_by_type(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-y", "code", "def foo(): pass is a function definition in Python language", ring=1)
        mem.remember("agent-y", "note", "note text", ring=1)
        results = mem.recall(agent_id="agent-y", entry_type="code", limit=10)
        assert len(results) == 1, f"expected 1 recalled code entry, got {len(results)}: {[e.entry_type for e in results]}"
        assert results[0].entry_type == "code"

    def test_recall_by_tag(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-z", "chat", "tagged entry A with enough content to pass quality check", tags=["foo"], ring=1)
        mem.remember("agent-z", "chat", "tagged entry B with enough content to pass quality check", tags=["bar"], ring=1)
        results = mem.recall(agent_id="agent-z", tag="foo", limit=10)
        assert len(results) == 1, f"expected 1 recall by tag, got {len(results)}"
        assert "tagged entry A" in results[0].content


class TestBuildContext:
    """Context construction — build_context() with empty and populated rings."""

    def test_build_context_empty(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        ctx = mem.build_context("no-agent", max_tokens=100)
        assert "WATERMARK" in ctx

    def test_build_context_with_data(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-z", "chat", "some context data that is sufficiently long to pass the memory quality gate", ring=1)
        ctx = mem.build_context("agent-z", max_tokens=4096)
        assert "some context data" in ctx


class TestPressure:
    """Memory pressure detection"""

    def test_pressure_low(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        p = mem.pressure()
        assert "level" in p
        assert p["level"] == "low"

    def test_pressure_keys(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        p = mem.pressure()
        assert "working_pct" in p
        assert "short_pct" in p
        assert "long_pct" in p


class TestStats:
    """Statistics"""

    def test_stats_keys(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        s = mem.stats()
        assert "working" in s
        assert "short" in s
        assert "long" in s

    def test_stats_after_store(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-s", "test", "test data entry with sufficient length for memory quality gate validation", ring=1)
        s = mem.stats()
        assert s["working"]["entries"] >= 1


class TestCompact:
    """Compact operation"""

    def test_compact_empty(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        r = mem.compact(dry_run=True)
        assert "merged" in r
        assert "saved_tokens" in r

    def test_stub_compact_empty(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        r = mem.stub_compact()
        assert "stubbed" in r
        assert "saved_bytes" in r


class TestQuality:
    """Quality report"""

    def test_quality_report_empty(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        q = mem.quality_report(agent_id="no-data")
        assert q["total"] == 0

    def test_quality_report_keys(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        q = mem.quality_report()
        assert "total" in q
        assert "quality" in q
        assert "by_type" in q
        assert "token_usage" in q


class TestForget:
    """Forget"""

    def test_forget_agent(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-f", "test", "forget me", ring=1)
        r = mem.forget_agent("agent-f")
        assert "working" in r
        assert "short" in r
        assert "long" in r


class TestPersistence:
    """Persistence"""

    def test_set_persist_dir(self):
        import tempfile

        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        with tempfile.TemporaryDirectory() as d:
            mem.set_persist_dir(d)
            assert mem._persist_dir is not None

    def test_persist_roundtrip(self):
        import tempfile

        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-p", "test", "persist data entry with sufficient length for memory quality validation test", ring=2)
        with tempfile.TemporaryDirectory() as d:
            r = mem.persist(d)
            assert r["success"]
            assert r["short_written"] >= 1

    def test_search_long_term_empty(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        r = mem.search_long_term("test")
        assert isinstance(r, list)


class TestRingLayer:
    """RingLayer basic functionality"""

    def test_ring_layer_push(self):
        from l3.memory.memory_ring import RingLayer
        layer = RingLayer("test", max_tokens=1000, ttl=60)
        from l3.memory.memory_ring import MemEntry
        e = MemEntry(id="e1", agent_id="a", entry_type="t", content="x", tokens=1)
        layer.push(e)
        assert layer.count() == 1

    def test_ring_layer_clear_agent(self):
        from l3.memory.memory_ring import RingLayer
        layer = RingLayer("test", max_tokens=1000)
        from l3.memory.memory_ring import MemEntry
        layer.push(MemEntry(id="e1", agent_id="a", entry_type="t", content="x"))
        layer.push(MemEntry(id="e2", agent_id="b", entry_type="t", content="y"))
        n = layer.clear_agent("a")
        assert n >= 1
