"""Tests for l3.cell.components.cell_watchdog — per-agent watchdog timer."""

from __future__ import annotations

import time

import pytest

from l3.cell.components.cell_watchdog import CellWatchdog, WatchdogState, WatchdogSlot


@pytest.fixture
def wd():
    """Watchdog with very short poll/timeout for quick tests."""
    return CellWatchdog(cell_id="test-cell", poll_interval=0.05, default_timeout=0.1)


class _FakePmu:
    def __init__(self):
        self.counts = {}
    def increment(self, name, delta=1):
        self.counts[name] = self.counts.get(name, 0) + delta


class TestInit:
    def test_empty_on_create(self, wd):
        s = wd.status()
        assert len(s["slots"]) == 0
        assert s["running"] is False
        assert s["cell_id"] == "test-cell"

    def test_not_running_initially(self, wd):
        assert wd._running is False
        assert wd._thread is None


class TestRegister:
    def test_register_agent(self, wd):
        wd.register("agent-a", timeout=10.0)
        s = wd.status()
        assert "agent-a" in s["slots"]
        assert s["slots"]["agent-a"]["state"] == "HEALTHY"
        assert s["slots"]["agent-a"]["timeout"] == 10.0

    def test_register_uses_default_timeout(self, wd):
        wd.register("agent-a")
        s = wd.status()
        assert s["slots"]["agent-a"]["timeout"] == 0.1  # default_timeout

    def test_register_multiple_agents(self, wd):
        wd.register("agent-a")
        wd.register("agent-b")
        assert len(wd.status()["slots"]) == 2

    def test_unregister(self, wd):
        wd.register("agent-a")
        wd.unregister("agent-a")
        assert "agent-a" not in wd.status()["slots"]

    def test_unregister_nonexistent(self, wd):
        wd.unregister("nonexistent")  # should not raise


class TestPet:
    def test_pet_resets_timer(self, wd):
        wd.register("agent-a", timeout=60.0)
        before = wd._slots["agent-a"].last_pet
        time.sleep(0.01)
        wd.pet("agent-a")
        after = wd._slots["agent-a"].last_pet
        assert after > before

    def test_pet_nonexistent_agent(self, wd):
        wd.pet("nonexistent")  # should not raise

    def test_pet_recovers_unresponsive(self, wd):
        """pet() on an UNRESPONSIVE agent restores HEALTHY."""
        wd.register("agent-a", timeout=0.05)
        callbacks = []
        wd.on_recovery = lambda aid: callbacks.append(aid)
        wd._slots["agent-a"].state = WatchdogState.UNRESPONSIVE
        wd.pet("agent-a")
        assert wd._slots["agent-a"].state == WatchdogState.HEALTHY
        assert callbacks == ["agent-a"]

    def test_pet_clears_consecutive_misses(self, wd):
        wd.register("agent-a", timeout=0.05)
        slot = wd._slots["agent-a"]
        slot.consecutive_misses = 5
        wd.pet("agent-a")
        assert slot.consecutive_misses == 0

    def test_pet_increments_pmu(self):
        pmu = _FakePmu()
        wd = CellWatchdog(cell_id="test", pmu=pmu)
        wd.register("agent-a", timeout=60.0)
        wd.pet("agent-a")
        assert pmu.counts.get("watchdog.pets", 0) >= 1


