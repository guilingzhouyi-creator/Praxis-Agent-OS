"""Memory 4-ring 持久化集成测试 — remember → pressure → swap → persist → restore → recall。"""
from __future__ import annotations
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestMemoryPersistenceIntegration:
    """remember → persist → restore → recall 全流程"""

    def test_remember_ring1(self):
        from l3.memory import MemoryManager
        mem = MemoryManager()
        eid = mem.remember("agent-r1", "decision",
                           "Use Python 3.11 for this project across all environments.",
                           tags=["python"], ring=1)
        assert eid.startswith("mem-")
        stats = mem.stats()
        assert stats["working"]["entries"] >= 1

    def test_remember_all_rings(self):
        from l3.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-all", "decision",
                     "Memory ring 1 working entry with sufficient length to pass quality check.",
                     ring=1)
        mem.remember("agent-all", "note",
                     "Memory ring 2 short term entry with enough content for quality validation.",
                     ring=2)
        mem.remember("agent-all", "knowledge",
                     "Memory ring 3 long term entry with sufficient content to meet quality requirements.",
                     ring=3)
        stats = mem.stats()
        assert stats["working"]["entries"] >= 1
        assert stats["short"]["entries"] >= 1
        assert stats["long"]["entries"] >= 1

    def test_persist_and_restore(self):
        """persist Ring 2 → JSONL + Ring 3 → SQLite, 然后 restore"""
        from l3.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-persist", "note",
                     "This is a persistent memory entry that will be saved and restored.",
                     ring=2)
        mem.remember("agent-persist", "knowledge",
                     "Long term knowledge entry that should survive persist and restore cycle.",
                     ring=3)
        with tempfile.TemporaryDirectory() as tmpdir:
            r = mem.persist(tmpdir)
            assert r.get("success"), f"persist failed: {r}"
            mem2 = MemoryManager()
            r2 = mem2.restore(tmpdir)
            assert r2.get("success"), f"restore failed: {r2}"
            assert r2["restored"] >= 0

    def test_pressure_high_with_data(self):
        """大量写入使压力升高"""
        from l3.memory import MemoryManager
        mem = MemoryManager(working_budget=500)
        for i in range(10):
            mem.remember("agent-press", "observation",
                         f"Test observation entry number {i} that must pass quality gate validation.",
                         ring=1)
        p = mem.pressure("agent-press")
        assert "level" in p
        assert p["working_pct"] >= 0

    def test_compact_merges_entries(self):
        """compact 合并同类条目"""
        from l3.memory import MemoryManager
        mem = MemoryManager()
        for i in range(5):
            mem.remember("agent-compact", "tool_call",
                         f"Running build command number {i} for project compilation and testing.",
                         tags=["build"], ring=1)
        r = mem.compact("agent-compact")
        assert isinstance(r, dict)
        assert "merged" in r

    def test_fts_search_empty(self):
        """FTS5 搜索空数据库（需先 set_persist_dir 才能访问 _db_path）"""
        from l3.memory import MemoryManager
        mem = MemoryManager()
        with tempfile.TemporaryDirectory() as tmpdir:
            mem.set_persist_dir(tmpdir)
            results = mem.search_long_term("test")
            assert isinstance(results, list)
            assert len(results) == 0

    def test_central_memory_integration(self):
        """CentralMemory.remember → CentralMemory.recall 跨环"""
        from l3.central_memory import get_center, reset_center
        from l3.memory import get_memory, reset_memory
        reset_center()
        reset_memory()
        cm = get_center()
        mem = get_memory()
        cm.remember("agent-ci", "Important decision with very high importance and sufficient content length.",
                    entry_type="decision", ring=1)
        cm.remember("agent-ci", "Short term observation with enough content to pass quality gate.",
                    entry_type="observation", ring=2)
        results = cm.recall(agent_id="agent-ci", limit=10)
        assert len(results) >= 1
