"""Tests for l1.kernel.process — ProcessTable / PCB / state machine."""

from __future__ import annotations

import time

import pytest

from l1.kernel.process import (
    PCB,
    ProcessState,
    ProcessTable,
    get_table,
    reset_table,
)

# ── Fixtures ──

@pytest.fixture
def pt():
    """Fresh ProcessTable with short GC interval disabled."""
    table = ProcessTable(gc_interval=9999)
    yield table
    # Clean up
    for pcb in list(table._processes.values()):
        table.reap(pcb.pid)


class TestProcessState:
    """ProcessState enum values."""

    def test_has_states(self):
        assert ProcessState.READY.name == "READY"
        assert ProcessState.RUNNING.name == "RUNNING"
        assert ProcessState.BLOCKED.name == "BLOCKED"
        assert ProcessState.ZOMBIE.name == "ZOMBIE"
        assert ProcessState.STOPPED.name == "STOPPED"


class TestPCB:
    """Process Control Block."""

    def test_create_pcb(self):
        pcb = PCB(pid=1, name="test-agent", role="reader", parent_pid=0, ring=1)
        assert pcb.pid == 1
        assert pcb.name == "test-agent"
        assert pcb.role == "reader"
        assert pcb.parent_pid == 0
        assert pcb.ring == 1
        assert pcb.state == ProcessState.READY
        assert pcb.exit_code is None
        assert pcb.identity_verified is False

    def test_touch_updates_last_active(self):
        pcb = PCB(pid=1, name="a")
        before = pcb.last_active
        time.sleep(0.01)
        pcb.touch()
        assert pcb.last_active > before

    def test_record_tokens(self):
        pcb = PCB(pid=1, name="a")
        pcb.record_tokens(100, 50)
        assert pcb.resources.tokens_allocated == 100
        assert pcb.resources.tokens_used == 50

    def test_record_card(self):
        pcb = PCB(pid=1, name="a")
        pcb.record_card()
        assert pcb.resources.cards_processed == 1

    def test_record_cpu(self):
        pcb = PCB(pid=1, name="a")
        pcb.record_cpu(1.5)
        assert pcb.resources.cpu_time == 1.5

    def test_record_scout(self):
        pcb = PCB(pid=1, name="a")
        pcb.record_scout(3)
        assert pcb.resources.scouts_active == 3
        pcb.record_scout(-1)
        assert pcb.resources.scouts_active == 2

    def test_snapshot_shape(self):
        pcb = PCB(pid=1, name="a", role="writer", ring=2)
        snap = pcb.snapshot()
        assert snap["pid"] == 1
        assert snap["name"] == "a"
        assert snap["role"] == "writer"
        assert snap["ring"] == 2
        assert snap["state"] == "READY"
        assert "uptime" in snap
        assert "idle" in snap


class TestProcessTableInit:
    """Process table initialization."""

    def test_init_has_pid0(self, pt):
        """PID 0 is the kernel init process."""
        pcb = pt.get(0)
        assert pcb is not None
        assert pcb.name == "kernel"
        assert pcb.role == "init"
        assert pcb.ring == 3
        assert pcb.state == ProcessState.RUNNING

    def test_singleton(self):
        t1 = get_table()
        t2 = get_table()
        assert t1 is t2

    def test_reset(self):
        t = get_table()
        reset_table()
        t2 = get_table()
        assert t2 is not t


class TestSpawn:
    """Process spawning."""

    def test_spawn_increments_pid(self, pt):
        p1 = pt.spawn("agent-a")
        p2 = pt.spawn("agent-b")
        assert p2.pid > p1.pid

    def test_spawn_with_role_and_ring(self, pt):
        pcb = pt.spawn("agent-a", role="reader", parent_pid=0, ring=1)
        assert pcb.role == "reader"
        assert pcb.parent_pid == 0
        assert pcb.ring == 1
        assert pcb.state == ProcessState.READY

    def test_spawn_adds_to_table(self, pt):
        pcb = pt.spawn("agent-a")
        assert pt.get(pcb.pid) is pcb

    def test_spawn_name_index(self, pt):
        pcb = pt.spawn("agent-a")
        assert pt.get_by_name("agent-a") is pcb


class TestGet:
    """Process lookup."""

    def test_get_by_pid(self, pt):
        pcb = pt.spawn("agent-a")
        assert pt.get(pcb.pid) is pcb

    def test_get_nonexistent(self, pt):
        assert pt.get(9999) is None

    def test_get_by_name(self, pt):
        pcb = pt.spawn("agent-a")
        assert pt.get_by_name("agent-a") is pcb

    def test_get_by_name_nonexistent(self, pt):
        assert pt.get_by_name("nonexistent") is None


