"""MonitorBus — unified monitoring event bus with ring buffer, JSONL persistence, streaming.

All monitoring subsystems emit typed MonitorEvent into this bus:
  kernel.*   — kernel health, interrupts, watchdog
  network.*  — peer discovery, mesh health
  service.*  — cell monitor, alerts, stagnation, approvals
  task.*     — card lifecycle, agent assignments

Persistence: each event is appended to a JSONL file for reboot survival.
The in-memory ring buffer is rehydrated from JSONL on startup.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.agent import MONITOR_RING_SIZE
from l1.kernel.params.system import MONITOR_BUS_MAX_QUEUED
from l3._daemon_pool import DaemonPool

logger = logging.getLogger(__name__)

_DEFAULT_RING_SIZE = MONITOR_RING_SIZE
_DEFAULT_PERSIST_PATH = ""  # set at boot from kernel.params


@dataclass
class MonitorEvent:
    """Unified monitoring event — all subsystems use this model."""

    type: str  # "l1.kernel.interrupt" | "network.peer.join" | "service.cell.crash" | "task.card.complete"
    source: str  # "net" | "cell_monitor" | "ops_console" | "stagnation" | "card_registry"
    severity: str  # "info" | "warn" | "crit"
    agent_id: str = ""
    cell_id: str = ""
    card_id: str = ""
    message: str = ""
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialize the event to a dict."""
        return {
            "type": self.type,
            "source": self.source,
            "severity": self.severity,
            "agent_id": self.agent_id,
            "cell_id": self.cell_id,
            "card_id": self.card_id,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp,
        }


# ── SSE subscription (for real-time streaming) ──

_SseCallback = Any  # Callable[[MonitorEvent], None]


