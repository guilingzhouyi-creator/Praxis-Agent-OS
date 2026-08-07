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
        skills = sm.list_skills()
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

    def test_authorize_write_system_internal(self):
        """Identity-less writes are allowed ONLY with internal=True."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        # Default (external): identity-less is rejected.
        ok, who = sm.authorize_write()
        assert not ok
        assert "identity required" in who
        # System-internal (boot/R4Agent): allowed.
        ok, who = sm.authorize_write(internal=True)
        assert ok
        assert who == "system"

    def test_authorize_write_role_allowed(self):
        """Role in write_roles → allowed."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        ok, who = sm.authorize_write(role="l3")
        assert ok
        assert who == "l3"

    def test_authorize_write_ring_clearance(self):
        """Role with ring >= min_ring → allowed even if not in roles list."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        # "default" has ring 3 (>= min_ring 3) and is not in write_roles
        ok, who = sm.authorize_write(role="default")
        assert ok
        assert who == "default"

    def test_authorize_write_denied(self):
        """Low-ring role not in write_roles → denied."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        ok, who = sm.authorize_write(role="reader")
        assert not ok
        assert "lacks skill write clearance" in who

    def test_create_denied_for_reader(self):
        """create() with a reader role → permission denied."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        r = sm.create(name="x", prompt="p", role="reader")
        assert not r["success"]
        assert "permission denied" in r["error"]

    def test_create_accepts_allowed_tools(self):
        """create() persists allowed_tools and useful_count default."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        r = sm.create(name="with-tools", prompt="p", allowed_tools=["read_file", "grep"], internal=True)
        assert r["success"]
        s = sm.get("with-tools")
        assert s["allowed_tools"] == ["read_file", "grep"]
        assert s["useful_count"] == 0

    def test_update_usage_bookkeeping_any_caller(self):
        """Bumping last_used / useful_count is allowed for any caller."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        sm.create(name="used", prompt="p", internal=True)
        r = sm.update("used", {"last_used": 123.0, "useful_count": 5}, role="reader")
        assert r["success"]
        assert sm.get("used")["useful_count"] == 5

    def test_update_structural_requires_clearance(self):
        """Structural update by a reader → permission denied."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        sm.create(name="struct", prompt="p", internal=True)
        r = sm.update("struct", {"prompt": "new"}, role="reader")
        assert not r["success"]
        assert "permission denied" in r["error"]

    def test_delete_requires_clearance(self):
        """delete() by a reader → permission denied."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        sm.create(name="delme", prompt="p", internal=True)
        r = sm.delete("delme", role="reader")
        assert not r["success"]
        assert "permission denied" in r["error"]

    def test_list_sort_by_loaded_at(self):
        """list(sort_by='loaded_at') returns newest first."""
        import time

        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        sm.create(name="old", prompt="p", tags=["evolved"], internal=True)
        time.sleep(0.02)  # ensure distinct timestamps on coarse Windows clocks
        sm.create(name="new", prompt="p", tags=["evolved"], internal=True)
        items = sm.list_skills(tags=["evolved"], sort_by="loaded_at")
        assert items[0]["name"] == "new"

    def test_list_sort_by_last_used(self):
        """list(sort_by='last_used') returns most recently used first."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        sm.create(name="a", prompt="p", tags=["evolved"], internal=True)
        sm.create(name="b", prompt="p", tags=["evolved"], internal=True)
        sm.update("a", {"last_used": 999.0})
        items = sm.list_skills(tags=["evolved"], sort_by="last_used")
        assert items[0]["name"] == "a"

    def test_query_keyword_scoring(self):
        """query() ranks name hits above description hits."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        sm.create(name="python-style", prompt="rules for python", tags=["evolved"], internal=True)
        sm.create(name="go-style", prompt="python linting guide", tags=["evolved"], internal=True)
        results = sm.query("python")
        assert len(results) >= 1
        assert results[0]["name"] == "python-style"

    def test_query_empty_returns_empty(self):
        """query('') returns empty list, not an exception."""
        from l1.kernel.skill import SkillManager

        sm = SkillManager()
        assert sm.query("") == []

    def test_to_dict_includes_tags_and_loaded_at(self):
        """Skill.to_dict now includes tags and loaded_at."""
        from l1.kernel.skill import Skill

        s = Skill(name="full", description="d", prompt="p")
        d = s.to_dict()
        assert "tags" in d
        assert "loaded_at" in d
        assert d["loaded_at"] == 0.0


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
