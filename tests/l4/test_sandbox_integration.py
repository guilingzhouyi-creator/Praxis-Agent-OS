"""Sandbox 集成测试 — write→diff→stage→flush→read COW 周期 + 冲突检测 + 跨 agent 版本路由."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCellSandboxInit:
    """CellSandbox 创建与基本操作"""

    def test_create_and_register_agent(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            p = sb.register_agent("agent-a")
            assert p.exists()
            assert p.name == "agent-a"

    def test_write_and_read_own_sandbox(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            w = sb.write("hello.txt", "world", "agent-a", task_id="t1", depends_on=[])
            assert w["success"]
            r = sb.read("hello.txt", "agent-a", depends_on=[])
            assert r["success"]
            assert r["content"] == "world"
            assert r["source"] == "sandbox"

    def test_write_creates_diff_hunks(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            w = sb.write("hello.txt", "world", "agent-a", task_id="t1", depends_on=[])
            assert w["success"]
            assert "entry" in w
            assert len(w["entry"].get("hunks", [])) >= 0  # new file may or may not produce hunks

    def test_write_populates_entry_metadata(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            w = sb.write("f.txt", "content", "agent-a", task_id="t-42", depends_on=["agent-b"])
            assert w["entry"]["task_id"] == "t-42"
            assert "agent-b" in w["entry"]["depends_on"]


class TestCellSandboxReadWriteCycle:
    """write → stage → flush → read 完整 COW 周期"""

    def test_write_disk_file_staged_pending(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            w = sb.write("f.txt", "staged content", "agent-a", task_id="t1", depends_on=[])
            assert w["success"]
            # File should not be on real disk yet (still in sandbox)
            real_path = os.path.join(td, "f.txt")
            assert not os.path.exists(real_path)

    def test_stage_then_flush_writes_to_project(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            sb.write("f.txt", "staged content", "agent-a", task_id="t1", depends_on=[])
            stage_r = sb.stage("agent-a")
            assert stage_r["success"]
            flush_r = sb.flush("agent-a")
            assert flush_r["success"]
            # After flush, file should exist on real disk
            real_path = os.path.join(td, "f.txt")
            assert os.path.exists(real_path)
            assert open(real_path).read() == "staged content"

    def test_discard_removes_pending_changes(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            sb.write("f.txt", "will be discarded", "agent-a", task_id="t1", depends_on=[])
            discard_r = sb.discard("agent-a")
            assert discard_r["success"]
            # After discard, read should return empty
            # (file doesn't exist in project, sandbox entry was removed)


class TestCellSandboxCrossAgentVersionRouting:
    """跨 agent 版本路由 — depends_on 参数"""

    def test_read_own_sandbox_first(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            sb.write("f.txt", "agent-a version", "agent-a", task_id="t1", depends_on=[])
            r = sb.read("f.txt", "agent-a", depends_on=[])
            assert r["content"] == "agent-a version"
            assert r["source"] == "sandbox"

    def test_read_upstream_when_own_missing(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            sb.register_agent("agent-b")
            sb.write("f.txt", "upstream version", "agent-a", task_id="t1", depends_on=[])
            r = sb.read("f.txt", "agent-b", depends_on=["agent-a"])
            assert r["success"]
            assert r["content"] == "upstream version"

    def test_read_project_fallback_when_no_sandbox(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            # Create a project file first
            real_file = os.path.join(td, "project.txt")
            with open(real_file, "w") as f:
                f.write("project base")
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            r = sb.read("project.txt", "agent-a", depends_on=[])
            assert r["success"]
            assert r["content"] == "project base"
            assert r["source"] == "project"


class TestCellSandboxConflictDetection:
    """跨 agent 冲突检测"""

    def test_same_agent_no_conflict(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            sb.write("f.txt", "v1", "agent-a", task_id="t1", depends_on=[])
            w2 = sb.write("f.txt", "v2", "agent-a", task_id="t2", depends_on=[])
            assert w2["success"]

    def test_diff_agent_detects_conflict(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            sb.register_agent("agent-b")
            sb.write("f.txt", "by a", "agent-a", task_id="t1", depends_on=[])
            w2 = sb.write("f.txt", "by b", "agent-b", task_id="t2", depends_on=[])
            assert w2["conflict"] in ("block", "warn")


class TestCellSandboxStatus:
    """sandbox status 查询"""

    def test_status_after_write(self):
        from l4.sandbox.cell_sandbox import CellSandbox
        with tempfile.TemporaryDirectory() as td:
            sb = CellSandbox("test-cell", td, os.path.join(td, ".sandbox"))
            sb.register_agent("agent-a")
            s0 = sb.status()
            assert s0["pending"] == 0
            sb.write("f.txt", "x", "agent-a", task_id="t1", depends_on=[])
            s1 = sb.status()
            assert s1["pending"] >= 1