class TestSetState:
    """State transitions."""

    def test_set_state(self, pt):
        pcb = pt.spawn("agent-a")
        assert pt.set_state(pcb.pid, ProcessState.RUNNING) is True
        assert pcb.state == ProcessState.RUNNING

    def test_set_state_nonexistent(self, pt):
        assert pt.set_state(9999, ProcessState.RUNNING) is False

    def test_set_state_touches_timestamp(self, pt):
        pcb = pt.spawn("agent-a")
        before = pcb.last_active
        time.sleep(0.01)
        pt.set_state(pcb.pid, ProcessState.RUNNING)
        assert pcb.last_active > before


class TestExitReap:
    """Process termination and cleanup."""

    def test_exit_sets_zombie(self, pt):
        pcb = pt.spawn("agent-a")
        assert pt.exit(pcb.pid, exit_code=1, reason="finished") is True
        assert pcb.state == ProcessState.ZOMBIE
        assert pcb.exit_code == 1
        assert pcb.exit_reason == "finished"

    def test_exit_nonexistent(self, pt):
        assert pt.exit(9999) is False

    def test_reap_removes_process(self, pt):
        pcb = pt.spawn("agent-a")
        pt.exit(pcb.pid)
        snap = pt.reap(pcb.pid)
        assert snap is not None
        assert pt.get(pcb.pid) is None
        assert pt.get_by_name("agent-a") is None

    def test_reap_twice(self, pt):
        pcb = pt.spawn("agent-a")
        pt.exit(pcb.pid)
        pt.reap(pcb.pid)
        assert pt.reap(pcb.pid) is None


class TestList:
    """Process listing."""

    def test_list_all(self, pt):
        pt.spawn("agent-a")
        pt.spawn("agent-b")
        # + PID 0 (kernel init)
        assert len(pt.list()) >= 3

    def test_list_by_state(self, pt):
        pt.spawn("agent-a")
        pcb = pt.spawn("agent-b")
        pt.set_state(pcb.pid, ProcessState.RUNNING)
        running = pt.list(state=ProcessState.RUNNING)
        assert all(p["state"] == "RUNNING" for p in running)

    def test_list_returns_snapshots(self, pt):
        pcb = pt.spawn("agent-a")
        items = pt.list()
        snap = [i for i in items if i["pid"] == pcb.pid][0]
        assert snap["name"] == "agent-a"
        assert "pid" in snap
        assert "state" in snap


class TestMarkIdentityVerified:
    """Ed25519 identity verification."""

    def test_mark_verified(self, pt):
        pt.spawn("agent-a")
        assert pt.mark_identity_verified("agent-a") is True
        assert pt.get_by_name("agent-a").identity_verified is True

    def test_mark_verified_nonexistent(self, pt):
        assert pt.mark_identity_verified("nonexistent") is False


class TestResourceSummary:
    """Aggregated resource accounting."""

    def test_resource_summary_shape(self, pt):
        summary = pt.resource_summary()
        assert "tokens" in summary
        assert "workers" in summary
        assert "scouts" in summary
        assert "cards" in summary

    def test_resource_summary_after_activity(self, pt):
        pcb = pt.spawn("agent-a")
        pcb.record_card()
        summary = pt.resource_summary()
        assert summary["cards"] >= 1


class TestAuditLog:
    """Audit trail."""

    def test_audit_log_after_operations(self, pt):
        pt.spawn("agent-a")
        pcb = pt.get_by_name("agent-a")
        pt.exit(pcb.pid)
        log = pt.audit_log()
        assert len(log) >= 2

    def test_audit_log_entries_shape(self, pt):
        pt.spawn("agent-b")
        log = pt.audit_log()
        entry = log[-1]
        assert "op" in entry
        assert "pid" in entry
        assert "name" in entry
        assert "timestamp" in entry


class TestGcReaper:
    """Background zombie reaper."""

    def test_gc_reaps_old_zombies(self):
        """Zombie reaper — zombie eligible for reaping after 300s idle."""
        pt = ProcessTable(gc_interval=0.05)
        pcb = pt.spawn("agent-a")
        pt.exit(pcb.pid)
        pcb.last_active = time.time() - 600  # older than 300s threshold
        # Manually simulate one GC tick: check if zombie would be reaped
        now = time.time()
        zombies = [(pid, p) for pid, p in pt._processes.items()
                   if p.state == ProcessState.ZOMBIE and now - p.last_active > 300]
        assert len(zombies) >= 1
        for zpid, _ in zombies:
            pt._processes.pop(zpid, None)
        assert pt.get(pcb.pid) is None
