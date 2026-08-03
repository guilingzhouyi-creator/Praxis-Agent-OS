"""Tests for l3.cell.components.cell_watchdog — per-agent watchdog timer."""

from __future__ import annotations

import time

import pytest

from l3.cell.components.cell_watchdog import CellWatchdog, WatchdogState


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


class TestWatchdogCellIntegration:
    """Cell × Watchdog 集成测试 — Cell 正确接线 watchdog 回调并响应 timeout/crash.

    使用模拟的 Cell 风格回调来验证 Cell 的接线模式，
    避免创建完整 Cell 对象所需的复杂依赖注入。
    """

    def test_cell_style_wiring(self):
        """验证 Cell 风格的 on_timeout/on_crash/on_recovery 接线模式。"""
        wd = CellWatchdog(cell_id="test-cell", poll_interval=0.05, default_timeout=0.1)
        calls = {"timeout": [], "crash": [], "recovery": []}

        wd.on_timeout = lambda aid, state: calls["timeout"].append((aid, state.name))
        wd.on_crash = lambda aid: calls["crash"].append(aid)
        wd.on_recovery = lambda aid: calls["recovery"].append(aid)

        wd.register("agent-a", timeout=0.05)
        wd._tick()  # within timeout, should be HEALTHY
        assert len(calls["timeout"]) == 0, "should not fire timeout yet"

        # 模拟超时
        wd._slots["agent-a"].last_pet = time.time() - 10
        wd._tick()
        assert len(calls["timeout"]) == 1, "on_timeout should fire"
        assert calls["timeout"][0][0] == "agent-a"
        assert calls["timeout"][0][1] == "UNRESPONSIVE"

        # 模拟 crash：在 UNRESPONSIVE 基础上继续漏 tick
        slot = wd._slots["agent-a"]
        slot.state = WatchdogState.UNRESPONSIVE
        slot.consecutive_misses = wd._unresponsive_escalation
        slot.last_pet = time.time() - 10
        wd._tick()
        assert len(calls["crash"]) == 1, "on_crash should fire"
        assert calls["crash"][0] == "agent-a"

        # 模拟 recovery：pet() 在 CRASHED/UNRESPONSIVE 后恢复
        wd2 = CellWatchdog(cell_id="test-cell")
        wd2.on_recovery = lambda aid: calls["recovery"].append(aid)
        wd2.register("agent-b", timeout=60.0)
        wd2._slots["agent-b"].state = WatchdogState.UNRESPONSIVE
        wd2.pet("agent-b")
        assert len(calls["recovery"]) == 1, "on_recovery should fire"
        assert calls["recovery"][0] == "agent-b"
        assert wd2._slots["agent-b"].state == WatchdogState.HEALTHY

    def test_timeout_then_pet_recovers(self):
        """Watchdog timeout 后 pet() 应触发 recovery 并恢复 HEALTHY 状态。"""
        wd = CellWatchdog(cell_id="test-cell", poll_interval=0.05, default_timeout=0.1)
        states = []
        wd.on_timeout = lambda aid, s: states.append(("timeout", aid))
        wd.on_recovery = lambda aid: states.append(("recovery", aid))

        wd.register("agent-a", timeout=0.05)
        wd._slots["agent-a"].last_pet = time.time() - 10
        wd._tick()
        assert ("timeout", "agent-a") in states
        assert wd._slots["agent-a"].state == WatchdogState.UNRESPONSIVE

        wd.pet("agent-a")
        assert ("recovery", "agent-a") in states
        assert wd._slots["agent-a"].state == WatchdogState.HEALTHY

    def test_crash_then_pet_does_not_recover(self):
        """CRASHED 状态的 agent pet() 不应自动恢复（需要外部干预）。"""
        wd = CellWatchdog(cell_id="test-cell", poll_interval=0.05, default_timeout=0.1)
        wd.register("agent-a", timeout=0.05)
        slot = wd._slots["agent-a"]
        slot.last_pet = time.time() - 10
        slot.state = WatchdogState.UNRESPONSIVE
        slot.consecutive_misses = wd._unresponsive_escalation
        wd._tick()
        assert slot.state == WatchdogState.CRASHED

        wd.pet("agent-a")  # CRASHED 时不触发 recovery
        assert slot.state == WatchdogState.CRASHED
