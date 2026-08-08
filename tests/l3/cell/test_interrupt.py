"""Tests for l3.cell.components.cell_interrupt — IRQ Controller."""

from __future__ import annotations

import time

import pytest

from l1.kernel.params.system import IRQ_TABLE_SIZE
from l3.cell.components.cell_interrupt import (
    InterruptController,
    IrqPriority,
)

# ── Fixtures ──


@pytest.fixture
def irq():
    """Fresh InterruptController with no PMU."""
    return InterruptController(cell_id="test-cell", pmu=None)


@pytest.fixture
def irq_with_pmu():
    """InterruptController with a mock PMU."""

    class FakePmu:
        def __init__(self):
            self.counts = {}

        def increment(self, name: str, delta: int = 1):
            self.counts[name] = self.counts.get(name, 0) + delta

    pmu = FakePmu()
    ctrl = InterruptController(cell_id="test-cell", pmu=pmu)
    return ctrl, pmu


# ── Built-in IRQ tests ──


class TestBuiltinIrqs:
    """17 built-in IRQs registered at init (0-16, incl. cell.rollback)."""

    def test_16_builtin_irqs(self, irq):
        """IRQs 0-16 pre-registered (17 total, cell.rollback added as IRQ16)."""
        stats = irq.stats()
        assert stats["registered_irqs"] == 17

    def test_builtin_nmi_priorities(self, irq):
        """IRQ 0-3 are NMI priority."""
        for n in range(4):
            slot = irq._table.get(n)
            assert slot is not None
            assert slot.priority == IrqPriority.NMI, f"IRQ{n} should be NMI"

    def test_builtin_high_priorities(self, irq):
        """IRQ 4-7 are HIGH priority."""
        for n in range(4, 8):
            slot = irq._table.get(n)
            assert slot is not None
            assert slot.priority == IrqPriority.HIGH, f"IRQ{n} should be HIGH"

    def test_builtin_low_priorities(self, irq):
        """IRQ 12-15 are LOW priority."""
        for n in range(12, 16):
            slot = irq._table.get(n)
            assert slot is not None
            assert slot.priority == IrqPriority.LOW, f"IRQ{n} should be LOW"

    def test_all_builtin_have_names(self, irq):
        """Every built-in IRQ has a non-empty name."""
        for n, s in irq._table.items():
            assert s.name, f"IRQ{n} has empty name"


# ── Registration tests ──


class TestRegister:
    """Register/unregister IRQ handlers."""

    def test_register_custom_irq(self, irq):
        r = irq.register(20, "custom.test", priority=IrqPriority.LOW)
        assert r["success"]
        assert irq._table[20].name == "custom.test"
        assert irq._table[20].priority == IrqPriority.LOW

    def test_register_out_of_range(self, irq):
        r = irq.register(99, "invalid")
        assert not r["success"]
        assert "out of range" in r.get("error", "")

    def test_register_negative(self, irq):
        r = irq.register(-1, "invalid")
        assert not r["success"]

    def test_register_duplicate(self, irq):
        irq.register(20, "first")
        r = irq.register(20, "duplicate")
        assert not r["success"]
        assert "already registered" in r.get("error", "")

    def test_unregister(self, irq):
        irq.register(20, "temp")
        r = irq.unregister(20)
        assert r["success"]
        assert 20 not in irq._table

    def test_unregister_missing(self, irq):
        r = irq.unregister(99)
        assert not r["success"]

    def test_register_with_handler(self, irq):
        """Handler registered on non-NMI IRQ is called after dispatch."""
        handler_called = []

        def handler(ev):
            handler_called.append(ev)

        irq.register(20, "with_handler", handler=handler)
        irq.trigger(20)
        irq.dispatch_pending()  # non-NMI IRQs need explicit dispatch
        assert len(handler_called) == 1


# ── Trigger tests ──


