"""Tests for l3.cell.components.cell_pmu — Performance Monitoring Unit."""

from __future__ import annotations

import time

import pytest

from l3.cell.components.cell_pmu import CellPmu


@pytest.fixture
def pmu():
    """Fresh CellPmu with default groups."""
    return CellPmu(cell_id="test-cell")


@pytest.fixture
def pmu_limited():
    """CellPmu with only the 'cards' group enabled."""
    return CellPmu(cell_id="test-cell", enabled_groups=["cards"])


class TestInit:
    """PMU initialization."""

    def test_all_groups_enabled_by_default(self, pmu):
        """12 counter groups from PMU_COUNTER_GROUPS initialized."""
        stats = pmu.stats()
        assert len(stats["enabled_groups"]) == 12
        assert "cards" in stats["enabled_groups"]
        assert "tools" in stats["enabled_groups"]
        assert "cache" in stats["enabled_groups"]
        assert "memory" in stats["enabled_groups"]
        assert "icache" in stats["enabled_groups"]
        assert "tlb" in stats["enabled_groups"]
        assert "interrupt" in stats["enabled_groups"]

    def test_all_counters_start_at_zero(self, pmu):
        stats = pmu.stats()
        for name, val in stats["counters"].items():
            assert val == 0, f"{name} should start at 0, got {val}"

    def test_limited_groups(self, pmu_limited):
        """Only specified group counters are initialized."""
        stats = pmu_limited.stats()
        assert stats["enabled_groups"] == ["cards"]
        assert "cards.dispatched" in stats["counters"]
        assert "tools.executed.ring_1" not in stats["counters"]

    def test_counter_names_known(self, pmu):
        """All predefined counters exist."""
        expected = [
            "cards.dispatched", "cards.completed", "cards.rolled_back",
            "cards.decomposed", "cards.failed",
            "tools.executed.ring_1", "tools.executed.ring_2_5",
            "tools.executed.ring_3", "tools.rejected",
            "cache.hits", "cache.misses", "cache.injections",
            "cache.flushes", "cache.promotions",
        ]
        for name in expected:
            assert name in pmu._counters, f"Missing counter: {name}"


class TestIncrement:
    """Counter increment operations."""

    @pytest.mark.parametrize("counter", [
        "cards.dispatched", "cards.completed", "cards.rolled_back",
        "tools.executed.ring_1", "cache.hits", "cache.misses",
        "scouts.spawned", "bus.messages_sent",
        "token.consumed", "agent.boots",
        "watchdog.timeouts",
    ])
    def test_increment_by_one(self, pmu, counter):
        pmu.increment(counter)
        assert pmu.read(counter) == 1

    def test_increment_by_delta(self, pmu):
        pmu.increment("cards.completed", delta=5)
        assert pmu.read("cards.completed") == 5

    def test_increment_multiple_times(self, pmu):
        for _ in range(10):
            pmu.increment("cache.hits")
        assert pmu.read("cache.hits") == 10

    def test_unknown_group_ignored(self, pmu):
        """Counter in disabled/nonexistent group is silently ignored."""
        pmu.increment("nonexistent.counter")
        assert pmu.read("nonexistent.counter") == 0

    def test_increment_limited_group(self, pmu_limited):
        pmu_limited.increment("cards.completed")
        assert pmu_limited.read("cards.completed") == 1
        pmu_limited.increment("tools.executed.ring_1")
        assert pmu_limited.read("tools.executed.ring_1") == 0  # ignored


class TestRead:
    """Counter reading."""

    def test_read_returns_zero_for_unknown(self, pmu):
        assert pmu.read("unknown.counter") == 0

    def test_read_group(self, pmu):
        pmu.increment("cards.dispatched")
        pmu.increment("cards.completed")
        group = pmu.read_group("cards")
        assert group["cards.dispatched"] == 1
        assert group["cards.completed"] == 1

    def test_read_group_returns_empty_for_unknown(self, pmu):
        assert pmu.read_group("nonexistent") == {}


