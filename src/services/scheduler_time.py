"""TimeScheduler — time-slice scheduler for fair CPU allocation.

Extracted from scheduler.py for modularity.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from kernel.params import DEFAULT_QUANTUM, MAX_PREEMPT
from .scheduler_types import TimeSlice

logger = logging.getLogger(__name__)


class TimeScheduler:
    """Time-slice scheduler — priority + wait-time based fair scheduling.

    Flow:
      tick(agent_id, elapsed) → report used time
        → over quantum → preempted=True → force swap-out
        → under quantum → continue
      schedule(agents) → pick next Agent by (priority + wait_time) weighted round-robin
      preempt(agent_id) → force swap-out
    """

    def __init__(self):
        self._slices: dict[str, TimeSlice] = {}
        self._lock = threading.Lock()
        self._total_ticks = 0
        self._preemptions = 0

    def register(self, agent_id: str, priority: int = 5, quantum: float = DEFAULT_QUANTUM) -> None:
        with self._lock:
            self._slices[agent_id] = TimeSlice(
                agent_id=agent_id, quantum=quantum, priority=priority,
            )

    def tick(self, agent_id: str, elapsed: float) -> dict:
        with self._lock:
            self._total_ticks += 1
            ts = self._slices.get(agent_id)
            if not ts:
                return {"success": False, "error": f"agent {agent_id} not registered"}
            ts.used += elapsed
            ts.deadline = time.time() + max(0, ts.quantum - ts.used)
            if ts.used >= MAX_PREEMPT:
                ts.preempted = True
                self._preemptions += 1
                return {"status": "timeout", "agent_id": agent_id,
                        "used": round(ts.used, 1), "quantum": ts.quantum,
                        "action": "force_preempt"}
            if ts.used >= ts.quantum:
                ts.preempted = True
                self._preemptions += 1
                return {"status": "preempt", "agent_id": agent_id,
                        "used": round(ts.used, 1), "quantum": ts.quantum,
                        "action": "yield_or_preempt"}
            return {"status": "ok", "agent_id": agent_id,
                    "used": round(ts.used, 1), "remaining": round(ts.quantum - ts.used, 1)}

    def schedule(self, available: list[str]) -> str | None:
        with self._lock:
            candidates = []
            now = time.time()
            for aid in available:
                ts = self._slices.get(aid)
                if not ts:
                    continue
                if ts.preempted:
                    if now - ts.deadline < 5.0:
                        continue
                    ts.preempted = False
                    ts.used = 0.0
                    ts.quantum = max(DEFAULT_QUANTUM * 0.5, ts.quantum * 0.8)
                prio_score = (10 - ts.priority) * 2.0
                wait_score = min((now - ts.wait_since) / 60.0, 1.0) * 3.0
                candidates.append((prio_score + wait_score, aid))
            if not candidates:
                return None
            candidates.sort(reverse=True)
            chosen = candidates[0][1]
            ts = self._slices[chosen]
            ts.used = 0.0
            ts.started_at = now
            ts.wait_since = now
            return chosen

    def reset(self, agent_id: str) -> None:
        with self._lock:
            ts = self._slices.get(agent_id)
            if ts:
                ts.used = 0.0
                ts.preempted = False
                ts.quantum = DEFAULT_QUANTUM
                ts.wait_since = time.time()

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_ticks": self._total_ticks,
                "preemptions": self._preemptions,
                "agents": {aid: {"used": round(ts.used, 1),
                                  "quantum": ts.quantum,
                                  "preempted": ts.preempted,
                                  "priority": ts.priority}
                           for aid, ts in self._slices.items()},
            }


_time_scheduler: TimeScheduler | None = None


def get_time_scheduler() -> TimeScheduler:
    global _time_scheduler
    if _time_scheduler is None:
        _time_scheduler = TimeScheduler()
    return _time_scheduler


def reset_time_scheduler() -> None:
    global _time_scheduler
    _time_scheduler = None
