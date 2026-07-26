"""MonitorBus unit test — ring buffer / JSONL persistence / stats semantics (M2-B)."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.monitor_bus import MonitorBus, MonitorEvent, _match_type


def _ev(type_: str = "kernel.test", severity: str = "info", **kw) -> MonitorEvent:
    return MonitorEvent(type=type_, source="t", severity=severity, **kw)


class TestRingBuffer:
    """Ring buffer eviction semantics."""

    def test_ring_evicts_oldest_when_full(self):
        bus = MonitorBus(ring_size=3)
        for i in range(5):
            bus.emit(_ev(type_="kernel.test"))
        assert len(bus._ring) == 3
        # Oldest two evicted, ring keeps last three
        assert bus._count == 5

    def test_emit_notifies_sse_listeners(self):
        bus = MonitorBus(ring_size=10)
        received: list[MonitorEvent] = []
        bus.subscribe_sse(lambda ev: received.append(ev))
        bus.emit(_ev())
        assert len(received) == 1
        bus.unsubscribe_sse(received.append)

    def test_subscribe_unsubscribe_threadsafe(self):
        """M1: subscribe/unsubscribe under lock; remove of unknown is tolerated."""
        bus = MonitorBus(ring_size=10)
        cb = lambda ev: None
        bus.subscribe_sse(cb)
        bus.unsubscribe_sse(cb)
        # Repeated unsubscribe must not raise
        bus.unsubscribe_sse(cb)
        assert cb not in bus._sse_listeners


class TestQuery:
    """Query filtering with type-prefix glob."""

    def test_query_type_prefix_glob(self):
        bus = MonitorBus(ring_size=10)
        bus.emit(_ev(type_="network.peer.join"))
        bus.emit(_ev(type_="kernel.interrupt"))
        net = bus.query(type_prefix="network.*")
        assert len(net) == 1
        assert net[0]["type"] == "network.peer.join"

    def test_query_severity_and_limit(self):
        bus = MonitorBus(ring_size=10)
        for _ in range(5):
            bus.emit(_ev(severity="warn"))
        results = bus.query(severity="warn", limit=3)
        assert len(results) == 3
        assert all(r["severity"] == "warn" for r in results)


class TestMatchType:
    """_match_type helper — supports exact and '.*' glob."""

    def test_exact_match(self):
        assert _match_type("kernel.interrupt", "kernel.interrupt")

    def test_glob_match_prefix(self):
        assert _match_type("network.peer.join", "network.*")

    def test_glob_does_not_match_other_prefix(self):
        assert not _match_type("kernel.interrupt", "network.*")

    def test_glob_matches_bare_prefix(self):
        """'network.*' should also match bare 'network'."""
        assert _match_type("network", "network.*")


class TestStatsM2B:
    """M2-B fix: stats distinguishes ring_total from emitted_total."""

    def test_stats_keys_present(self):
        bus = MonitorBus(ring_size=10)
        s = bus.stats()
        for key in ("ring_total", "emitted_total", "total",
                    "ring_used", "ring_capacity", "by_type", "by_severity"):
            assert key in s, f"missing key: {key}"

    def test_ring_total_equals_by_type_sum(self):
        """Core M2-B fix: ring_total == sum(by_type.values()).

        Before the fix, total = _count (including evicted), but by_type only counted
        entries still in the ring — causing a mismatch.
        """
        bus = MonitorBus(ring_size=3)
        for _ in range(5):
            bus.emit(_ev(type_="kernel.test"))
        s = bus.stats()
        assert s["ring_total"] == 3
        assert s["emitted_total"] == 5
        assert sum(s["by_type"].values()) == s["ring_total"]
        # back-compat alias
        assert s["total"] == s["ring_total"]

    def test_empty_stats(self):
        bus = MonitorBus(ring_size=5)
        s = bus.stats()
        assert s["ring_total"] == 0
        assert s["emitted_total"] == 0
        assert s["by_type"] == {}


class TestPersistence:
    """JSONL append-only persistence + rehydrate on startup."""

    def test_rehydrate_loads_events_from_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "bus.jsonl")
            # First instance: emit + persist
            bus1 = MonitorBus(ring_size=10, persist_path=log)
            bus1.emit(_ev(type_="kernel.test", message="hello"))
            bus1.emit(_ev(type_="network.peer.join", message="world"))
            assert os.path.exists(log)

            # Second instance: should rehydrate from JSONL
            bus2 = MonitorBus(ring_size=10, persist_path=log)
            assert len(bus2._ring) == 2
            assert bus2._count == 2
            types = {ev.type for ev in bus2._ring}
            assert types == {"kernel.test", "network.peer.join"}

    def test_rehydrate_skips_corrupt_lines(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "bus.jsonl")
            with open(log, "w", encoding="utf-8") as f:
                f.write('{"type":"kernel.test","source":"t","severity":"info"}\n')
                f.write("THIS IS NOT JSON\n")
                f.write('{"type":"network.peer.join","source":"t","severity":"info"}\n')
            bus = MonitorBus(ring_size=10, persist_path=log)
            assert len(bus._ring) == 2  # corrupt line skipped

    def test_rehydrate_no_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "nonexistent.jsonl")
            bus = MonitorBus(ring_size=10, persist_path=log)
            assert len(bus._ring) == 0
