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
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_RING_SIZE = 2000
_DEFAULT_PERSIST_PATH = ""  # set at boot from kernel.params


@dataclass
class MonitorEvent:
    """Unified monitoring event — all subsystems use this model."""
    type: str                # "l1.kernel.interrupt" | "network.peer.join" | "service.cell.crash" | "task.card.complete"
    source: str              # "net" | "cell_monitor" | "ops_console" | "stagnation" | "card_registry"
    severity: str            # "info" | "warn" | "crit"
    agent_id: str = ""
    cell_id: str = ""
    card_id: str = ""
    message: str = ""
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": self.type, "source": self.source, "severity": self.severity,
            "agent_id": self.agent_id, "cell_id": self.cell_id, "card_id": self.card_id,
            "message": self.message, "data": self.data, "timestamp": self.timestamp,
        }


# ── SSE subscription (for real-time streaming) ──

_SseCallback = Any  # Callable[[MonitorEvent], None]


class MonitorBus:
    """Unified event bus — ring buffer + JSONL persistence + streaming + query."""

    def __init__(self, ring_size: int = _DEFAULT_RING_SIZE, persist_path: str = ""):
        self._ring: deque[MonitorEvent] = deque(maxlen=ring_size)
        self._lock = threading.RLock()
        self._sse_listeners: list[_SseCallback] = []
        self._count: int = 0
        self._persist_path = persist_path or _DEFAULT_PERSIST_PATH
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
                        ev = MonitorEvent(**{k: v for k, v in d.items() if k in (
                            "type", "source", "severity", "agent_id", "cell_id",
                            "card_id", "message", "data", "timestamp",
                        )})
                        self._ring.append(ev)
                        self._count += 1
                        loaded += 1
                    except Exception:
                        continue
            logger.info("monitor_bus: rehydrated %d events from %s", loaded, self._persist_path)
        except Exception as e:
            logger.warning("monitor_bus rehydrate failed: %s", e)

    def _append_persist(self, event: MonitorEvent) -> None:
        """Append one event to the JSONL file."""
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning("monitor_bus persist failed: %s", e)

    # ── Emit ──

    def emit(self, event: MonitorEvent) -> None:
        self._append_persist(event)
        with self._lock:
            self._ring.append(event)
            self._count += 1
        for cb in list(self._sse_listeners):
            try:
                cb(event)
            except Exception as e:
                logger.warning("monitor_bus SSE callback failed: %s", e)

    # ── Query ──

    def query(self, type_prefix: str = "", severity: str = "",
              agent_id: str = "", cell_id: str = "",
              source: str = "", since: float = 0.0,
              limit: int = 100) -> list[dict]:
        """Query events with filters. type_prefix supports glob: "kernel.*", "network.*"."""
        results = []
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

    def subscribe_sse(self, callback: _SseCallback) -> None:
        with self._lock:
            self._sse_listeners.append(callback)

    def unsubscribe_sse(self, callback: _SseCallback) -> None:
        with self._lock:
            try:
                self._sse_listeners.remove(callback)
            except ValueError:
                pass


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
    global _bus
    if _bus is None:
        try:
            from l1.kernel.params.system import PRAXIS_MONITOR_BUS_LOG
            persist = PRAXIS_MONITOR_BUS_LOG
        except Exception:
            persist = ""
        _bus = MonitorBus(persist_path=persist)
    return _bus


def reset_bus() -> None:
    global _bus
    _bus = None


# MONITOR_ROUTES moved to api_routes.py (central route table)
