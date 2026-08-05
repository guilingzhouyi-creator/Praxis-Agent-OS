"""Memory and Sandbox service tests."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestMemoryManager:
    def test_remember_and_recall(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        eid = mem.remember("agent-a", "tool_call", "read_file /etc/config find version=2.0", tags=["read"], ring=1)
        assert eid.startswith("mem-")
        results = mem.recall(agent_id="agent-a", limit=10)
        assert len(results) == 1
        assert results[0].entry_type == "tool_call"

    def test_recall_by_type(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-a", "decision", "approve deploy to production server v3", ring=2)
        mem.remember("agent-a", "observation", "saw error in /var/log/app.log port 8080", ring=1)
        decisions = mem.recall(agent_id="agent-a", entry_type="decision")
        assert len(decisions) >= 1
        assert any(e.entry_type == "decision" for e in decisions), (
            f"expected at least one 'decision' entry, got {[e.entry_type for e in decisions]}"
        )

    def test_recall_by_tag(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-a", "observation", "security audit found open port 443 on 10.0.1.50", tags=["urgent", "security"], ring=1)
        results = mem.recall(agent_id="agent-a", tag="security")
        assert len(results) >= 1

    def test_recall_multiple_rings(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-a", "working", "project root at /home/user/src/api uses Python 3.12", ring=1)
        mem.remember("agent-a", "short", "staging server at 10.0.1.50 with Docker Compose", ring=2)
        mem.remember("agent-a", "long", "database migration from MySQL to PostgreSQL completed 2026-01-15", ring=3)
        results = mem.recall(agent_id="agent-a", rings=[1, 2, 3], limit=10)
        assert len(results) >= 3

    def test_build_context(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-a", "observation", "project root at /home/user/src/api uses Python 3.12", ring=1)
        ctx = mem.build_context("agent-a", max_tokens=4096)
        assert "Python 3.12" in ctx

    def test_stats(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-a", "observation", "project uses Poetry for deps not pip", ring=1)
        stats = mem.stats()
        assert "working" in stats
        assert stats["working"]["entries"] >= 1

    def test_forget_agent(self):
        from l3.memory.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("forget-me", "observation", "custom port 2222 for SSH on staging", ring=1)
        mem.forget_agent("forget-me")
        results = mem.recall(agent_id="forget-me")
        assert len(results) == 0

    def test_get_memory_singleton(self):
        from l3.memory.memory import get_memory, reset_memory
        reset_memory()
        m1 = get_memory()
        m2 = get_memory()
        assert m1 is m2


class TestSandbox:
    def test_cell_sandbox_create(self):
        from l4.sandbox import CellSandbox
        td = tempfile.mkdtemp()
        sb = CellSandbox("test-cell", td, td)
        assert sb.cell_id == "test-cell"
        shutil.rmtree(td, ignore_errors=True)

    def test_register_agent(self):
        from l4.sandbox import CellSandbox
        td = tempfile.mkdtemp()
        sb = CellSandbox("cell-1", td, td)
        agent_dir = sb.register_agent("agent-x")
        assert agent_dir.exists()
        assert (sb.sandbox_root / "agent-x") == agent_dir
        shutil.rmtree(td, ignore_errors=True)

    def test_write_and_read(self):
        from l4.sandbox import CellSandbox
        td = tempfile.mkdtemp()
        sb = CellSandbox("cell-wr", td, tempfile.mkdtemp())
        sb.register_agent("writer")
        w = sb.write("test.txt", "hello sandbox", "writer")
        assert w.get("success"), f"write failed: {w}"
        r = sb.read("test.txt", "writer")
        assert r.get("success")
        assert r["content"] == "hello sandbox"
        assert r["source"] == "sandbox"
        shutil.rmtree(td, ignore_errors=True)

    def test_read_from_project(self):
        from l4.sandbox import CellSandbox
        td = tempfile.mkdtemp()
        real_file = os.path.join(td, "existing.txt")
        with open(real_file, "w") as f:
            f.write("project content")
        sb_root = tempfile.mkdtemp()
        sb = CellSandbox("cell-read", td, sb_root)
        sb.register_agent("reader")
        r = sb.read("existing.txt", "reader")
        assert r.get("success")
        assert r["source"] == "project"
        shutil.rmtree(td, ignore_errors=True)
        shutil.rmtree(sb_root, ignore_errors=True)

    def test_discard(self):
        from l4.sandbox import CellSandbox
        td = tempfile.mkdtemp()
        sb = CellSandbox("cell-discard", td, tempfile.mkdtemp())
        sb.register_agent("discarder")
        sb.write("to_discard.txt", "will be gone", "discarder")
        r = sb.discard("discarder")
        assert r.get("success")
        project_file = os.path.join(td, "to_discard.txt")
        assert not os.path.exists(project_file)
        shutil.rmtree(td, ignore_errors=True)

    def test_agent_path(self):
        from l4.sandbox import CellSandbox
        td = tempfile.mkdtemp()
        sb = CellSandbox("cell-path", td, tempfile.mkdtemp())
        sb.register_agent("path-agent")
        p = sb._agent_path("path-agent")
        assert p is not None
        shutil.rmtree(td, ignore_errors=True)
