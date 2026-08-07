"""StatsCenter — unified statistics center for cross-Cell metric aggregation.

Collects metric data from:
  - PMU (per-Cell performance counters, via snapshot())
  - CentralCollector (token usage per Cell/Agent)
  - CellMonitor (health events)
  - CommMonitor (communication stats)

Each data source emits MetricPoints.  StatsCenter:
  - Buckets by {name, tags} with configurable time windows
  - Supports cross-Cell aggregation (sum/avg/min/max/p95)
  - Exposes sliding-window queries (1m/5m/1h)
  - Provides SSE live stream for real-time dashboard
  - Does NOT replace MonitorBus (alert pipeline) or ErrorBus

MetricPoint protocol:
  {"name": "cards.dispatched", "value": 42,
   "tags": {"cell": "cell-1", "agent": "agent-a"},
   "timestamp": 1234567890.0, "metric_type": "counter"}
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from l1.kernel.params.system import (
    STATS_BUCKET_SIZE,
    STATS_DEFAULT_WINDOW,
    STATS_HISTORY_BUCKETS,
    STATS_SSE_BUFFER,
    STATS_TOP_LIMIT,
)

logger = logging.getLogger(__name__)

_SseCallback = Callable[[dict], None]


@dataclass
class MetricPoint:
    """MetricPoint — metric point record (name, value, tags, timestamp, metric_type)."""

    name: str = ""
    value: float = 0.0
    tags: dict = field(default_factory=dict)
    timestamp: float = 0.0
    metric_type: str = "counter"  # "counter" | "gauge" | "rate"


@dataclass
class MetricBucket:
    """Aggregated values for one metric+tags within a time window."""

    name: str = ""
    tags_key: str = ""  # canonical tags dict key
    sum: float = 0.0
    count: int = 0
    min_val: float = float("inf")
    max_val: float = float("-inf")
    last: float = 0.0
    window_start: float = 0.0

    def ingest(self, value: float) -> None:
        """Accumulate one value into the bucket aggregates."""
        self.sum += value
        self.count += 1
        self.min_val = min(self.min_val, value)
        self.max_val = max(self.max_val, value)
        self.last = value

    def avg(self) -> float:
        """Return the mean of the ingested values."""
        return self.sum / max(self.count, 1)

    def to_dict(self) -> dict:
        """Serialize the bucket aggregates to a dict."""
        return {
            "name": self.name,
            "tags_key": self.tags_key,
            "sum": round(self.sum, 2),
            "count": self.count,
            "avg": round(self.avg(), 2),
            "min": round(self.min_val, 2) if self.count > 0 else 0,
            "max": round(self.max_val, 2) if self.count > 0 else 0,
            "last": round(self.last, 2),
            "window_start": round(self.window_start, 2),
        }

    def reset(self) -> None:
        """Zero out all bucket aggregates."""
        self.sum = 0.0
        self.count = 0
        self.min_val = float("inf")
        self.max_val = float("-inf")
        self.last = 0.0


def _tags_key(tags: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(tags.items()))


class StatsCenter:
    """Unified statistics center — metric ingestion, bucketing, query, SSE."""

    def __init__(
        self,
        bucket_size: int = STATS_BUCKET_SIZE,
        history_buckets: int = STATS_HISTORY_BUCKETS,
        sse_buffer: int = STATS_SSE_BUFFER,
    ):
        self._bucket_size = bucket_size
        self._history_buckets = history_buckets
        self._sse_buffer = sse_buffer
        self._lock = threading.RLock()

        # buckets[metric_name][tags_key] = MetricBucket
        self._buckets: dict[str, dict[str, MetricBucket]] = defaultdict(dict)

        # time-series history: list of (window_start, metric_name, tags_key, MetricBucket)
        self._history: list[tuple[float, str, str, MetricBucket]] = []

        # SSE subscribers
        self._sse_listeners: list[_SseCallback] = []

        # Lifetime counts
        self._total_points: int = 0

    # ── Ingestion ────────────────────────────────────────────────

    def ingest(self, point: MetricPoint) -> None:
        """Ingest a single metric point."""
        if point.timestamp == 0:
            point.timestamp = time.time()
        window_start = self._window(point.timestamp)
        tk = _tags_key(point.tags)

        with self._lock:
            bucket = self._buckets[point.name].get(tk)
            if bucket is None or bucket.window_start != window_start:
                # Finalize old bucket to history
                if bucket is not None:
                    self._history.append((bucket.window_start, point.name, tk, bucket))
                    self._trim_history()
                bucket = MetricBucket(
                    name=point.name,
                    tags_key=tk,
                    window_start=window_start,
                )
                self._buckets[point.name][tk] = bucket

            bucket.ingest(point.value)
            self._total_points += 1

        # Notify SSE listeners
        event = self._point_to_event(point)
        for cb in list(self._sse_listeners):
            try:
                cb(event)
            except Exception as e:
                logger.warning("stats SSE callback: %s", e)

    def ingest_batch(self, points: list[MetricPoint]) -> None:
        """Ingest multiple metric points at once."""
        for p in points:
            self.ingest(p)

    def ingest_pmu_snapshot(self, cell_id: str, counters: dict[str, int], timestamp: float = 0) -> None:
        """Convert a PMU snapshot dict to MetricPoints and ingest."""
        ts = timestamp or time.time()
        for name, value in counters.items():
            self.ingest(
                MetricPoint(
                    name=name,
                    value=float(value),
                    tags={"cell": cell_id},
                    timestamp=ts,
                    metric_type="counter",
                )
            )

    # ── Query ────────────────────────────────────────────────────

    def query(
        self,
        metrics: list[str] | None = None,
        tags: dict | None = None,
        window: str = STATS_DEFAULT_WINDOW,
        agg: str = "sum",
    ) -> list[dict]:
        """Query aggregated metrics.

        Args:
          metrics: Metric name filter (e.g. ["cards.dispatched"]).
                   None = all metrics.
          tags: Tag filter (e.g. {"cell": "cell-1"}).
          window: Time window: "1m", "5m", "1h", "all".
          agg: Aggregation: "sum" | "avg" | "min" | "max" | "last" | "p95".

        Returns list of {name, tags_key, value, window_start, count}.
        """
        window_seconds = self._parse_window(window)
        cutoff = time.time() - window_seconds

        with self._lock:
            results = []
            seen_buckets: set[tuple[str, str]] = set()

            # Current buckets
            for mname, tag_buckets in self._buckets.items():
                if metrics and mname not in metrics:
                    continue
                for tk, bucket in tag_buckets.items():
                    if bucket.window_start < cutoff:
                        continue
                    if tags and not self._tags_match(tk, tags):
                        continue
                    results.append(self._agg_bucket(bucket, agg))
                    seen_buckets.add((mname, tk))

            # Historical buckets
            for ws, mname, tk, bucket in self._history:
                if (mname, tk) in seen_buckets:
                    continue
                if metrics and mname not in metrics:
                    continue
                if ws < cutoff:
                    continue
                if tags and not self._tags_match(tk, tags):
                    continue
                results.append(self._agg_bucket(bucket, agg))
                seen_buckets.add((mname, tk))

        return results

    def top(
        self, metric: str, order: str = "desc", limit: int = STATS_TOP_LIMIT, window: str = STATS_DEFAULT_WINDOW
    ) -> list[dict]:
        """Cross-Cell ranking for a single metric.

        Returns sorted list of {tags_key, value} aggregated per tags.
        """
        results = self.query(metrics=[metric], window=window, agg="sum")
        # Group by tags_key (already grouped by bucket)
        order_asc = order != "desc"
        results.sort(key=lambda r: r["value"], reverse=not order_asc)
        return results[:limit]

    # ── SSE ──────────────────────────────────────────────────────

    def subscribe_sse(self, callback: _SseCallback) -> Callable[[], None]:
        """Register an SSE callback. Returns an unsubscribe callable."""
        with self._lock:
            self._sse_listeners.append(callback)
        return lambda: self.unsubscribe_sse(callback)

    def unsubscribe_sse(self, callback: _SseCallback) -> None:
        """Remove an SSE callback from the listener set."""
        with self._lock:
            try:
                self._sse_listeners.remove(callback)
            except ValueError:
                logger.debug("stats_center: sse listener not registered, nothing to remove")

    # ── Stats ────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return center-wide counters: points, buckets, history, subscribers."""
        with self._lock:
            metric_count = len(self._buckets)
            bucket_count = sum(len(tb) for tb in self._buckets.values())
            return {
                "total_points": self._total_points,
                "active_metrics": metric_count,
                "active_buckets": bucket_count,
                "history_entries": len(self._history),
                "history_capacity": self._history_buckets,
                "bucket_size_s": self._bucket_size,
                "sse_subscribers": len(self._sse_listeners),
                "metrics": sorted(self._buckets.keys()),
            }

    # ── Internal ─────────────────────────────────────────────────

    def _window(self, ts: float) -> float:
        return (ts // self._bucket_size) * self._bucket_size

    def _trim_history(self) -> None:
        while len(self._history) > self._history_buckets:
            self._history.pop(0)

    def _parse_window(self, window: str) -> float:
        if window == "all":
            return float("inf")
        unit = window[-1]
        val = int(window[:-1]) if len(window) > 1 else 5
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return val * multipliers.get(unit, 60)

    def _tags_match(self, tags_key: str, filter_tags: dict) -> bool:
        for k, v in filter_tags.items():
            expected = f"{k}={v}"
            if expected not in tags_key:
                return False
        return True

    def _agg_bucket(self, bucket: MetricBucket, agg: str) -> dict:
        value_map = {
            "sum": bucket.sum,
            "avg": bucket.avg(),
            "min": bucket.min_val if bucket.count > 0 else 0,
            "max": bucket.max_val if bucket.count > 0 else 0,
            "last": bucket.last,
            "p95": bucket.last,  # simplified: single-bucket p95 = last
        }
        return {
            "name": bucket.name,
            "tags_key": bucket.tags_key,
            "value": round(value_map.get(agg, bucket.sum), 2),
            "count": bucket.count,
            "window_start": round(bucket.window_start, 2),
        }

    def _point_to_event(self, point: MetricPoint) -> dict:
        return {
            "type": "stats.metric",
            "name": point.name,
            "value": point.value,
            "tags": point.tags,
            "timestamp": point.timestamp,
            "metric_type": point.metric_type,
        }


# ── Singleton ────────────────────────────────────────────────

_center: StatsCenter | None = None
_center_lock = threading.Lock()


def get_center() -> StatsCenter:
    """Return the shared StatsCenter singleton, creating it on first use."""
    global _center
    if _center is None:
        with _center_lock:
            if _center is None:
                _center = StatsCenter()
    return _center


def reset_center() -> None:
    """Drop the StatsCenter singleton (for testing / hot-reload)."""
    global _center
    _center = None
