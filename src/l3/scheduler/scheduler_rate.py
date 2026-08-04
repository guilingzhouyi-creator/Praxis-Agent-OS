"""RateScheduler — per-agent, per-ring tool rate limiting.
Extracted from tool_pipeline.py for schedulr matrix integration.

Ring 1:   60 calls/min  (fast, read-only)
Ring 2.5: 20 calls/min  (moderate)
Ring 3:    5 calls/min   (slow, destructive)
"""
from __future__ import annotations

import logging
import threading
import time as _time

from l1.kernel.discovery import get_config as _get_config
from l1.kernel.params.system import PMU_SNAPSHOT_INTERVAL
from l1.kernel.params.tool import (
    TOOL_RATE_RING_1 as _TR1,
)
from l1.kernel.params.tool import (
    TOOL_RATE_RING_2_5 as _TR25,
)
from l1.kernel.params.tool import (
    TOOL_RATE_RING_3 as _TR3,
)

logger = logging.getLogger(__name__)

from l1.kernel.params.kernel import (
    RING_1 as _R1,
)
from l1.kernel.params.kernel import (
    RING_2_5 as _R25,
)
from l1.kernel.params.kernel import (
    RING_3 as _R3,
)
from l1.kernel.params.kernel import (
    RING_NUM_MAP as _RNM,
)

_RING_ORDER = _RNM
_RING_RATE = {}  # resolved below


def _resolve_ring_rates() -> dict:
    """Resolve tool rates from config with params fallback."""
    cfg = _get_config("tool_rates") or {}
    return {
        _R1: cfg.get("ring_1", _TR1),
        _R25: cfg.get("ring_2_5", _TR25),
        _R3: cfg.get("ring_3", _TR3),
    }


_RING_RATE = _resolve_ring_rates()


def agent_can_access(agent_id: str, tool_ring: str) -> bool:
    """Check whether the agent may access the given tool/ring."""
    from l1.kernel.params.agent import AGENT_CLEARANCE
    level = AGENT_CLEARANCE.get(agent_id, 1)
    return level >= _RING_ORDER.get(tool_ring, 0)


class RateScheduler:
    """Per-agent, per-ring tool rate limiting (sliding window)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, list[float]] = {}

    def check(self, agent_id: str, tool_ring: str) -> dict:
        rate = _RING_RATE.get(tool_ring, _TR1)
        key = f"{agent_id}:{tool_ring}"
        now = _time.time()
        with self._lock:
            ts_list = self._counters.setdefault(key, [])
            cutoff = now - PMU_SNAPSHOT_INTERVAL
            ts_list[:] = [t for t in ts_list if t > cutoff]
            if len(ts_list) >= rate:
                reset_after = ts_list[0] + PMU_SNAPSHOT_INTERVAL - now if ts_list else 0
                return {"allowed": False, "remaining": 0, "reset_after": round(reset_after, 1)}
            ts_list.append(now)
            return {"allowed": True, "remaining": rate - len(ts_list), "ring": tool_ring}

    def stats(self) -> dict:
        with self._lock:
            return {"active_keys": len(self._counters)}


_rate_scheduler: RateScheduler | None = None


def get_rate_scheduler() -> RateScheduler:
    """Get the rate scheduler singleton."""
    global _rate_scheduler
    if _rate_scheduler is None:
        _rate_scheduler = RateScheduler()
    return _rate_scheduler


def reset_rate_scheduler() -> None:
    global _rate_scheduler
    _rate_scheduler = None
