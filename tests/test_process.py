"""Process table tests — spawn/get/set_state/exit/reap/list/audit"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestProcessTable:
    """Process table basics"""

    def setup_method(self):
        from kernel.process import reset_table
        reset_table()

    def test_init_has_pid0(self):
        from kernel.process import get_table
        t = get_table()
        p0 = t.get(0)
        assert p0 is not None
        assert p0.name == "kernel"

    def test_get_nonexistent(self):
        from kernel.process import get_table
        t = get_table()
        p = t.get(99999)
        assert p is None


class TestSpawn:
    """Process creation"""

    def test_spawn_basic(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        pcb = t.spawn("agent-a", role="reader", ring=1)
        assert pcb.pid >= 1
        assert pcb.name == "agent-a"
        assert pcb.role == "reader"

    def test_spawn_multiple(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        p1 = t.spawn("a1")
        p2 = t.spawn("a2")
        assert p1.pid != p2.pid

    def test_spawn_with_parent(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        child = t.spawn("child-agent", parent_pid=0)
        assert child.parent_pid == 0


class TestGetByName:
    """Lookup by name"""

    def test_get_by_name(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        t.spawn("find-me")
        pcb = t.get_by_name("find-me")
        assert pcb is not None
        assert pcb.name == "find-me"

    def test_get_by_name_nonexistent(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        pcb = t.get_by_name("no-such-process")
        assert pcb is None


class TestSetState:
    """State setting"""

    def test_set_state(self):
        from kernel.process import get_table, reset_table, ProcessState
        reset_table()
        t = get_table()
        pcb = t.spawn("state-test")
        r = t.set_state(pcb.pid, ProcessState.RUNNING)
        assert r is True
        assert pcb.state == ProcessState.RUNNING

    def test_set_state_nonexistent(self):
        from kernel.process import get_table, reset_table, ProcessState
        reset_table()
        t = get_table()
        r = t.set_state(99999, ProcessState.RUNNING)
        assert r is False

    def test_zombie_state(self):
        from kernel.process import get_table, reset_table, ProcessState
        reset_table()
        t = get_table()
        pcb = t.spawn("zombie-test")
        t.set_state(pcb.pid, ProcessState.ZOMBIE)
        assert pcb.state == ProcessState.ZOMBIE


class TestExit:
    """Process exit"""

    def test_exit_basic(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        pcb = t.spawn("exit-test")
        r = t.exit(pcb.pid, exit_code=0, reason="finished")
        assert r is True

    def test_exit_sets_state(self):
        from kernel.process import get_table, reset_table, ProcessState
        reset_table()
        t = get_table()
        pcb = t.spawn("exit-state")
        t.exit(pcb.pid)
        assert pcb.state == ProcessState.ZOMBIE

    def test_exit_nonexistent(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        r = t.exit(99999)
        assert r is False


class TestReap:
    """Process reaping"""

    def test_reap_basic(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        pcb = t.spawn("reap-me")
        t.exit(pcb.pid)
        snap = t.reap(pcb.pid)
        assert snap is not None
        assert snap["name"] == "reap-me"

    def test_reap_nonexistent(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        snap = t.reap(99999)
        assert snap is None


class TestList:
    """Process listing"""

    def test_list_all(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        t.spawn("list-a")
        t.spawn("list-b")
        procs = t.list()
        assert len(procs) >= 2

    def test_list_by_state(self):
        from kernel.process import get_table, reset_table, ProcessState
        reset_table()
        t = get_table()
        t.spawn("running-1")
        t.spawn("running-2")
        running = t.list(state=ProcessState.RUNNING)
        assert len(running) >= 1

    def test_list_sorted(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        p1 = t.spawn("z-first")
        p2 = t.spawn("a-second")
        procs = t.list()
        assert procs[0]["pid"] < procs[1]["pid"]


class TestIdentity:
    """Identity verification mark"""

    def test_mark_identity(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        t.spawn("id-test")
        r = t.mark_identity_verified("id-test")
        assert r is True

    def test_mark_identity_nonexistent(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        r = t.mark_identity_verified("no-such-agent")
        assert r is False


class TestAudit:
    """Audit log"""

    def test_audit_log_basic(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        t.spawn("audit-me")
        logs = t.audit_log(limit=10)
        assert len(logs) >= 1
        assert any(l["name"] == "audit-me" for l in logs)

    def test_audit_log_limit(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        t.spawn("a1")
        t.spawn("a2")
        logs = t.audit_log(limit=1)
        assert len(logs) <= 1


class TestResourceSummary:
    """Resource summary"""

    def test_resource_summary(self):
        from kernel.process import get_table, reset_table
        reset_table()
        t = get_table()
        s = t.resource_summary()
        assert "tokens" in s
        assert "workers" in s
        assert "scouts" in s
        assert "cards" in s


class TestPCB:
    """PCB data class"""

    def test_pcb_create(self):
        from kernel.process import PCB, ProcessState
        pcb = PCB(pid=1, name="test-pcb", role="reader", ring=1)
        assert pcb.pid == 1
        assert pcb.name == "test-pcb"
        assert pcb.role == "reader"

    def test_pcb_snapshot(self):
        from kernel.process import PCB
        pcb = PCB(pid=2, name="snap-test")
        s = pcb.snapshot()
        assert s["pid"] == 2
        assert s["name"] == "snap-test"
        assert "state" in s
        # Resource fields are spread into the flat dict via **self.resources.__dict__
        assert "tokens_allocated" in s
        assert "cpu_time" in s
        assert "cards_processed" in s

    def test_pcb_touch(self):
        from kernel.process import PCB
        import time
        pcb = PCB(pid=3, name="touch-test")
        t1 = pcb.last_active
        time.sleep(0.01)
        pcb.touch()
        assert pcb.last_active > t1
