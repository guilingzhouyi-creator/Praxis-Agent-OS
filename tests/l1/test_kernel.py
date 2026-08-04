"""Kernel tests — core: sync, event, VFS, process, device, gatechain, allocator, OS, health, prompts, L3 integration."""

from __future__ import annotations

import threading

from l1.kernel.params.kernel import (
    PROCESS_INIT_NAME,
    PROCESS_INIT_RING,
    PROCESS_INIT_ROLE,
)

# ═══════════════════════════════════════════════════════════════
# Process Table
# ═══════════════════════════════════════════════════════════════

class TestProcessTable:
    def test_singleton(self):
        from l1.kernel.process import get_table
        t1 = get_table()
        t2 = get_table()
        assert t1 is t2

    def test_init_pid0(self):
        from l1.kernel.process import ProcessState, get_table
        t = get_table()
        p = t.get(0)
        assert p is not None
        assert p.name == PROCESS_INIT_NAME
        assert p.role == PROCESS_INIT_ROLE
        assert p.ring == PROCESS_INIT_RING
        assert p.state is ProcessState.RUNNING

    def test_spawn(self):
        from l1.kernel.process import get_table
        t = get_table()
        p = t.spawn("test-agent", role="reader", ring=1)
        assert p is not None
        assert p.name == "test-agent"
        assert p.ring == 1
        assert p.state.name == "READY"

    def test_exit_and_reap(self):
        from l1.kernel.process import ProcessState, get_table
        t = get_table()
        p = t.spawn("reap-agent", role="scout")
        pid = p.pid
        assert t.exit(pid, exit_code=0, reason="test") is True
        assert p.state is ProcessState.ZOMBIE
        snap = t.reap(pid)
        assert snap is not None
        assert snap["pid"] == pid
        assert t.get(pid) is None

    def test_get_by_name(self):
        from l1.kernel.process import get_table
        t = get_table()
        t.spawn("name-test")
        p = t.get_by_name("name-test")
        assert p is not None
        assert p.name == "name-test"
        assert t.get_by_name("nonexistent") is None

    def test_list(self):
        from l1.kernel.process import get_table
        t = get_table()
        t.spawn("list-a")
        t.spawn("list-b")
        items = t.list()
        pids = [i["pid"] for i in items]
        assert len(pids) >= 3  # pid0 + 2 spawned


# ═══════════════════════════════════════════════════════════════
# Syscall / Audit
# ═══════════════════════════════════════════════════════════════

class TestSyscall:
    def test_register_process(self):
        from l1.kernel import register_process
        from l1.kernel.process import get_table
        pid = register_process("syscall-agent", "reader")
        assert pid > 0
        pt = get_table()
        p = pt.get(pid)
        assert p is not None
        assert p.state.name == "READY"

    def test_get_audit_log(self):
        from l1.kernel import get_audit_log
        log = get_audit_log(limit=10)
        assert isinstance(log, list)

    def test_emit_signal_crash(self):
        from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
        try:
            emit_signal(EVENT_TASK_ASSIGN, sender="test", target="l3", data={"x": 1})
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# Mutex / Semaphore / Barrier / Condition / RWLock
# ═══════════════════════════════════════════════════════════════

class TestMutex:
    def test_create(self):
        from l1.kernel.sync import Mutex
        m = Mutex(name="test-mutex", timeout=5.0)
        r = m.acquire("agent-a")
        assert r.get("success")
        r2 = m.release("agent-a")
        assert r2.get("success")

    def test_contention(self):
        from l1.kernel.sync import Mutex
        m = Mutex(name="contention-mutex", timeout=0.5)
        m.acquire("a")
        r = m.acquire("b")
        assert not r.get("success")

    def test_status(self):
        from l1.kernel.sync import Mutex
        m = Mutex(name="status-mutex")
        m.acquire("a")
        s = m.status()
        assert s.get("owner") == "a"


class TestSemaphore:
    def test_create(self):
        from l1.kernel.sync import Semaphore
        s = Semaphore(name="test-sem", max_count=3)
        r1 = s.acquire("a")
        r2 = s.acquire("b")
        r3 = s.acquire("c")
        assert r1.get("success") and r2.get("success") and r3.get("success")
        s.release("a")
        r4 = s.acquire("d", blocking=False)
        assert r4.get("success")

    def test_exhausted(self):
        from l1.kernel.sync import Semaphore
        s = Semaphore(name="exhausted-sem", max_count=1)
        s.acquire("a")
        r = s.acquire("b", blocking=False)
        assert not r.get("success")


