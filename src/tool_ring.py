"""Tool call ring buffer — records and queries tool execution history per ring."""
import time as _time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from l1.kernel.params.gatechain import GateStatus
from l1.kernel.params.kernel import PraxisRing, RequestPoolConfig


@dataclass
class ToolCallRecord:
    """ToolCallRecord — tool call record record (tool_name, agent_id, success, gate_result, fingerprint)."""
    tool_name: str
    agent_id: str
    success: bool
    gate_result: str = GateStatus.PASS
    fingerprint: str = ""
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class ToolRequest:
    """Tool request in the Ring 2.5 request pool."""
    tool_name: str
    agent_id: str
    priority: int = 3           # 1-5, from intent card
    agent_reputation: float = 0.9
    tool_danger: int = 0
    enqueued_at: float = field(default_factory=_time.time)


class ToolRing:
    """Ring 1 private tool ring — per-agent instance."""

    def __init__(self, capacity: int = PraxisRing.TOOL_RING_CAPACITY):
        self.capacity = capacity
        self._records: deque[ToolCallRecord] = deque(maxlen=capacity)

    def record(self, entry: ToolCallRecord):
        """Append a tool call record to the ring."""
        self._records.append(entry)

    def recent(self, n: int = 10) -> list[ToolCallRecord]:
        """Return the n most recent tool call records."""
        return list(self._records)[-n:]

    def count(self) -> int:
        """Return the number of recorded tool calls."""
        return len(self._records)

    def gate_stats(self) -> dict:
        """Tally gate results (pass/warn/block/report) across recorded calls."""
        total = len(self._records)
        if total == 0:
            return {GateStatus.PASS: 0, GateStatus.WARN: 0, GateStatus.BLOCK: 0, GateStatus.REPORT: 0}
        stats = {GateStatus.PASS: 0, GateStatus.WARN: 0, GateStatus.BLOCK: 0, GateStatus.REPORT: 0}
        for r in self._records:
            stats[r.gate_result] = stats.get(r.gate_result, 0) + 1
        return stats


class RequestPool:
    """Ring 2.5 request pool — reputation-weighted scheduling.

    Not FIFO, but three-factor weighted:
      - Reputation weight (40%): Agent reputation × tool danger level match
      - Priority (35%): Intent card priority 1-5
      - Wait time (25%): FIFO fairness compensation, linear growth, cap 5 min
    """

    def __init__(self, capacity: int = RequestPoolConfig.CAPACITY):
        self.capacity = capacity
        self._requests: list[ToolRequest] = []

    def enqueue(self, request: ToolRequest) -> bool:
        """Enqueue. If pool is full and EVICT_ON_FULL, evict lowest score."""
        if len(self._requests) >= self.capacity:
            if not RequestPoolConfig.EVICT_ON_FULL:
                return False
            self._evict_lowest()
        self._requests.append(request)
        return True

    def dequeue(self) -> ToolRequest | None:
        """Dequeue: return the highest-scored request."""
        if not self._requests:
            return None
        scored = [(self._score(r), i, r) for i, r in enumerate(self._requests)]
        scored.sort(key=lambda x: x[0], reverse=True)
        _, idx, best = scored[0]
        del self._requests[idx]
        return best

    def peek(self) -> list[ToolRequest]:
        """List all queued requests (sorted by score descending)."""
        scored = [(self._score(r), r) for r in self._requests]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored]

    def pending_for(self, agent_id: str) -> list[ToolRequest]:
        """Pending requests for a specific agent."""
        return [r for r in self._requests if r.agent_id == agent_id]

    def remove_for(self, agent_id: str) -> int:
        """Remove all requests for an agent (e.g., on crash)."""
        before = len(self._requests)
        self._requests = [r for r in self._requests if r.agent_id != agent_id]
        return before - len(self._requests)

    def _score(self, r: ToolRequest) -> float:
        """Three-factor weighted scoring."""
        w_r = RequestPoolConfig.WEIGHT_REPUTATION
        w_p = RequestPoolConfig.WEIGHT_PRIORITY
        w_w = RequestPoolConfig.WEIGHT_WAIT

        reputation_score = r.agent_reputation * (1.0 - r.tool_danger / 10.0)
        priority_score = r.priority / 5.0
        wait_seconds = _time.time() - r.enqueued_at
        wait_score = min(wait_seconds / RequestPoolConfig.MAX_WAIT_S, 1.0)

        return w_r * reputation_score + w_p * priority_score + w_w * wait_score

    def _evict_lowest(self) -> None:
        """Evict the lowest-scored request."""
        if not self._requests:
            return
        scored = [(self._score(r), i) for i, r in enumerate(self._requests)]
        scored.sort(key=lambda x: x[0])
        _, idx = scored[0]
        del self._requests[idx]

    def __len__(self) -> int:
        return len(self._requests)


# ═══════════════════════════════════════════════════════════════════════════
# Global singleton
# ═══════════════════════════════════════════════════════════════════════════

_shared_ring = ToolRing()
_shared_pool = RequestPool()


def get_shared_ring() -> ToolRing:
    """Global shared Ring 1 (backward compat). Phase 19 changed to per-agent."""
    return _shared_ring


def get_request_pool() -> RequestPool:
    """Global Ring 2.5 request pool singleton."""
    return _shared_pool