class TestTrigger:
    """Interrupt triggering — NMI vs queued, by number vs name."""

    def test_trigger_nmi_inline(self, irq):
        """NMI fires handler immediately."""
        calls = []

        def handler(ev):
            calls.append(ev.data)

        irq.set_handler(0, handler)  # IRQ0 = watchdog.crash (NMI)
        r = irq.trigger(0, data="crash_info")
        assert r["delivery"] == "nmi"
        assert len(calls) == 1
        assert calls[0] == "crash_info"

    def test_trigger_queued(self, irq):
        """Non-NMI is queued, not dispatched."""
        r = irq.trigger(4, data="hello")  # IRQ4 = task.complete (HIGH)
        assert r["delivery"] == "queued"
        stats = irq.stats()
        assert stats["pending_by_priority"]["high"] == 1

    def test_trigger_by_name(self, irq):
        """Trigger by slot name string."""
        r = irq.trigger("task.complete")
        assert r["delivery"] == "queued"

    def test_trigger_unknown(self, irq):
        r = irq.trigger(99)
        assert not r["success"]
        assert "unknown" in r.get("error", "")

    def test_trigger_unknown_name(self, irq):
        r = irq.trigger("nonexistent.irq")
        assert not r["success"]

    def test_trigger_masked_dropped(self, irq):
        from l2.i18n import t as _t

        irq.mask(4)
        r = irq.trigger(4)
        assert not r["success"]
        assert r.get("error") == _t("core.interrupt_masked")

    def test_trigger_increments_counter(self, irq):
        irq.trigger(0)
        irq.trigger(4)
        irq.trigger(8)
        stats = irq.stats()
        assert stats["total_triggered"] == 3
        assert stats["irqs"]["IRQ0"]["triggered"] == 1


# ── Dispatch tests ──


class TestDispatch:
    """Pending interrupt dispatch — priority ordering."""

    def test_dispatch_highest_priority_first(self, irq):
        """Queue HIGH, NORMAL, LOW; dispatch should process HIGH first."""
        dispatched = []
        irq.set_handler(4, lambda e: dispatched.append(("high", e.irq_num)))
        irq.set_handler(8, lambda e: dispatched.append(("norm", e.irq_num)))
        irq.set_handler(12, lambda e: dispatched.append(("low", e.irq_num)))
        irq.trigger(12)  # LOW
        irq.trigger(8)  # NORMAL
        irq.trigger(4)  # HIGH
        count = irq.dispatch_pending(max_total=5)
        assert count == 3
        assert dispatched[0][0] == "high"
        assert dispatched[1][0] == "norm"
        assert dispatched[2][0] == "low"

    def test_dispatch_respects_mask(self, irq):
        irq.set_handler(4, lambda e: None)
        irq.mask(4)
        irq.trigger(4)
        count = irq.dispatch_pending()
        assert count == 0  # masked interrupts skipped

    def test_dispatch_multiple_same_priority(self, irq):
        calls = []
        irq.set_handler(4, lambda e: calls.append("a"))
        irq.set_handler(5, lambda e: calls.append("b"))
        irq.trigger(4)
        irq.trigger(5)
        count = irq.dispatch_pending()
        assert count == 2
        assert len(calls) == 2

    def test_dispatch_empty(self, irq):
        count = irq.dispatch_pending()
        assert count == 0

    def test_dispatch_max_per_priority(self, irq):
        """max_total caps total dispatched across all priority levels."""
        for _ in range(10):
            irq.trigger(4)  # HIGH
            irq.trigger(8)  # NORMAL
        # max_total is a global cap, not per-priority
        count = irq.dispatch_pending(max_total=3)
        assert count == 3  # total cap, not per-priority


# ── Mask / Unmask tests ──


class TestMaskUnmask:
    """IRQ masking."""

    def test_mask(self, irq):
        r = irq.mask(4)
        assert r["success"]
        assert irq._table[4].masked is True

    def test_unmask(self, irq):
        irq.mask(4)
        r = irq.unmask(4)
        assert r["success"]
        assert irq._table[4].masked is False

    def test_mask_nmi_fails(self, irq):
        r = irq.mask(0)
        assert not r["success"]
        assert "cannot mask NMI" in r.get("error", "")

    def test_mask_unknown(self, irq):
        r = irq.mask(99)
        assert not r["success"]


# ── Set handler tests ──


