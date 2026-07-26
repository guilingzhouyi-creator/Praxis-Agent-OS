"""Kernel module tests — sync, event, process, interrupt, device, vfs, gatechain, allocator."""

import sys
import os
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestKernelHealth:
    def test_health_pass(self):
        from kernel import health
        h = health()
        assert h["status"] == "PASS"
        assert h["module_count"] >= 9


class TestProcessTable:
    def test_pid0_exists(self):
        from kernel.process import get_table, ProcessState
        pt = get_table()
        assert pt.get(0) is not None
        assert pt.get(0).name == "kernel"

    def test_spawn_and_lifecycle(self):
        from kernel.process import get_table, ProcessState
        pt = get_table()
        p1 = pt.spawn("test-agent", "http", ring=2)
        assert p1.pid > 0
        pt.set_state(p1.pid, ProcessState.RUNNING)
        assert pt.get(p1.pid).state == ProcessState.RUNNING
        procs = pt.list()
        assert len(procs) >= 2
        pt.exit(p1.pid, 0, "test")
        assert pt.get(p1.pid).state == ProcessState.ZOMBIE
        pt.reap(p1.pid)
        assert pt.get(p1.pid) is None


class TestSyscall:
    def test_mutex_acquire(self):
        from kernel import syscall
        r = syscall("mutex.acquire", mutex="t1", agent_id="probe")
        assert r.get("success")

    def test_alloc_usage(self):
        from kernel import syscall
        r = syscall("alloc.usage", agent_id="probe")
        assert r.get("success")

    def test_process_list(self):
        from kernel import syscall
        r = syscall("process.list", agent_id="probe")
        assert r.get("success")

    def test_audit_trail(self):
        from kernel import get_audit_log, record_audit
        log = get_audit_log(limit=5)
        assert len(log) >= 3
        record_audit("custom.event", "probe", True, detail="test")
        log2 = get_audit_log(limit=10)
        assert len(log2) >= len(log)


class TestMutex:
    def test_priority_inheritance(self):
        from kernel.sync import get_mutex
        m = get_mutex("pi-test")
        r1 = m.acquire("low-prio", priority=5.0)
        assert r1["success"]
        result = {}
        def waiter():
            m2 = get_mutex("pi-test")
            result["val"] = m2.acquire("high-prio", priority=1.0, blocking=True)
        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        time.sleep(0.3)
        status = m.status()
        assert status["effective_priority"] < status["base_priority"], \
            f"priority not boosted: eff={status['effective_priority']} base={status['base_priority']}"
        m.release("low-prio")
        t.join(1)
        assert result.get("val", {}).get("success")

    def test_deadlock_detection(self):
        from kernel.sync import get_mutex
        m_a = get_mutex("dl-a", timeout=2.0)
        m_b = get_mutex("dl-b", timeout=2.0)
        m_a.acquire("agent-x", priority=5.0)
        m_b.acquire("agent-y", priority=5.0)
        results = {}
        def waiter_a():
            mb = get_mutex("dl-b", timeout=1.5)
            results["r"] = mb.acquire("agent-x", priority=1.0, blocking=True)
        t = threading.Thread(target=waiter_a, daemon=True)
        t.start()
        time.sleep(0.5)
        r_b = m_a.acquire("agent-y", priority=1.0, blocking=True)
        t.join(3)
        detected = (
            results.get("r", {}).get("cycle_detected", False)
            or r_b.get("cycle_detected", False)
        )
        assert detected, "deadlock not detected"
        m_a.force_unlock()
        m_b.force_unlock()


class TestSemaphore:
    def test_semaphore(self):
        from kernel.sync import get_semaphore
        s = get_semaphore("sem-test", max_count=2)
        assert s.acquire("a")["success"]
        assert s.acquire("b")["success"]
        assert not s.acquire("c", blocking=False)["success"]
        s.release("a")
        assert s.acquire("c")["success"]


class TestBarrier:
    def test_barrier(self):
        from kernel.sync import get_barrier
        b = get_barrier("bar-test", count=2)
        results = []
        def b_waiter():
            b.wait("agent-x")
            results.append("ok")
        t = threading.Thread(target=b_waiter, daemon=True)
        t.start()
        time.sleep(0.1)
        assert len(results) == 0, "barrier should block until N arrive"
        b.wait("agent-y")
        t.join(1)
        assert len(results) == 1, "barrier should release both"
        b.reset()