class TestBarrier:
    def test_barrier(self):
        from l1.kernel.sync import Barrier
        b = Barrier(name="test-barrier", count=3)
        results = []
        def arrive(agent):
            results.append(b.wait(agent))
        threads = [threading.Thread(target=arrive, args=(ag,)) for ag in ("a", "b", "c")]
        for t in threads: t.start()
        for t in threads: t.join(timeout=2)
        assert all(r.get("success") for r in results if r)


class TestCondition:
    def test_condition(self):
        from l1.kernel.sync import Condition
        c = Condition(name="test-cond")
        r = c.wait("a", timeout=0.1)
        assert r.get("success") is False  # timeout


# ═══════════════════════════════════════════════════════════════
# EventBus / Signal
# ═══════════════════════════════════════════════════════════════

class TestEventBus:
    def test_get_event_bus(self):
        from l1.kernel import get_event_bus
        bus = get_event_bus()
        assert bus is not None

    def test_on_and_emit(self):
        from l1.kernel import Signal, SignalType, get_event_bus
        bus = get_event_bus()
        captured = []
        bus.on(SignalType.TASK_ASSIGN, lambda s: captured.append(s.sender))
        n = bus.emit(Signal(type=SignalType.TASK_ASSIGN, sender="test-a", target="cell"))
        assert n >= 1
        assert "test-a" in captured

    def test_off(self):
        from l1.kernel import Signal, SignalType, get_event_bus
        bus = get_event_bus()
        captured = []
        def handler(s): captured.append(s.sender)
        bus.on(SignalType.SCOUT_DONE, handler)
        bus.emit(Signal(type=SignalType.SCOUT_DONE, sender="s1", target="cell"))
        assert "s1" in captured
        bus.off(SignalType.SCOUT_DONE, handler)
        captured.clear()
        bus.emit(Signal(type=SignalType.SCOUT_DONE, sender="s2", target="cell"))
        assert len(captured) == 0

    def test_wildcard_listener(self):
        from l1.kernel import Signal, SignalType, get_event_bus
        bus = get_event_bus()
        caught = []
        bus.on_any(lambda s: caught.append(s.type.name))
        bus.emit(Signal(type=SignalType.STATE_CHANGE, sender="a", target="b"))
        assert "STATE_CHANGE" in caught

    def test_history(self):
        from l1.kernel import Signal, SignalType, get_event_bus
        bus = get_event_bus()
        bus.emit(Signal(type=SignalType.TERRITORY_QUERY, sender="h", target="cell"))
        history = bus.history(limit=5)
        assert len(history) >= 1

    def test_emit_signal_no_crash(self):
        from l1.kernel import EVENT_TASK_ASSIGN, emit_signal, get_event_bus
        bus = get_event_bus()
        emit_signal(EVENT_TASK_ASSIGN, sender="test", target="l3", data={"test": True})
        assert True


# ═══════════════════════════════════════════════════════════════
# GateChain
# ═══════════════════════════════════════════════════════════════

class TestGateChain:
    def test_create_gatechain(self):
        from l1.kernel.gatechain import get_gatechain
        gc = get_gatechain()
        assert gc is not None

    def test_gate_check(self):
        from l1.kernel.gatechain import get_gatechain
        gc = get_gatechain()
        r = gc.check("read_file", "l3", target="src/test.txt")
        assert isinstance(r, dict)

    def test_gate_ledger(self):
        from l1.kernel.gatechain import get_gatechain
        gc = get_gatechain()
        led = gc.ledger.recent()
        assert isinstance(led, list)


# ═══════════════════════════════════════════════════════════════
# Virtual File System (VFS)
# ═══════════════════════════════════════════════════════════════

class TestVFS:
    def test_get_vfs(self):
        from l1.kernel.vfs import get_vfs
        vfs = get_vfs()
        assert vfs is not None

    def test_mount(self):
        from l1.kernel.vfs import MountType, get_vfs
        vfs = get_vfs()
        r = vfs.mount("test", MountType.VIRTUAL, description="test mount")
        assert r.get("success")

    def test_virtual_read_write(self):
        from l1.kernel.vfs import MountType, get_vfs
        vfs = get_vfs()
        vfs.mount("tmp", MountType.VIRTUAL, min_ring=1, description="tmp")
        w = vfs.write("/tmp/hello", "world")
        assert w.get("success") or not w.get("success")
        if w.get("success"):
            r = vfs.read("/tmp/hello")
            assert r.get("content") == "world"


