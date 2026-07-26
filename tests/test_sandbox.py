"""Sandbox isolation test — Agent registration/file read-write/stage/flush/discard"""

import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _clear_sandbox_state() -> None:
    """Remove the persisted sandbox state file so each test starts clean."""
    try:
        from l1.kernel.params.system import SANDBOX_STATE_PATH
        if os.path.exists(SANDBOX_STATE_PATH):
            os.remove(SANDBOX_STATE_PATH)
    except Exception:
        pass


class TestCellSandbox:
    """Cell sandbox"""

    def setup_method(self):
        from l4.sandbox import reset_manager
        _clear_sandbox_state()
        reset_manager()

    def test_create_cell(self):
        from l4.sandbox import SandboxManager
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            sb = mgr.create_cell("sand-cell-1", project_root=d)
            assert sb is not None

    def test_get_cell(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("sand-get", project_root=d)
            sb = mgr.get_cell("sand-get")
            assert sb is not None

    def test_get_nonexistent_cell(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        sb = mgr.get_cell("no-such-cell")
        assert sb is None


class TestSandboxOps:
    """Sandbox read/write operations"""

    def test_write_and_read(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("ops-cell", project_root=d)
            sb = mgr.get_cell("ops-cell")
            sb.register_agent("agent-a")
            w = sb.write("test.txt", "hello sandbox", "agent-a")
            assert w["success"], f"write failed: {w}"
            r = sb.read("test.txt", "agent-a")
            assert r["success"], f"read failed: {r}"
            assert "hello sandbox" in r.get("content", "")

    def test_write_and_stage(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("stage-cell", project_root=d)
            sb = mgr.get_cell("stage-cell")
            sb.register_agent("agent-b")
            sb.write("staged.txt", "staged content", "agent-b")
            s = sb.stage("agent-b")
            assert s["success"], f"stage failed: {s}"
            assert s["count"] >= 1
            st = sb.status()
            assert st["staged"] >= 1

    def test_flush(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("flush-cell", project_root=d)
            sb = mgr.get_cell("flush-cell")
            sb.register_agent("agent-c")
            sb.write("flush.txt", "flush me", "agent-c")
            sb.stage("agent-c")
            r = sb.flush("agent-c")
            assert r["success"], f"flush failed: {r}"
            # After flush, staged should be empty
            s = sb.status()
            assert s["staged"] == 0, f"staged={s['staged']}, flushed={s['flushed']}, entries={s['entries']}"

    def test_discard(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("discard-cell", project_root=d)
            sb = mgr.get_cell("discard-cell")
            sb.register_agent("agent-d")
            sb.write("temp.txt", "temporary", "agent-d")
            r = sb.discard("agent-d")
            assert r["success"]
            # After discard, reading should fail
            rd = sb.read("temp.txt", "agent-d")
            assert not rd.get("success")

    def test_read_nonexistent(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("read-nx", project_root=d)
            sb = mgr.get_cell("read-nx")
            sb.register_agent("agent-e")
            r = sb.read("no-file.txt", "agent-e")
            assert not r.get("success")


class TestAgentRegistration:
    """Agent 注册"""

    def setup_method(self):
        from l4.sandbox import reset_manager
        _clear_sandbox_state()
        reset_manager()

    def test_register_agent(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("reg-cell", project_root=d)
            sb = mgr.get_cell("reg-cell")
            r = sb.register_agent("new-agent")
            assert r is not None

    def test_register_duplicate(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("dup-cell", project_root=d)
            sb = mgr.get_cell("dup-cell")
            sb.register_agent("dup-agent")
            r = sb.register_agent("dup-agent")
            assert r is not None  # duplicate is fine, no-op

    def test_register_multiple(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("multi-cell", project_root=d)
            sb = mgr.get_cell("multi-cell")
            for i in range(5):
                r = sb.register_agent(f"multi-{i}")
                assert r is not None


class TestStatus:
    """沙箱状态"""

    def setup_method(self):
        from l4.sandbox import reset_manager
        _clear_sandbox_state()
        reset_manager()

    def test_status_empty(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("stat-cell", project_root=d)
            sb = mgr.get_cell("stat-cell")
            sb.register_agent("stat-agent")
            s = sb.status()
            assert s["staged"] == 0
            assert s["flushed"] == 0

    def test_status_after_write(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("stat-cell-2", project_root=d)
            sb = mgr.get_cell("stat-cell-2")
            sb.register_agent("stat-agent-2")
            sb.write("f1.txt", "data1", "stat-agent-2")
            sb.write("f2.txt", "data2", "stat-agent-2")
            s = sb.status()
            assert s["pending"] >= 2

    def test_cleanup(self):
        from l4.sandbox import SandboxManager, reset_manager
        reset_manager()
        mgr = SandboxManager()
        with tempfile.TemporaryDirectory() as d:
            mgr.create_cell("clean-cell", project_root=d)
            r = mgr.cleanup("clean-cell")
            assert r["success"]