class TestSetHandler:
    """Handler assignment."""

    def test_set_handler(self, irq):
        calls = []

        def handler(ev):
            calls.append(ev.data)

        r = irq.set_handler(4, handler)
        assert r["success"]
        irq.trigger(4, data="test")
        irq.dispatch_pending()
        assert len(calls) == 1

    def test_set_handler_unknown(self, irq):
        r = irq.set_handler(99, lambda e: None)
        assert not r["success"]

    def test_set_handler_by_name(self, irq):
        calls = []
        irq.set_handler("task.complete", lambda e: calls.append(1))
        irq.trigger(4)
        irq.dispatch_pending()
        assert len(calls) == 1


# ── Stats tests ──


class TestStats:
    """Statistics reporting."""

    def test_stats_shape(self, irq):
        stats = irq.stats()
        assert stats["cell_id"] == "test-cell"
        assert "total_triggered" in stats
        assert "total_handled" in stats
        assert "registered_irqs" in stats
        assert "pending_by_priority" in stats
        assert "irqs" in stats

    def test_stats_tracks_handled(self, irq):
        irq.set_handler(4, lambda e: None)
        irq.trigger(4)
        irq.dispatch_pending()
        stats = irq.stats()
        assert stats["total_handled"] == 1
        assert stats["irqs"]["IRQ4"]["handled"] == 1

    def test_stats_pending_by_priority(self, irq):
        irq.trigger(8)  # NORMAL
        irq.trigger(12)  # LOW
        stats = irq.stats()
        assert stats["pending_by_priority"]["normal"] == 1
        assert stats["pending_by_priority"]["low"] == 1


# ── PMU integration tests ──


class TestPmuIntegration:
    """PMU counter integration."""

    def test_pmu_trigger_increments(self, irq_with_pmu):
        ctrl, pmu = irq_with_pmu
        ctrl.trigger(8)  # NORMAL
        assert pmu.counts.get("interrupt.triggered.normal") == 1

    def test_pmu_handle_increments(self, irq_with_pmu):
        ctrl, pmu = irq_with_pmu
        ctrl.set_handler(8, lambda e: None)
        ctrl.trigger(8)
        ctrl.dispatch_pending()
        assert pmu.counts.get("interrupt.handled.normal") == 1

    def test_pmu_nmi_trigger(self, irq_with_pmu):
        ctrl, pmu = irq_with_pmu
        ctrl.set_handler(0, lambda e: None)
        ctrl.trigger(0)
        # NMI doesn't increment per-priority PMU counters
        assert ctrl.stats()["total_triggered"] == 1


# ── Thread safety tests ──


class TestThreadSafety:
    """Concurrent access from multiple threads."""

    def test_parallel_trigger(self, irq):
        import threading

        errors = []

        def worker(n):
            try:
                for _ in range(20):
                    irq.trigger(8, data=n)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        stats = irq.stats()
        assert stats["total_triggered"] == 80

    def test_parallel_dispatch(self, irq):
        import threading

        irq.set_handler(4, lambda e: None)
        irq.set_handler(8, lambda e: None)

        def triggerer():
            for _ in range(50):
                irq.trigger(4)
                irq.trigger(8)

        def dispatcher():
            for _ in range(10):
                irq.dispatch_pending(max_total=5)

        threads = [threading.Thread(target=triggerer) for _ in range(2)]
        threads += [threading.Thread(target=dispatcher) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stats = irq.stats()
        assert stats["total_triggered"] >= 100


# ── Edge case tests ──


class TestEdgeCases:
    """Boundary conditions."""

    def test_register_at_table_limit(self, irq):
        r = irq.register(IRQ_TABLE_SIZE - 1, "last_slot")
        assert r["success"]

    def test_register_beyond_table_limit(self, irq):
        r = irq.register(IRQ_TABLE_SIZE, "beyond")
        assert not r["success"]

    def test_resolve_by_name_case_sensitive(self, irq):
        slot = irq._resolve_slot("WATCHDOG.CRASH")
        assert slot is None  # name is lowercase

    def test_event_timestamp_set(self, irq):
        before = time.time()
        irq.trigger(4)
        after = time.time()
        ev = irq._pending[IrqPriority.HIGH][0]
        assert before <= ev.timestamp <= after
