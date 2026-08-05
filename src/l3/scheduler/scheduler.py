"""Scheduler — CentralScheduler matrix (L3Router + RequestPool + TimeScheduler + Rate + Scope).

L3 Router:    intent → best Agent (territory + reputation + load)
RequestPool:  tool call → execute (reputation × 0.4 + priority × 0.35 + wait × 0.25)
TimeScheduler: process → CPU time-slice (quantum, preempt)
RateScheduler: tool → per-ring rate limit (60/20/5 per min)
ScopeScheduler: task → step budget + scout quota
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from l1.kernel.params.system import SCHEDULER_TASK_RETENTION

from .scheduler_rate import get_rate_scheduler
from .scheduler_router import L3Router, RequestPool
from .scheduler_scope import get_scope_scheduler
from .scheduler_time import TimeScheduler
from .scheduler_types import Task, TaskPriority

logger = logging.getLogger(__name__)


class CentralScheduler:
    """Unified CentralScheduler — 5-dimension scheduling matrix.

    Matrix dimensions:
      route  → L3Router: territory + reputation + load
      pool   → RequestPool: priority + wait time scoring
      time   → TimeScheduler: cpu quantum allocation
      rate   → RateScheduler: per-ring tool rate limiting
      scope  → ScopeScheduler: step budget + scout quota
    """

    def __init__(self):
        self.router = L3Router()
        self.pool = RequestPool()
        self.time_scheduler = TimeScheduler()
        self.rate = get_rate_scheduler()
        self.scope = get_scope_scheduler()
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._next_id = 0
        self._acb = None

    def _get_acb(self):
        if self._acb is None:
            from .acb import get_service as ga
            self._acb = ga()
        return self._acb

    # ── Scheduler matrix: evaluate all dimensions ──

    def evaluate_all(self, agent_id: str, tool_ring: str = "") -> dict:
        """Evaluate all scheduling dimensions for an agent/tool."""
        decisions = {}
        decisions["route"] = {"status": "pass"}
        if tool_ring:
            decisions["rate"] = self.rate.check(agent_id, tool_ring)
        decisions["scope"] = self.scope.check_scout_quota(agent_id)
        return decisions

    def submit(self, domain: str, command: str, args: dict | None = None,
               intent_tags: list[str] | None = None,
               preferred_agent: str | None = None,
               priority: int = TaskPriority.NORMAL.value) -> dict:
        """Route + enqueue through all matrix dimensions."""
        route = self.router.route(domain, intent_tags, preferred_agent)
        if not route.get("success", True) and "error" in route:
            return route
        agent_id = route["agent_id"]

        acb = self._get_acb()
        acb.create(agent_id)
        acb.set_slot(agent_id, "priority", priority)
        acb.set_slot(agent_id, "current_card", command)

        self.time_scheduler.register(agent_id, priority)
        tid = f"task-{self._next_id}"
        self._next_id += 1

        task = Task(id=tid, agent_id=agent_id, command=command,
                    args=args or {}, priority=priority)
        with self._lock:
            self._tasks[tid] = task
            self._prune_tasks_locked()

        pool_result = self.pool.enqueue(task)
        if not pool_result.get("success"):
            return pool_result

        self.router.update_load(agent_id, 0.1)
        acb.set_slot(agent_id, "task_state", "QUEUED")
        return {"success": True, "task_id": tid, "agent_id": agent_id,
                "score": round(self.pool._score(task), 3)}

    def execute(self, task_id: str, executor: Callable) -> dict:
        """Execute with time-slice monitoring + ACB state sync."""
        with self._lock:
            task = self._tasks.get(task_id)
        if not task:
            return {"success": False, "error": "task not found"}
        task.started_at = time.time()
        agent_id = task.agent_id
        acb = self._get_acb()
        acb.set_slot(agent_id, "task_state", "EXECUTING")
        self.time_scheduler.reset(agent_id)
        elapsed = 0.0
        try:
            task.result = executor(task.command, task.args)
            elapsed = time.time() - task.started_at
            tick_result = self.time_scheduler.tick(agent_id, elapsed)
            task.completed_at = time.time()
            if tick_result.get("status") in ("preempt", "timeout"):
                logger.warning("task %s: agent %s used %.1fs — %s",
                               task_id, agent_id, elapsed, tick_result["status"])
        except Exception as e:
            task.error = str(e)
            task.result = None
            task.completed_at = time.time()
            elapsed = task.completed_at - task.started_at
        status = "DONE" if not task.error else "ERROR"
        acb.set_slot(agent_id, "task_state", status)
        acb.set_slot(agent_id, "token_consumed", int(elapsed * 100))
        self.router.update_load(agent_id, -0.1)
        self.time_scheduler.reset(agent_id)
        with self._lock:
            self._prune_tasks_locked()
        return {"success": not task.error, "task_id": task_id,
                "result": task.result, "error": task.error, "elapsed": round(elapsed, 3)}

    def _prune_tasks_locked(self) -> None:
        """Drop oldest completed tasks beyond the retention cap (bounded memory).

        Called with ``self._lock`` held.  Only terminal tasks (``completed_at``
        set) are evicted, so queued-but-unexecuted tasks stay resolvable by
        execute()/status().
        """
        overflow = sum(1 for t in self._tasks.values() if t.completed_at) - SCHEDULER_TASK_RETENTION
        if overflow <= 0:
            return
        evicted = 0
        for tid in list(self._tasks):
            if evicted >= overflow:
                break
            if self._tasks[tid].completed_at:
                self._tasks.pop(tid, None)
                evicted += 1

    def poll(self) -> Task | None:
        return self.pool.dequeue()

    def schedule(self, agent_ids: list[str]) -> str | None:
        return self.time_scheduler.schedule(agent_ids)

    def status(self, task_id: str) -> dict:
        with self._lock:
            t = self._tasks.get(task_id)
        if not t:
            return {"success": False, "error": "task not found"}
        return {
            "success": True, "id": t.id, "agent_id": t.agent_id, "command": t.command,
            "priority": t.priority, "submitted_at": t.submitted_at, "started_at": t.started_at,
            "completed_at": t.completed_at, "error": t.error,
            "state": "running" if t.started_at and not t.completed_at
                     else "done" if t.completed_at else "queued",
        }

    def stats(self) -> dict:
        return {
            "agents": self.router.agents(),
            "pool": self.pool.stats(),
            "rate": self.rate.stats(),
            "scope": self.scope.stats(),
            "time": self.time_scheduler.stats() if hasattr(self.time_scheduler, 'stats') else {},
        }


# Legacy Scheduler alias for backward compat
Scheduler = CentralScheduler


_scheduler: CentralScheduler | None = None


def get_scheduler() -> CentralScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = CentralScheduler()
    return _scheduler


def reset_scheduler() -> None:
    global _scheduler
    _scheduler = None