class TestSnapshot:
    """Point-in-time snapshots."""

    def test_snapshot_returns_initial_state(self, pmu):
        snap = pmu.snapshot(force=True)
        assert snap is not None
        assert snap.cell_id == "test-cell"
        assert isinstance(snap.timestamp, float)
        assert snap.counters["cards.dispatched"] == 0

    def test_snapshot_captures_changes(self, pmu):
        pmu.increment("cards.completed", delta=3)
        snap = pmu.snapshot(force=True)
        assert snap.counters["cards.completed"] == 3

    def test_snapshot_rate_limited(self, pmu):
        """Snapshot without force respects snapshot_interval."""
        s1 = pmu.snapshot(force=True)
        assert s1 is not None
        s2 = pmu.snapshot(force=False)  # too soon, returns None
        assert s2 is None

    def test_snapshot_history(self, pmu):
        pmu.snapshot(force=True)
        time.sleep(0.01)
        pmu.increment("cards.completed")
        pmu.snapshot(force=True)
        history = pmu.query_history()
        assert len(history) == 2

    def test_snapshot_history_with_name_filter(self, pmu):
        pmu.snapshot(force=True)
        time.sleep(0.01)
        pmu.increment("cards.completed")
        pmu.snapshot(force=True)
        history = pmu.query_history(name="cards.completed")
        assert len(history) == 2

    def test_snapshot_history_limit(self, pmu):
        for _ in range(5):
            pmu.snapshot(force=True)
            time.sleep(0.01)
        history = pmu.query_history(limit=3)
        assert len(history) == 3


class TestDeltaRate:
    """Delta and rate computations."""

    def test_delta_returns_zero_without_history(self, pmu):
        assert pmu.delta("cards.completed") == 0

    def test_delta_after_snapshots(self, pmu):
        """delta() needs a snapshot older than 'seconds' to compute difference."""
        pmu.snapshot(force=True)                      # snap 1 at t≈now
        # Backdate the first snapshot so delta sees it as "old"
        old_snap = pmu._history[-1]
        old_snap.timestamp = time.time() - 10000
        pmu.increment("cards.completed", delta=5)
        pmu.snapshot(force=True)                      # snap 2 at t≈now
        d = pmu.delta("cards.completed", seconds=9999)
        assert d == 5

    def test_rate_after_snapshots(self, pmu):
        pmu.snapshot(force=True)
        old_snap = pmu._history[-1]
        old_snap.timestamp = time.time() - 10000
        pmu.increment("cards.completed", delta=10)
        pmu.snapshot(force=True)
        r = pmu.rate("cards.completed", seconds=9999)
        assert r == pytest.approx(10.0 / 9999, abs=0.01)

    def test_rate_large_delta(self, pmu):
        pmu.snapshot(force=True)
        old_snap = pmu._history[-1]
        old_snap.timestamp = time.time() - 10000
        pmu.increment("cards.completed", delta=3600)
        pmu.snapshot(force=True)
        r = pmu.rate("cards.completed", seconds=9999)
        assert r == pytest.approx(3600.0 / 9999, abs=0.01)


class TestReset:
    """Counter reset."""

    def test_reset_single_counter(self, pmu):
        pmu.increment("cards.dispatched", delta=5)
        pmu.reset("cards.dispatched")
        assert pmu.read("cards.dispatched") == 0

    def test_reset_all(self, pmu):
        pmu.increment("cards.dispatched")
        pmu.increment("cache.hits")
        pmu.reset()
        assert pmu.read("cards.dispatched") == 0
        assert pmu.read("cache.hits") == 0

    def test_reset_clears_history(self, pmu):
        pmu.snapshot(force=True)
        pmu.reset()
        assert len(pmu._history) == 0


class TestStats:
    """Statistics reporting."""

    def test_stats_shape(self, pmu):
        stats = pmu.stats()
        assert stats["cell_id"] == "test-cell"
        assert "counters" in stats
        assert "history_entries" in stats
        assert "history_capacity" in stats
        assert "enabled_groups" in stats
        assert "uptime" in stats


class TestConcurrency:
    """Thread safety."""

    def test_parallel_increment(self, pmu):
        import threading
        errors = []
        def worker():
            try:
                for _ in range(100):
                    pmu.increment("cards.completed")
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(errors) == 0
        assert pmu.read("cards.completed") == 400

    def test_parallel_snapshot(self, pmu):
        import threading
        def worker():
            for _ in range(10):
                pmu.increment("cards.completed")
                pmu.snapshot(force=True)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert pmu.read("cards.completed") == 40
        assert len(pmu._history) <= pmu._history_size
