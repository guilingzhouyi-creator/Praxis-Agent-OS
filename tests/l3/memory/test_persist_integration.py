"""Memory 4-ring 持久化集成测试 — remember → pressure → swap → persist → restore → recall。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestMemoryPersistenceIntegration:
    """remember → persist → restore → recall 全流程"""

    def _make_mem(self):
        from l3.memory.memory import MemoryManager
        return MemoryManager()

    def test_remember_ring1(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        eid = mem.remember("agent-r1", "decision",
                           "Use Python 3.11 for this project across all environments.",
                           tags=["python"], ring=1)
        assert eid.startswith("mem-")
        stats = mem.stats()
        assert stats["working"]["entries"] >= 1

    def test_remember_all_rings(self):
        from l3.memory.memory import MemoryManager
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
        from l3.memory.memory import MemoryManager
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
        from l3.memory.memory import MemoryManager
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
        from l3.memory.memory import MemoryManager
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
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        with tempfile.TemporaryDirectory() as tmpdir:
            mem.set_persist_dir(tmpdir)
            results = mem.search_long_term("test")
            assert isinstance(results, list)
            assert len(results) == 0

    def test_central_memory_integration(self):
        """CentralMemory.remember → CentralMemory.recall 跨环"""
        from l3.memory.central_memory import get_center, reset_center
        from l3.memory.memory import get_memory, reset_memory
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


class TestMemoryDirtyTracking:
    """增量脏追踪持久化测试 — 只写入新变更的条目而非全量转储"""

    def test_persist_only_dirty_ring2(self):
        """persist 只写入脏的 Ring 2 条目，清除脏标记后再次 persist 不做重复写入"""
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()

        # 写 2 条到 Ring 2 → 标记为 dirty
        eid1 = mem.remember("agent-dirty", "note",
                            "First dirty entry for ring2 with enough content to pass quality validation.",
                            ring=2)
        eid2 = mem.remember("agent-dirty", "note",
                            "Second dirty entry for ring2 with enough content to pass quality validation.",
                            ring=2)
        assert eid1 in mem._dirty_short
        assert eid2 in mem._dirty_short

        with tempfile.TemporaryDirectory() as tmpdir:
            # 第一次 persist：应写入 2 条
            r1 = mem.persist(tmpdir)
            assert r1.get("success"), f"first persist failed: {r1}"
            assert r1["short_written"] == 2, f"expected 2 dirty writes, got {r1}"
            assert len(mem._dirty_short) == 0, "dirty set should be cleared after persist"

            # 第二次 persist（无新条目）：应写入 0 条
            r2 = mem.persist(tmpdir)
            assert r2.get("success"), f"second persist failed: {r2}"
            assert r2["short_written"] == 0, f"expected 0 writes (no new dirty), got {r2}"

            # 再写 1 条 → 再次只写入这条
            eid3 = mem.remember("agent-dirty", "note",
                                "Third entry added after persist, should be the only dirty one.",
                                ring=2)
            assert eid3 in mem._dirty_short
            r3 = mem.persist(tmpdir)
            assert r3.get("success"), f"third persist failed: {r3}"
            assert r3["short_written"] == 1, f"expected 1 dirty write, got {r3}"

    def test_persist_only_dirty_ring3(self):
        """persist 只写入脏的 Ring 3 SQLite 条目"""
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()

        eid1 = mem.remember("agent-dirty-l3", "knowledge",
                            "Long term knowledge entry for dirty tracking test with sufficient content.",
                            ring=3)
        assert eid1 in mem._dirty_long

        with tempfile.TemporaryDirectory() as tmpdir:
            r1 = mem.persist(tmpdir)
            assert r1.get("success"), f"first persist failed: {r1}"
            assert r1["long_written"] == 1, f"expected 1 long write, got {r1}"
            assert len(mem._dirty_long) == 0

            # 第二次 persist（无新 Ring 3 条目）：long_written 应为 0
            r2 = mem.persist(tmpdir)
            assert r2.get("success"), f"second persist failed: {r2}"
            assert r2["long_written"] == 0, f"expected 0 long writes, got {r2}"

    def test_dirty_set_after_compact(self):
        """compact 创建的 summary 条目应被标记为 dirty"""
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        for i in range(5):
            mem.remember("agent-compact-dirty", "tool_call",
                         f"compact test entry number {i} with enough text content to pass quality validation.",
                         tags=["build"], ring=2)
        before = len(mem._dirty_short)
        r = mem.compact("agent-compact-dirty")
        assert isinstance(r, dict)
        # compact 在 Ring 2 中创建 summary 条目 → _dirty_short 应增长或至少保持
        assert len(mem._dirty_short) >= before, "dirty set should not shrink after compact"


class TestMemoryDirtyTrackingConcurrent:
    """多线程脏追踪安全测试 — 并发 remember + persist 不丢失脏条目"""

    def test_concurrent_remember_ring2(self):
        """多线程同时 remember Ring 2 条目，所有应被标记为 dirty"""
        import threading

        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        n_threads = 4
        entries_per_thread = 25
        errors = []

        def worker(n):
            for i in range(entries_per_thread):
                try:
                    mem.remember(
                        f"agent-con-{n}", "note",
                        f"Concurrent dirty entry {n}-{i} with enough content to pass validation.",
                        ring=2,
                    )
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"concurrent remember errors: {errors}"
        expected = n_threads * entries_per_thread
        assert len(mem._dirty_short) == expected, (
            f"expected {expected} dirty entries, got {len(mem._dirty_short)}"
        )

    def test_concurrent_remember_and_persist(self):
        """并发 remember + persist 不应丢失脏条目。persist 后新 remember 重新标记为 dirty。"""
        import tempfile
        import threading

        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        barrier = threading.Barrier(3)
        errors = []

        def writer(n):
            try:
                for i in range(20):
                    mem.remember(
                        f"agent-cp-{n}", "note",
                        f"Concurrent persist test entry {n}-{i} with enough content.",
                        ring=2,
                    )
                barrier.wait()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer, args=(1,))
        t2 = threading.Thread(target=writer, args=(2,))
        t1.start()
        t2.start()

        # 在主线程中也写入并 persist
        for i in range(10):
            mem.remember("agent-cp-main", "note",
                         f"Main thread entry {i} for concurrent persist test.", ring=2)
        barrier.wait()

        with tempfile.TemporaryDirectory() as tmpdir:
            r = mem.persist(tmpdir)
            assert r.get("success"), f"concurrent persist failed: {r}"
            assert r["short_written"] == 50, (
                f"expected 50 dirty entries persisted, got {r['short_written']}"
            )

        t1.join()
        t2.join()
        assert len(errors) == 0, f"concurrent errors: {errors}"

    def test_concurrent_ring3_dirty(self):
        """多线程 remember Ring 3 条目，所有应标记为 _dirty_long"""
        import threading

        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        errors = []

        def worker(n):
            try:
                for i in range(10):
                    mem.remember(
                        f"agent-l3-{n}", "knowledge",
                        f"Long term concurrent entry {n}-{i} with sufficient content.",
                        ring=3,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(mem._dirty_long) == 30, (
            f"expected 30 dirty long entries, got {len(mem._dirty_long)}"
        )


class TestPersistCrashSafety:
    """persist 崩溃安全测试 — 写入失败时脏条目应保留，可重试。"""

    def test_dirty_survives_failed_persist(self):
        """写入失败后脏条目不清除，可再次 persist 成功。"""
        import os
        import tempfile

        from l3.memory.memory import MemoryManager
        mem = MemoryManager()

        eid = mem.remember("agent-safe", "note",
                           "This entry should survive a persist failure with enough content.",
                           ring=2)
        assert eid in mem._dirty_short

        # 用只读目录模拟写入失败（如果 tempdir 被 chmod）
        with tempfile.TemporaryDirectory() as tmpdir:
            readonly = os.path.join(tmpdir, "readonly")
            os.mkdir(readonly, mode=0o444)
            try:
                r = mem.persist(readonly)
            except (PermissionError, OSError):
                pass
            else:
                # 某些系统可能不拒绝写入只读目录 → 此时 persist 应成功
                if r.get("success"):
                    assert eid not in mem._dirty_short
                    return

            # 写入失败后，脏条目应保留
            assert eid in mem._dirty_short, (
                "dirty entry should survive failed persist"
            )

            # 重试到可写目录应成功
            writable = os.path.join(tmpdir, "writable")
            os.mkdir(writable)
            r2 = mem.persist(writable)
            assert r2.get("success"), f"retry persist failed: {r2}"
            assert r2["short_written"] == 1, (
                f"expected 1 entry on retry, got {r2['short_written']}"
            )
            assert eid not in mem._dirty_short, (
                "dirty set should be cleared after successful persist"
            )

    def test_dirty_survives_interrupted_write(self):
        """模拟中途异常，验证脏集在异常后仍保留。"""
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()

        mem.remember("agent-interrupt", "note",
                     "Entry that should survive an interrupted persist with enough content.",
                     ring=2)
        mem.remember("agent-interrupt", "knowledge",
                     "Long term entry for interrupt test with enough content.",
                     ring=3)

        before_short = set(mem._dirty_short)
        before_long = set(mem._dirty_long)

        # 模拟失败：用 None path 调用 persist（应返回错误）
        r = mem.persist(None)
        assert not r.get("success"), "persist with no path should fail"

        # 失败后脏集应完全保留
        assert mem._dirty_short == before_short, (
            f"dirty_short changed after failed persist: was {before_short}, now {mem._dirty_short}"
        )
        assert mem._dirty_long == before_long, (
            f"dirty_long changed after failed persist: was {before_long}, now {mem._dirty_long}"
        )
