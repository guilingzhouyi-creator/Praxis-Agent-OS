"""L3Router + RequestPool — intent routing and task queuing for Agent OS."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel.params.agent import REP_DEFAULT_REPUTATION

from .scheduler_types import AgentInfo, Task

logger = logging.getLogger(__name__)


class L3Router:
    """Route intents to the best Agent."""

    def __init__(self):
        self._agents: dict[str, AgentInfo] = {}
        self._lock = threading.Lock()

    def register(self, agent_id: str, territory: list[str],
                 reputation: float = REP_DEFAULT_REPUTATION, affinity: list[str] | None = None) -> None:
        """Register an agent with territory, reputation, and affinity tags."""
        with self._lock:
            self._agents[agent_id] = AgentInfo(
                id=agent_id, territory=territory, reputation=reputation,
                affinity_tags=affinity or [],
            )

    def route(self, domain: str, intent_tags: list[str] | None = None,
              preferred: str | None = None) -> dict:
        """Route a domain intent to the best agent."""
        with self._lock:
            agents = dict(self._agents)
        if preferred and preferred in agents:
            a = agents[preferred]
            return {"agent_id": preferred, "territory": a.territory,
                    "reputation": a.reputation, "score": 999, "reason": "preferred"}
        scored = []
        for aid, a in agents.items():
            score = 0.0
            if any(domain.startswith(t) for t in a.territory):
                score += 3.0
            score += a.reputation * 2.0
            score += (1.0 - a.load) * 1.0
            if intent_tags and any(t in a.affinity_tags for t in intent_tags):
                score += 1.5
            scored.append((score, aid))
        if not scored:
            return {"success": False, "error": "no agents available"}
        scored.sort(reverse=True)
        best = scored[0][1]
        a = agents[best]
        return {"agent_id": best, "territory": a.territory,
                "reputation": a.reputation, "score": scored[0][0], "reason": "best match"}

    def update_load(self, agent_id: str, delta: float = 0.1) -> None:
        """Adjust an agent's load by delta, clamped to [0, 1]."""
        with self._lock:
            a = self._agents.get(agent_id)
            if a:
                a.load = max(0, min(1, a.load + delta))
                a.last_seen = time.time()

    def agents(self) -> dict:
        """Return a snapshot of all registered agents."""
        with self._lock:
            return {aid: {"territory": a.territory, "reputation": a.reputation,
                          "load": a.load, "active_tasks": a.active_tasks}
                    for aid, a in self._agents.items()}


class RequestPool:
    """Tool request scheduling with priority scoring."""

    def __init__(self, capacity: int = 8):
        self.capacity = capacity
        self._queue: list[Task] = []
        self._lock = threading.Lock()

    def enqueue(self, task: Task) -> dict:
        """Enqueue a task, evicting the lowest-scored one when full."""
        with self._lock:
            if len(self._queue) >= self.capacity:
                scored = [(self._score(t), i, t) for i, t in enumerate(self._queue)]
                scored.sort()
                if scored[0][0] < self._score(task):
                    _, idx, _ = scored[0]
                    self._queue.pop(idx)
                    self._queue.append(task)
                    return {"success": True, "evicted": True}
                return {"success": False, "error": "pool full"}
            self._queue.append(task)
            return {"success": True}

    def dequeue(self) -> Task | None:
        """Dequeue the highest-scored task; returns None when empty."""
        with self._lock:
            if not self._queue:
                return None
            scored = [(self._score(t), i, t) for i, t in enumerate(self._queue)]
            scored.sort(reverse=True, key=lambda x: x[0])
            _, idx, best = scored[0]
            self._queue.pop(idx)
            return best

    def pending(self, agent_id: str | None = None) -> list[dict]:
        """List pending tasks, optionally filtered by agent."""
        with self._lock:
            items: list[dict[str, Any]] = [
                {"id": t.id, "command": t.command,
                 "priority": t.priority, "score": round(self._score(t), 3),
                 "wait": round(time.time() - t.submitted_at, 1)}
                for t in self._queue if not agent_id or t.agent_id == agent_id
            ]
            items.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
            return items

    def _score(self, task: Task) -> float:
        wait = min((time.time() - task.submitted_at) / 300.0, 1.0)
        prio_norm = (10 - task.priority) / 10.0
        return 0.4 + 0.35 * prio_norm + 0.25 * wait

    def stats(self) -> dict:
        """Return pool queue stats."""
        with self._lock:
            return {"queued": len(self._queue), "capacity": self.capacity}
