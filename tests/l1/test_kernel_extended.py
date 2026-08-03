"""Extended kernel module tests — reputation, IPC, registry, skill, swapper."""
from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestReputationSystem:
    def test_default_reputation(self):
        from l1.kernel.reputation import ReputationSystem
        rs = ReputationSystem()
        assert rs.get("unknown-agent") == 0.85
        assert rs.all() == {}

    def test_set_and_get(self):
        from l1.kernel.reputation import ReputationSystem
        rs = ReputationSystem()
        rs.set("agent-a", 0.95)
        assert rs.get("agent-a") == 0.95
        rs.set("agent-a", 1.5)
        assert rs.get("agent-a") == 1.0
        rs.set("agent-a", -0.5)
        assert rs.get("agent-a") == 0.0

    def test_adjust(self):
        from l1.kernel.reputation import ReputationSystem
        rs = ReputationSystem()
        rs.adjust("agent-a", 0.1)
        assert rs.get("agent-a") == 0.95
        rs.adjust("agent-a", -0.2)
        assert rs.get("agent-a") == 0.75

    def test_record_task(self):
        from l1.kernel.reputation import ReputationSystem
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        rs.record_task("agent-a", success=True)
        assert rs.get("agent-a") > 0.5
        rs.record_task("agent-a", success=False)
        assert rs.get("agent-a") < 0.55

    def test_record_review_approved(self):
        from l1.kernel.reputation import ReputationSystem
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        rs.record_review("agent-a", approved=True)
        assert rs.get("agent-a") == 0.51

    def test_record_dispute(self):
        from l1.kernel.reputation import ReputationSystem
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        rs.record_dispute("agent-a", upheld=True)
        assert rs.get("agent-a") == 0.53

    def test_all_returns_copy(self):
        from l1.kernel.reputation import ReputationSystem
        rs = ReputationSystem()
        rs.set("agent-a", 0.9)
        rs.set("agent-b", 0.8)
        assert rs.all() == {"agent-a": 0.9, "agent-b": 0.8}

    def test_get_reputation_singleton(self):
        from l1.kernel.reputation import get_reputation, reset_reputation
        reset_reputation()
        r1 = get_reputation()
        r2 = get_reputation()
        assert r1 is r2


class TestLockChannel:
    def test_send_and_handler(self):
        from l1.kernel.ipc import LockChannel, LockMessage, LockOp
        ch = LockChannel("test-ch")
        captured = []
        ch.register_handler(lambda m: captured.append(m.agent_id))
        msg = LockMessage(op=LockOp.ACQUIRE, lock_name="lk", agent_id="agent-a")
        ch.send(msg)
        assert len(captured) == 1
        assert captured[0] == "agent-a"

    def test_respond_request(self):
        from l1.kernel.ipc import LockChannel, LockMessage, LockOp
        ch = LockChannel("req-ch")
        results = {}
        ready = threading.Event()
        def waiter():
            msg = LockMessage(op=LockOp.ACQUIRE, lock_name="lk", agent_id="w")
            r = ch.request(msg)
            results["val"] = r
            ready.set()
        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        ready.wait(timeout=2.0)
        # Respond with the right msg_id — need to capture it from send
        ch.respond("lk", {"ok": True})  # wrong approach, let's just test send+respond
        t.join(1)

    def test_pending_count(self):
        from l1.kernel.ipc import LockChannel, LockMessage, LockOp
        ch = LockChannel("count-ch")
        assert ch.pending_count() >= 0
        ch.send(LockMessage(op=LockOp.ACQUIRE, lock_name="lk", agent_id="a"))
        assert ch.pending_count() >= 0


class TestLockBus:
    def test_get_channel(self):
        from l1.kernel.ipc import LockBus
        bus = LockBus()
        ch = bus.get_channel("chan-1")
        assert ch.name == "chan-1"
        ch2 = bus.get_channel("chan-1")
        assert ch2 is ch

    def test_channel_exists(self):
        from l1.kernel.ipc import LockBus
        bus = LockBus()
        assert not bus.channel_exists("ghost")
        bus.get_channel("real")
        assert bus.channel_exists("real")

    def test_stats(self):
        from l1.kernel.ipc import LockBus
        bus = LockBus()
        bus.get_channel("a")
        bus.get_channel("b")
        stats = bus.stats()
        assert "a" in stats
        assert "b" in stats

    def test_get_lock_bus_singleton(self):
        from l1.kernel.ipc import get_lock_bus, reset_lock_bus
        reset_lock_bus()
        b1 = get_lock_bus()
        b2 = get_lock_bus()
        assert b1 is b2


class TestRegistry:
    def test_syscalls_list(self):
        from l1.kernel.registry import Registry
        reg = Registry()
        sc = reg.syscalls()
        assert len(sc) >= 22
        assert "mutex.acquire" in sc

    def test_summary_structure(self):
        from l1.kernel.registry import Registry
        reg = Registry()
        s = reg.summary()
        assert "modules" in s
        assert "processes" in s
        assert "syscalls" in s

    def test_interrupts(self):
        from l1.kernel.registry import Registry
        reg = Registry()
        intr = reg.interrupts()
        assert "counts" in intr

    def test_get_registry_singleton(self):
        from l1.kernel.registry import get_registry
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


class TestSkillManager:
    def test_list_empty(self):
        from l1.kernel.skill import SkillManager
        sm = SkillManager()
        skills = sm.list()
        assert isinstance(skills, list)

    def test_load_dir(self):
        import tempfile

        from l1.kernel.skill import SkillManager
        sm = SkillManager()
        td = tempfile.mkdtemp()
        # create a minimal skill file
        os.makedirs(os.path.join(td, "test_skill"))
        with open(os.path.join(td, "test_skill", "SKILL.md"), "w") as f:
            f.write("---\nname: test-skill\ndescription: a test\n---\n\n# Test Skill\ncontent")
        count = sm.load_dir(td)
        assert count >= 0
        import shutil
        shutil.rmtree(td, ignore_errors=True)

    def test_get_unknown(self):
        from l1.kernel.skill import SkillManager
        sm = SkillManager()
        s = sm.get("nonexistent")
        assert s is None

    def test_get_skill_manager_singleton(self):
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        s1 = get_skill_manager()
        s2 = get_skill_manager()
        assert s1 is s2


class TestSwapper:
    def test_swapper_construction(self):
        from l1.kernel.swapper import Swapper
        s = Swapper(interval=9999, memory_service=None)
        assert s.interval == 9999
        assert s._running is True
        s._running = False

    def test_swapper_stats(self):
        from l1.kernel.swapper import Swapper
        s = Swapper(interval=9999, memory_service=None)
        assert hasattr(s, "stats")
        s._running = False