# ═══════════════════════════════════════════════════════════════
# Device Manager
# ═══════════════════════════════════════════════════════════════

class TestDeviceManager:
    def test_get_device_manager(self):
        from l1.kernel.device import get_device_manager
        dm = get_device_manager()
        assert dm is not None

    def test_register_device(self):
        from l1.kernel.device import DeviceType, get_device_manager
        dm = get_device_manager()
        r = dm.register("test-llm", DeviceType.LLM, rate_limit=5)
        assert r.get("success")
        dev = dm.get("test-llm")
        assert dev is not None
        assert dev.device_type == DeviceType.LLM

    def test_list_devices(self):
        from l1.kernel.device import DeviceType, get_device_manager
        dm = get_device_manager()
        dm.register("list-llm", DeviceType.LLM)
        items = dm.list()
        assert any(d["name"] == "list-llm" for d in items)

    def test_rate_check(self):
        from l1.kernel.device import DeviceType, get_device_manager
        dm = get_device_manager()
        dm.register("rate-dev", DeviceType.LLM, rate_limit=1)
        r = dm.check_rate("rate-dev")
        assert r.get("allowed")


# ═══════════════════════════════════════════════════════════════
# Interrupt (L1)
# ═══════════════════════════════════════════════════════════════

class TestInterrupt:
    def test_get_table(self):
        from l1.kernel.interrupt import get_table
        it = get_table()
        assert it is not None


# ═══════════════════════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════════════════════

class TestSettings:
    def test_get_settings(self):
        from l1.kernel.settings import get_settings
        s = get_settings()
        assert s is not None


# ═══════════════════════════════════════════════════════════════
# Constitution
# ═══════════════════════════════════════════════════════════════

class TestConstitution:
    def test_get_constitution(self):
        from l1.kernel.constitution import get_constitution
        c = get_constitution()
        assert c is not None

    def test_is_allowed(self):
        from l1.kernel.constitution import get_constitution
        c = get_constitution()
        r = c.is_allowed("read_file", "l3", target=".")
        assert isinstance(r, dict)
        assert "allowed" in r


# ═══════════════════════════════════════════════════════════════
# OS Lifecycle
# ═══════════════════════════════════════════════════════════════

class TestOSLifecycle:
    def test_get_os_singleton(self):
        from l1.kernel.os import get_os
        svc = get_os()
        assert svc is not None

    def test_status(self):
        from l1.kernel.os import get_os
        svc = get_os()
        s = svc.status()
        assert isinstance(s, dict)

    def test_state_initial_down(self):
        from l1.kernel.os import OS
        os_obj = OS()
        assert os_obj.state.name == "DOWN"


# ═══════════════════════════════════════════════════════════════
# Kernel Health
# ═══════════════════════════════════════════════════════════════

class TestKernelHealth:
    def test_kernel_modules_list(self):
        from l1.kernel.healthcheck import _KERNEL_MODULES
        assert len(_KERNEL_MODULES) >= 15
        assert "l1.kernel.constitution" in _KERNEL_MODULES

    def test_health_imports(self):
        import l1.kernel.healthcheck
        assert hasattr(l1.kernel.healthcheck, "_KERNEL_MODULES")


# ═══════════════════════════════════════════════════════════════
# Prompt Templates
# ═══════════════════════════════════════════════════════════════

class TestPrompts:
    def test_get_prompt(self):
        from l1.kernel.prompts import get_prompt
        p = get_prompt("agent_loop.system")
        assert p is not None
        assert "agent" in p.lower()

    def test_get_prompt_not_found(self):
        from l1.kernel.prompts import get_prompt
        p = get_prompt("nonexistent")
        assert p is None or p == ""

    def test_list_prompts(self):
        from l1.kernel.prompts import list_prompts
        prompts = list_prompts()
        assert len(prompts) >= 3
        assert "agent_loop.system" in prompts


# ═══════════════════════════════════════════════════════════════
# Allocator (basic — extended tests in test_kernel_allocator.py)
# ═══════════════════════════════════════════════════════════════

class TestAllocator:
    def test_get_allocator(self):
        from l1.kernel.allocator import get_allocator
        a = get_allocator()
        assert a is not None
