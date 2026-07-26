"""CommMonitor — communication monitoring bus for inter-Cell/IPC/message traffic.

Aggregates message counts, latency samples, trace IDs, heartbeats, and health
probes across all communication channels.  Exposes stats via API.

Previously scattered across:
  - services/ipc.py:129-296   (_total_messages, _total_dropped)
  - services/cell.py:62-172   (_mailbox message counts)
  - kernel/event.py:74         (_history deque)
  - services/card_state.py:37  (trace_id)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ──
_COMM_HISTORY_MAX: int = 500
_TRACE_SAMPLE_RATE: float = 0.1  # 10% of messages get latency sampling


# ── Data types ──

@dataclass
class CommSample:
    """A single communication event sample."""
    channel: str          # "ipc", "cell_mailbox", "event_bus", "signal"
    msg_type: str = ""    # "send", "receive", "broadcast", "signal", "emit"
    direction: str = ""   # "in", "out", "internal"
    agent_id: str = ""
    target: str = ""
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""


@dataclass
class CommStats:
    """Aggregated communication statistics."""
    total_messages: int = 0
    total_dropped: int = 0
    total_broadcasts: int = 0
    total_signals: int = 1
    by_channel: dict[str, int] = field(default_factory=dict)
    by_agent: dict[str, int] = field(default_factory=dict)
    latency_samples: list[float] = field(default_factory=list)
    active_sessions: int = 0
    last_minute_rate: float = 0.0


# ── CommMonitor ──

class CommMonitor:
    """Centralized communication monitoring bus.

    Thread-safe.  Collects samples from IPC, Cell mailbox, EventBus, etc.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._history: list[CommSample] = []
        self._stats = CommStats()
        self._started_at = time.time()
        # Per-channel rolling windows for rate calculation
        self._timestamps: list[float] = []

    # ── Record API ──

    def record_message(self, channel: str, msg_type: str = "send",
                       direction: str = "out", agent_id: str = "",
                       target: str = "", latency_ms: float = 0.0) -> None:
        """Record a communication event (called by IPC/Cell/EventBus)."""
        sample = CommSample(
            channel=channel, msg_type=msg_type, direction=direction,
            agent_id=agent_id, target=target, latency_ms=latency_ms,
        )
        with self._lock:
            self._stats.total_messages += 1
            self._stats.by_channel[channel] = self._stats.by_channel.get(channel, 0) + 1
            if agent_id:
                self._stats.by_agent[agent_id] = self._stats.by_agent.get(agent_id, 0) + 1
            if msg_type == "broadcast":
                self._stats.total_broadcasts += 1
            self._timestamps.append(time.time())
            if latency_ms > 0:
                self._stats.latency_samples.append(latency_ms)
            self._history.append(sample)
            if len(self._history) > _COMM_HISTORY_MAX:
                self._history.pop(0)

    def record_dropped(self, channel: str = "ipc", count: int = 1) -> None:
        with self._lock:
            self._stats.total_dropped += count

    def record_signal(self) -> None:
        with self._lock:
            self._stats.total_signals += 1

    def set_active_sessions(self, n: int) -> None:
        with self._lock:
            self._stats.active_sessions = n

    # ── Query API ──

    def stats(self) -> dict:
        """Return aggregated communication statistics."""
        with self._lock:
            rate = 0.0
            now = time.time()
            cutoff = now - 60
            recent = [t for t in self._timestamps if t > cutoff]
            rate = len(recent)
            avg_latency = (
                sum(self._stats.latency_samples[-100:])
                / max(len(self._stats.latency_samples[-100:]), 1)
            )
            return {
                "total_messages": self._stats.total_messages,
                "total_dropped": self._stats.total_dropped,
                "total_broadcasts": self._stats.total_broadcasts,
                "total_signals": self._stats.total_signals,
                "by_channel": dict(self._stats.by_channel),
                "by_agent": dict(self._stats.by_agent),
                "active_sessions": self._stats.active_sessions,
                "msg_rate_per_min": round(rate, 1),
                "avg_latency_ms": round(avg_latency, 2),
                "history_count": len(self._history),
                "uptime": round(now - self._started_at),
                "memory_used": f"{sum(len(str(h)) for h in self._history)} bytes",
            }

    def recent(self, limit: int = 50) -> list[dict]:
        """Return recent communication samples."""
        with self._lock:
            return [
                {
                    "channel": s.channel, "type": s.msg_type,
                    "direction": s.direction, "agent": s.agent_id,
                    "target": s.target, "latency": s.latency_ms,
                    "ts": s.timestamp,
                }
                for s in self._history[-limit:]
            ]

    def health(self) -> dict:
        """Return communication health status."""
        with self._lock:
            now = time.time()
            recent_msg = (
                sum(1 for t in self._timestamps if t > now - 60)
            )
            return {
                "status": "ok" if recent_msg > 0 or now - self._started_at < 120 else "idle",
                "msg_rate_per_min": recent_msg,
                "dropped_rate": round(
                    self._stats.total_dropped / max(self._stats.total_messages, 1) * 100, 2
                ),
                "active_sessions": self._stats.active_sessions,
            }


# ── Singleton ──

_monitor: CommMonitor | None = None


def get_monitor() -> CommMonitor:
    global _monitor
    if _monitor is None:
        _monitor = CommMonitor()
    return _monitor


def reset_monitor() -> None:
    global _monitor
    _monitor = None