class TestCondition:
    def test_condition_signal(self):
        from kernel.sync import get_condition
        cv = get_condition("cv-test")
        cv_results = []
        def cv_waiter():
            cv.wait("w")
            cv_results.append("done")
        t = threading.Thread(target=cv_waiter, daemon=True)
        t.start()
        time.sleep(0.1)
        cv.signal("s")
        t.join(1)
        assert len(cv_results) == 1, "condition signal should wake waiter"


class TestEventBus:
    def test_emit(self):
        from kernel import get_event_bus, Signal, SignalType
        bus = get_event_bus()
        captured = []
        bus.on(SignalType.TASK_ASSIGN, lambda s: captured.append(s.data))
        bus.emit(Signal(type=SignalType.TASK_ASSIGN, sender="t", data={"msg": "hi"}))
        assert len(captured) >= 1


class TestGateChain:
    def test_g1_whitelist(self):
        from kernel.gatechain import get_gatechain
        from kernel.process import get_table
        pt = get_table()
        pt.spawn("gc-agent", "security", ring=3)
        gc = get_gatechain()
        gc.register_tools(["read_file", "deploy"])
        r = gc.check("deploy", "gc-agent")
        steps = {s["gate"]: s for s in r.get("steps", [])}
        assert steps.get("G1", {}).get("result") == "PASS", "registered tool should pass G1"

    def test_g2_blocks_unknown(self):
        from kernel.gatechain import get_gatechain
        gc = get_gatechain()
        r2 = gc.check("deploy", "unknown")
        steps2 = {s["gate"]: s for s in r2.get("steps", [])}
        assert not r2.get("allowed"), "unknown agent should be blocked"
        assert steps2.get("G2", {}).get("result") == "BLOCK", "unknown agent should be blocked by G2"


class TestVFS:
    def test_proc_readable(self):
        from kernel.vfs import get_vfs, MountType
        vfs = get_vfs()
        vfs.mount("/proc", MountType.SYSTEM, min_ring=1, read_only=True)
        r = vfs.read("/proc")
        assert r.get("success"), "/proc should be readable"
        assert "PID" in r.get("content", "")

    def test_unknown_path_enoent(self):
        from kernel.vfs import get_vfs
        vfs = get_vfs()
        r = vfs.read("/nonexistent", agent_ring=1)
        assert r.get("error_code") == "ENOENT"

    def test_ring_check_eacces(self):
        from kernel.vfs import get_vfs, MountType
        vfs = get_vfs()
        vfs.mount("/test", MountType.VIRTUAL, min_ring=2, read_only=False)
        r = vfs.read("/test/x", agent_ring=1)
        assert r.get("error_code") == "EACCES"


class TestDeviceManager:
    def test_rate_limiting(self):
        from kernel.device import get_device_manager, DeviceType, DeviceHealth
        dm = get_device_manager()
        dm.register("test-llm", DeviceType.LLM, rate_limit=3)
        assert dm.check_rate("test-llm").get("allowed")
        dm.record_call("test-llm")
        dm.record_call("test-llm")
        dm.record_call("test-llm")
        assert not dm.check_rate("test-llm").get("allowed"), "rate limit should block"

    def test_health_change(self):
        from kernel.device import get_device_manager, DeviceType, DeviceHealth
        dm = get_device_manager()
        dm.register("test-dev", DeviceType.LLM, rate_limit=10)
        dm.set_health("test-dev", DeviceHealth.DEGRADED)
        dev = dm.get("test-dev")
        assert dev is not None
        assert dev.health == DeviceHealth.DEGRADED


class TestToolChain:
    def test_fingerprint_chain(self):
        from kernel.tool_chain import get_tool_chain
        tc = get_tool_chain()
        pid = tc.start("composite", "agent-x", ring=2)
        cid = tc.child("atomic", "agent-y", ring=1, parent=pid)
        tc.complete(pid, True, 0.5)
        tc.complete(cid, True, 0.05)
        v = tc.verify(cid)
        assert v.get("valid"), "fingerprint chain should be valid"
        assert v.get("depth") == 2
        ancestry = tc.chain(cid)
        assert ancestry[-1].call_id == pid


class TestAllocator:
    def test_oom_trigger(self):
        from kernel.allocator import get_allocator
        a = get_allocator()
        a.set_limit("hog", "tokens", 100)
        r1 = a.alloc("hog", "tokens", 80)
        assert r1["success"]
        a.set_limit("victim", "tokens", 10)
        r2 = a.alloc("victim", "tokens", 100)
        assert r2.get("oom") is not None, "OOM should trigger on exhaustion"


