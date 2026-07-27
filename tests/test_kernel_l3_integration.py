"""L1 Kernel ↔ L3 集成测试 — gatechain → constitution → tool_pipeline → alloc → lock → audit。

验证 L1 内核层与 L3 层之间的关键交互通路可用且返回结构化结果。
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestGateChainIntegration:
    """GateChain G1-G5 与 L3 的集成"""

    def test_get_gatechain(self):
        from l1.kernel.gatechain import get_gatechain
        gc = get_gatechain()
        assert gc is not None

    def test_gate_check(self):
        from l1.kernel.gatechain import get_gatechain
        gc = get_gatechain()
        r = gc.check("read_file", "l3", target="src/test.txt")
        assert isinstance(r, dict)


class TestConstitutionIntegration:
    """Constitution 规则引擎与 L3 的集成"""

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


class TestAllocatorIntegration:
    """Allocator token 分配"""

    def test_get_allocator(self):
        from l1.kernel.allocator import get_allocator
        a = get_allocator()
        assert a is not None

    def test_alloc_tokens(self):
        from l1.kernel.allocator import get_allocator
        a = get_allocator()
        assert a is not None
        assert hasattr(a, 'alloc')


class TestSyncIntegration:

    def test_mutex_basic(self):
        from l1.kernel.sync import Mutex
        m = Mutex(name="test-mutex")
        assert m is not None
        assert hasattr(m, 'acquire')
        assert hasattr(m, 'release')

    def test_semaphore_basic(self):
        from l1.kernel.sync import Semaphore
        s = Semaphore(name="test-sem")
        assert s is not None

    def test_rwlock_basic(self):
        from l1.kernel.sync import RWLock
        rw = RWLock(name="test-rwlock")
        assert rw is not None
        assert hasattr(rw, 'read_lock')
        assert hasattr(rw, 'write_lock')


class TestEventBusIntegration:

    def test_emit_signal_no_crash(self):
        from l1.kernel import emit_signal, get_event_bus, EVENT_TASK_ASSIGN
        bus = get_event_bus()
        emit_signal(EVENT_TASK_ASSIGN, sender="test", target="l3",
                    data={"test": True})
        assert True


class TestAuditIntegration:
    """Syscall 审计追踪"""

    def test_audit_log(self):
        from l1.kernel import get_audit_log
        log = get_audit_log(limit=10)
        assert isinstance(log, list)

    def test_register_process(self):
        from l1.kernel import register_process
        from l1.kernel.process import get_table
        pid = register_process("test-agent", "test")
        assert pid > 0
        pt = get_table()
        proc = pt.get(pid)
        assert proc is not None