class TestTimeout:
    """Watchdog timeout escalation — HEALTHY→UNRESPONSIVE→CRASHED."""

    def test_timeout_escalates_to_unresponsive(self, wd):
        wd.register("agent-a", timeout=0.05)
        callbacks = []
        wd.on_timeout = lambda aid, state: callbacks.append((aid, state))
        # Manually set last_pet far in the past
        wd._slots["agent-a"].last_pet = time.time() - 10
        wd._tick()
        assert wd._slots["agent-a"].state == WatchdogState.UNRESPONSIVE
        assert len(callbacks) == 1
        assert callbacks[0][0] == "agent-a"

    def test_timeout_escalates_to_crashed(self, wd):
        wd.register("agent-a", timeout=0.05)
        crash_calls = []
        wd.on_crash = lambda aid: crash_calls.append(aid)
        # Set consecutive misses to trigger CRASHED
        slot = wd._slots["agent-a"]
        slot.last_pet = time.time() - 10
        slot.state = WatchdogState.UNRESPONSIVE
        slot.consecutive_misses = wd._unresponsive_escalation
        wd._tick()
        assert slot.state == WatchdogState.CRASHED
        assert len(crash_calls) == 1

    def test_healthy_agent_not_timed_out(self, wd):
        wd.register("agent-a", timeout=60.0)
        wd._tick()  # within timeout
        assert wd._slots["agent-a"].state == WatchdogState.HEALTHY

    def test_timeout_increments_pmu(self):
        pmu = _FakePmu()
        wd = CellWatchdog(cell_id="test", default_timeout=0.05, pmu=pmu)
        wd.register("agent-a", timeout=0.05)
        wd._slots["agent-a"].last_pet = time.time() - 10
        wd._tick()
        assert pmu.counts.get("watchdog.timeouts", 0) >= 1


class TestTick:
    def test_tick_idempotent(self, wd):
        wd.register("agent-a", timeout=60.0)
        before = wd.status()["slots"]["agent-a"]["state"]
        wd._tick()
        wd._tick()
        after = wd.status()["slots"]["agent-a"]["state"]
        assert before == after == "HEALTHY"

    def test_tick_multi_agent(self, wd):
        wd.register("agent-a", timeout=60.0)
        wd.register("agent-b", timeout=0.05)
        wd._slots["agent-b"].last_pet = time.time() - 10
        wd._tick()
        assert wd._slots["agent-a"].state == WatchdogState.HEALTHY
        assert wd._slots["agent-b"].state == WatchdogState.UNRESPONSIVE


class TestStartStop:
    """Background thread lifecycle."""

    def test_start_creates_thread(self, wd):
        wd.start()
        assert wd._running is True
        assert wd._thread is not None
        assert wd._thread.is_alive()
        wd.stop()

    def test_stop_stops_thread(self, wd):
        wd.start()
        wd.stop()
        assert wd._running is False

    def test_start_idempotent(self, wd):
        wd.start()
        t = wd._thread
        wd.start()  # second start should be noop
        assert wd._thread is t
        wd.stop()


class TestStatus:
    def test_status_shape(self, wd):
        s = wd.status()
        assert "cell_id" in s
        assert "running" in s
        assert "poll_interval" in s
        assert "default_timeout" in s
        assert "slots" in s

    def test_status_after_register(self, wd):
        wd.register("agent-a", timeout=5.0)
        s = wd.status()
        slot = s["slots"]["agent-a"]
        assert slot["state"] == "HEALTHY"
        assert slot["timeout"] == 5.0
        assert slot["consecutive_misses"] == 0

    def test_status_after_timeout(self, wd):
        wd.register("agent-a", timeout=0.05)
        wd._slots["agent-a"].last_pet = time.time() - 10
        wd._tick()
        s = wd.status()
        assert s["slots"]["agent-a"]["state"] == "UNRESPONSIVE"


class TestAgentHealthy:
    def test_healthy_returns_true(self, wd):
        wd.register("agent-a")
        assert wd.agent_healthy("agent-a") is True

    def test_healthy_unknown_agent_false(self, wd):
        assert wd.agent_healthy("nonexistent") is False

    def test_healthy_unresponsive_false(self, wd):
        wd.register("agent-a", timeout=0.05)
        wd._slots["agent-a"].last_pet = time.time() - 10
        wd._tick()
        assert wd.agent_healthy("agent-a") is False


class TestConcurrency:
    def test_parallel_pet(self, wd):
        import threading
        wd.register("agent-a", timeout=60.0)
        errors = []
        def worker():
            try:
                for _ in range(50):
                    wd.pet("agent-a")
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(errors) == 0