class TestInterrupt:
    def test_fire(self):
        from kernel.interrupt import get_table as int_table, fire, InterruptType
        it = int_table()
        before = it.counts().get("AGENT_CRASH", 0)
        fire(InterruptType.AGENT_CRASH, agent_id="crash-test", reason="unit test")
        after = it.counts().get("AGENT_CRASH", 0)
        assert after == before + 1


class TestSettings:
    def test_defaults(self):
        from kernel.settings import get_settings, reset_settings
        s = get_settings()
        all_s = s.all()
        assert len(all_s) >= 20
        s.set("test.key", 42)
        assert s.get("test.key") == 42
        cat = s.category("llm")
        assert "llm.provider" in cat
        s.set_many({"a": 1, "b": 2})
        assert s.get("a") == 1
        s.reset("test.key")
        assert s.get("test.key") is None
        reset_settings()


class TestConstitution:
    def test_has_rules(self):
        from kernel.constitution import get_constitution
        cc = get_constitution()
        rules = cc.rules_list()
        assert len(rules) >= 10

    def test_allows_unknown_action(self):
        from kernel.constitution import get_constitution
        cc = get_constitution()
        r = cc.is_allowed("unknown_action", "anyone", "/tmp/test")
        assert r.get("allowed", True)

    def test_rule_descriptors_loaded(self):
        """Verify builtin rules use RuleDescriptor with ids and tags."""
        from kernel.constitution import get_constitution
        from kernel.rule_descriptor import RuleDescriptor
        cc = get_constitution()
        for rule in cc._rules:
            assert isinstance(rule, RuleDescriptor)
            assert rule.id, f"rule missing id: {rule.description}"

    def test_rules_have_unique_ids(self):
        from kernel.constitution import get_constitution
        cc = get_constitution()
        ids = [r.id for r in cc._rules]
        assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"

    def test_blocks_constitution_file_write(self):
        from kernel.constitution import get_constitution, reset_constitution
        reset_constitution()
        cc = get_constitution()
        r = cc.is_allowed("write_file", "agent-a", ".nomos-rules.md")
        assert not r.get("allowed")

    def test_blocks_constitution_keyword_path(self):
        from kernel.constitution import get_constitution
        cc = get_constitution()
        r = cc.is_allowed("write_file", "agent-a", "src/constitution.py")
        assert not r.get("allowed")

    def test_blocks_scout_write(self):
        from kernel.constitution import get_constitution
        cc = get_constitution()
        r = cc.is_allowed("write_file", "scout", "/tmp/test")
        assert not r.get("allowed")

    def test_allows_scout_read(self):
        from kernel.constitution import get_constitution
        cc = get_constitution()
        r = cc.is_allowed("read_file", "scout", "/tmp/test")
        assert r.get("allowed")

    def test_territory_block(self):
        from kernel.constitution import get_constitution
        cc = get_constitution()
        # read_file IS in CONSTITUTION_FILE_ACTIONS, so territory check applies
        r = cc.is_allowed("read_file", "agent-a", "/forbidden",
                          territory=["/allowed"])
        assert not r.get("allowed")

    def test_territory_allowed(self):
        from kernel.constitution import get_constitution
        cc = get_constitution()
        r = cc.is_allowed("read_file", "agent-a", "/allowed/src/main.py",
                          territory=["/allowed"])
        assert r.get("allowed")

    def test_rules_list_includes_all_builtins(self):
        from kernel.constitution import get_constitution
        cc = get_constitution()
        rules = cc.rules_list()
        descriptions = [r["description"] for r in rules]
        assert any("territory" in d.lower() for d in descriptions)
        assert any("GateChain" in d for d in descriptions)
        assert any("sandbox" in d.lower() for d in descriptions)
        assert any("scout" in d.lower() for d in descriptions)
        assert len(rules) == 15  # 15 built-in rules

    def test_load_custom_rules(self):
        from kernel.constitution import get_constitution, reset_constitution
        import tempfile, os
        reset_constitution()
        content = """# Custom Rules
## §custom
[MUST] Custom rule one
[SHOULD] Custom rule two
"""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        try:
            cc = get_constitution()
            r = cc.load(tmp.name)
            assert r.get("success")
            assert r.get("custom", 0) == 2
            assert len(cc._rules) == 15 + 2  # 15 builtins + 2 custom
        finally:
            os.unlink(tmp.name)
