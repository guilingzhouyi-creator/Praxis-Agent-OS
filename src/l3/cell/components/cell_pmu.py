"""CellPmu — Performance Monitoring Unit for Cell.

Hardware-style performance counters for monitoring Cell behavior.
Each Cell gets its own PMU instance.  Counters are 64-bit monotonic
values that can be sampled, snapshotted, and streamed to MonitorBus.

Counter namespace (dot-delimited):
  cards.dispatched        cards.completed         cards.rolled_back
  cards.decomposed        cards.failed
  tools.executed.ring_1   tools.executed.ring_2_5 tools.executed.ring_3
  tools.rejected
  cache.hits              cache.misses            cache.injections
  cache.flushes           cache.promotions
  scouts.spawned          scouts.completed        scouts.timed_out
  scouts.cache_hits
  bus.messages_sent       bus.signals_emitted
  token.consumed          token.estimated
  agent.seconds_active    agent.boots             agent.crashes
  agent.recoveries
  watchdog.timeouts       watchdog.pets
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import (
    PMU_HISTORY_SIZE, PMU_SNAPSHOT_INTERVAL, PMU_COUNTER_GROUPS,
    PMU_QUERY_LIMIT, PMU_RATE_WINDOW, PMU_RATE_MIN_SECONDS,
)

logger = logging.getLogger(__name__)


@dataclass
class PmuSnapshot:
    """Point-in-time snapshot of all counter values."""
    timestamp: float = 0.0
    counters: dict[str, int] = field(default_factory=dict)
    cell_id: str = ""


class CellPmu:
    """Performance Monitoring Unit — named 64-bit counters with snapshot history.

    Thread-safe.  All public methods acquire a reentrant lock.
    """

    def __init__(
        self,
        cell_id: str,
        history_size: int = PMU_HISTORY_SIZE,
        snapshot_interval: float = PMU_SNAPSHOT_INTERVAL,
        enabled_groups: list[str] | None = None,
    ):
        self.cell_id = cell_id
        self._history_size = history_size
        self._snapshot_interval = snapshot_interval
        self._enabled_groups = set(enabled_groups or PMU_COUNTER_GROUPS)
        self._lock = threading.RLock()

        # Flat counter dict: "cards.dispatched" -> int
        self._counters: dict[str, int] = defaultdict(int)

        # Initialise all known counters to 0 so snapshot keys are stable
        for group in self._enabled_groups:
            for name in _COUNTER_NAMES_BY_GROUP.get(group, []):
                self._counters[f"{group}.{name}"] = 0

        # Time-series ring buffer of snapshots
        self._history: list[PmuSnapshot] = []

        # Last snapshot time for auto-snapshot
        self._last_snapshot: float = time.time()

    # ── Counter operations ────────────────────────────────────────

    def increment(self, name: str, delta: int = 1) -> None:
        """Increment a counter by delta (default 1).

        Name can be dot-delimited (e.g. "cards.dispatched") or
        group-prefixed ("cards.dispatched").  Unknown counters are
        silently ignored if the group is not enabled.
        """
        if not self._group_enabled(name):
            return
        with self._lock:
            self._counters[name] += delta

    def read(self, name: str) -> int:
        """Read the current value of a counter."""
        with self._lock:
            return self._counters.get(name, 0)

    def read_group(self, group: str) -> dict[str, int]:
        """Read all counters in a group (e.g. "cards")."""
        prefix = f"{group}."
        with self._lock:
            return {k: v for k, v in self._counters.items() if k.startswith(prefix)}

    # ── Snapshot ──────────────────────────────────────────────────

    def snapshot(self, force: bool = False) -> PmuSnapshot | None:
        """Take a point-in-time snapshot of all counters.

        If not forced, honours snapshot_interval to avoid flooding
        the history ring buffer.  On snapshot, pushes counters to
        the global StatsCenter for cross-Cell aggregation.
        """
        now = time.time()
        if not force and now - self._last_snapshot < self._snapshot_interval:
            return None
        self._last_snapshot = now
        with self._lock:
            snap = PmuSnapshot(
                timestamp=now,
                counters=dict(self._counters),
                cell_id=self.cell_id,
            )
            self._history.append(snap)
            if len(self._history) > self._history_size:
                self._history.pop(0)
            # Push to global StatsCenter
            try:
                from .services.stats_center import get_center
                get_center().ingest_pmu_snapshot(self.cell_id, snap.counters, now)
            except Exception:
                logger.debug("cell_pmu: stats center ingest failed")
            return snap

    def query_history(
        self,
        since: float = 0.0,
        limit: int = PMU_QUERY_LIMIT,
        name: str = "",
    ) -> list[PmuSnapshot]:
        """Query snapshot history with optional time/counter filter."""
        results: list[PmuSnapshot] = []
        for snap in reversed(self._history):
            if len(results) >= limit:
                break
            if since and snap.timestamp < since:
                continue
            if name and name not in snap.counters:
                continue
            results.append(snap)
        return results

    # ── Aggregation ───────────────────────────────────────────────

    def delta(self, name: str, seconds: float = PMU_RATE_WINDOW) -> int:
        """Compute the delta of a counter over the last N seconds."""
        since = time.time() - seconds
        oldest = None
        newest = None
        for snap in self._history:
            if snap.timestamp < since:
                oldest = snap
            else:
                newest = snap
        if oldest is None or newest is None:
            return 0
        return newest.counters.get(name, 0) - oldest.counters.get(name, 0)

    def rate(self, name: str, seconds: float = PMU_RATE_WINDOW) -> float:
        """Compute per-second rate of a counter over the last N seconds."""
        d = self.delta(name, seconds)
        return round(d / max(seconds, PMU_RATE_MIN_SECONDS), 2)

    # ── Reset ─────────────────────────────────────────────────────

    def reset(self, name: str = "") -> None:
        """Reset counters.  If name is empty, reset all."""
        with self._lock:
            if name:
                self._counters[name] = 0
            else:
                for k in self._counters:
                    self._counters[k] = 0
            self._history.clear()

    # ── Stats / report ────────────────────────────────────────────

    def stats(self) -> dict:
        """Return a dict of all counters with metadata."""
        now = time.time()
        with self._lock:
            return {
                "cell_id": self.cell_id,
                "counters": dict(self._counters),
                "history_entries": len(self._history),
                "history_capacity": self._history_size,
                "enabled_groups": sorted(self._enabled_groups),
                "uptime": round(now - self._last_snapshot, 1),
            }

    # ── Internal helpers ──────────────────────────────────────────

    def _group_enabled(self, name: str) -> bool:
        group = name.split(".")[0]
        return group in self._enabled_groups


# ── Counter name registry ──────────────────────────────────────

_COUNTER_NAMES_BY_GROUP: dict[str, list[str]] = {
    "cards": [
        "dispatched", "completed", "rolled_back", "decomposed", "failed",
    ],
    "tools": [
        "executed.ring_1", "executed.ring_2_5", "executed.ring_3", "rejected",
    ],
    "cache": [
        "hits", "misses", "injections", "flushes", "promotions",
    ],
    "scouts": [
        "spawned", "completed", "timed_out", "cache_hits",
    ],
    "bus": [
        "messages_sent", "signals_emitted",
    ],
    "token": [
        "consumed", "estimated",
    ],
    "memory": [
        "compacts", "compact.merges", "compact.saved_tokens",
        "stub_compacts", "stub_compact.saved_bytes",
        "context.warnings", "context.critical",
    ],
    "agent": [
        "seconds_active", "boots", "crashes", "recoveries",
    ],
    "watchdog": [
        "timeouts", "pets",
    ],
    "icache": [
        "hits", "misses", "evictions",
    ],
    "tlb": [
        "hits", "misses", "flushes",
    ],
    "interrupt": [
        "triggered.nmi", "triggered.high", "triggered.normal", "triggered.low",
        "handled.nmi", "handled.high", "handled.normal", "handled.low",
    ],
}