class MonitorBus:
    """Unified event bus — ring buffer + JSONL persistence + streaming + query."""

    def __init__(self, ring_size: int = _DEFAULT_RING_SIZE, persist_path: str = ""):
        self._ring: deque[MonitorEvent] = deque(maxlen=ring_size)
        self._lock = threading.RLock()
        self._sse_listeners: list[_SseCallback] = []
        self._listeners: list[Callable[[MonitorEvent], None]] = []
        self._count: int = 0
        self._persist_path = persist_path or _DEFAULT_PERSIST_PATH
        self._executor = DaemonPool(max_workers=2, thread_name_prefix="mon")
        self._rehydrate()

    # ── Persistence ──

    def _rehydrate(self) -> None:
        """On startup, load recent events from JSONL into ring buffer."""
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            loaded = 0
            with open(self._persist_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        ev = MonitorEvent(
                            **{
                                k: v
                                for k, v in d.items()
                                if k
                                in (
                                    "type",
                                    "source",
                                    "severity",
                                    "agent_id",
                                    "cell_id",
                                    "card_id",
                                    "message",
                                    "data",
                                    "timestamp",
                                )
                            }
                        )
                        self._ring.append(ev)
                        self._count += 1
                        loaded += 1
                    except Exception:
                        continue
            logger.info("monitor_bus: rehydrated %d events from %s", loaded, self._persist_path)
        except Exception as e:
            logger.warning("monitor_bus rehydrate failed: %s", e)

    _file_lock = threading.Lock()
    """Lock serialising JSONL appends from background thread pool workers."""

    def _append_persist(self, event: MonitorEvent) -> None:
        """Append one event to the JSONL file (thread-safe)."""
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with self._file_lock:
                with open(self._persist_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning("monitor_bus persist failed: %s", e)

    # ── Emit ──

    def emit(self, event: MonitorEvent) -> None:
        """Emit a monitor event. Ring buffer append is synchronous (O(1));
        JSONL persist and SSE callbacks run in a background thread pool
        so that slow I/O cannot block the emitter.
        """
        self._bounded_submit(self._append_persist, event)
        with self._lock:
            self._ring.append(event)
            self._count += 1
            callbacks = list(self._sse_listeners) + list(self._listeners)
        for cb in callbacks:
            self._bounded_submit(self._safe_sse, cb, event)
        # L5: mirror event counts into StatsCenter so the observability stream
        # participates in statistical aggregation (was isolated from centers).
        try:
            from l3.services.stats_center import MetricPoint, get_center

            get_center().ingest(
                MetricPoint(
                    name=f"monitor.event.{event.type}",
                    value=1.0,
                    tags={"source": event.source, "severity": event.severity},
                    metric_type="counter",
                )
            )
        except Exception as e:
            logger.debug("monitor_bus: stats center ingest failed: %s", e)

    _MAX_QUEUED = MONITOR_BUS_MAX_QUEUED
    """Max pending tasks in the executor queue. Beyond this, new tasks are dropped
    to prevent unbounded memory growth under high event load."""

    def sync(self) -> None:
        """Wait for all pending background tasks (persist, SSE) to complete.
        Useful in tests where synchronous completion is required."""
        self._executor.shutdown(wait=True)
        self._executor = DaemonPool(max_workers=2, thread_name_prefix="mon")

    def _bounded_submit(self, fn: Callable, *args: Any) -> None:
        """Submit a task to the executor, dropping if the work queue is too deep."""
        if self._executor._work_queue.qsize() >= self._MAX_QUEUED:
            logger.warning("monitor_bus: executor queue full (%d), dropping task", self._MAX_QUEUED)
            return
        self._executor.submit(fn, *args)

    @staticmethod
    def _safe_sse(cb: Any, event: MonitorEvent) -> None:
        try:
            cb(event)
        except Exception as e:
            logger.warning("monitor_bus SSE callback failed: %s", e)

    # ── Query ──

    def query(
        self,
        type_prefix: str = "",
        severity: str = "",
        agent_id: str = "",
        cell_id: str = "",
        source: str = "",
        since: float = 0.0,
        limit: int = 100,
    ) -> list[dict]:
        """Query events with filters. type_prefix supports glob: "kernel.*", "network.*"."""
        results: list[dict] = []
        with self._lock:
            for ev in reversed(self._ring):
                if len(results) >= limit:
                    break
                if since and ev.timestamp < since:
                    continue
                if type_prefix and not _match_type(ev.type, type_prefix):
                    continue
                if severity and ev.severity != severity:
                    continue
                if agent_id and ev.agent_id != agent_id:
                    continue
                if cell_id and ev.cell_id != cell_id:
                    continue
                if source and ev.source != source:
                    continue
                results.append(ev.to_dict())
        return results

    def stats(self) -> dict:
        """Aggregate counts by type prefix and severity.

        ``ring_total``/``by_*`` reflect only events currently in the
        ring buffer (after eviction); ``emitted_total`` is the lifetime
        emit count (persisted across reboots via JSONL).
        """
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        with self._lock:
            for ev in self._ring:
                prefix = ev.type.split(".")[0] + ".*"
                by_type[prefix] = by_type.get(prefix, 0) + 1
                by_severity[ev.severity] = by_severity.get(ev.severity, 0) + 1
            ring_total = len(self._ring)
        return {
            "ring_total": ring_total,
            "emitted_total": self._count,
            # Back-compat alias for callers expecting ``total``.
            "total": ring_total,
            "ring_used": ring_total,
            "ring_capacity": self._ring.maxlen,
            "by_type": by_type,
            "by_severity": by_severity,
        }

    # ── SSE ──

    def subscribe(self, callback: Callable[[MonitorEvent], None]) -> None:
        """Register an internal (non-SSE) listener. G6: gives internal
        components a real subscription path instead of a one-way stream."""
        with self._lock:
            self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[MonitorEvent], None]) -> None:
        """Remove an internal listener. Returns None."""
        with self._lock:
            try:
                self._listeners.remove(callback)
            except ValueError:
                logger.debug("monitor_bus: listener not registered, nothing to remove")

    def subscribe_sse(self, callback: _SseCallback) -> None:
        """Register an SSE listener callback. Returns None."""
        with self._lock:
            self._sse_listeners.append(callback)

    def unsubscribe_sse(self, callback: _SseCallback) -> None:
        """Remove an SSE listener callback. Returns None."""
        with self._lock:
            try:
                self._sse_listeners.remove(callback)
            except ValueError:
                logger.debug("monitor_bus: sse listener not registered, nothing to remove")


# ── Helpers ──


def _match_type(event_type: str, pattern: str) -> bool:
    """Match "network.peer.join" against "network.*" or "network.peer.*"."""
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return event_type.startswith(prefix + ".") or event_type == prefix
    return event_type == pattern


# ── Singleton ──

_bus: MonitorBus | None = None


def get_bus() -> MonitorBus:
    """Get the MonitorBus singleton. Returns the shared bus."""
    global _bus
    if _bus is None:
        try:
            from l1.kernel.paths import get_paths as _gp

            persist = _gp().monitor_bus_log
        except Exception:
            persist = ""
        _bus = MonitorBus(persist_path=persist)
    return _bus


def reset_bus() -> None:
    """Reset the MonitorBus singleton. Returns None."""
    global _bus
    _bus = None


# MONITOR_ROUTES moved to api_routes.py (central route table)
