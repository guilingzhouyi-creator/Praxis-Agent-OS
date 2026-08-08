"""SubAgentPool — async delegation pool for structured card execution.

Architecture:
  Unified pool shared across all Cell agents (cf ScoutPool).
  Dual-buffer design separating explore (read-only) and execute (read-write) tasks.
  Each buffer has its own ThreadPoolExecutor for independent parallelism control.

  Explore buffer:  read-only investigation, Ring 1 tools
  Execute buffer:  read-write multi-step execution, Ring 2/2.5

  Results are NOT collected here — SubAgentTask._deliver_result() sends
  the result directly to the parent Peer Agent's CellMessage mailbox
  (SUBAGENT_RESULT type, TTL-managed).  The pool only tracks task IDs
  for life-cycle and stats.

Flow:
  PeerAgent -> gate.classify_card(card) -> 'explore' | 'execute'
    -> pool.commission(card_type, spec, prompt)
    -> executor.submit(task.start)  (explore or execute executor)
    -> daemon thread runs AgentLoop
    -> _deliver_result() -> Cell.send_message() -> mailbox
    -> Peer.collect() retrieves from mailbox
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from l1.kernel.params.agent import SUBAGENT_SESSION_TTL
from l1.kernel.params.api import SUBAGENT_POOL_EXECUTE_WORKERS, SUBAGENT_POOL_EXPLORE_WORKERS, SUBAGENT_RUN_TIMEOUT
from l1.kernel.params.system import LOG_TRUNC_100, POLL_INTERVAL_DEFAULT

from .subagent_spec import BUILTIN_SUBAGENTS, SubAgentSpec, load_specs
from .subagent_task import SubAgentTask

logger = logging.getLogger(__name__)

_DEFAULT_EXPLORE_WORKERS = SUBAGENT_POOL_EXPLORE_WORKERS
_DEFAULT_EXECUTE_WORKERS = SUBAGENT_POOL_EXECUTE_WORKERS


class SubAgentPool:
    """Async delegation pool for structured SubAgent execution.

    Each Cell gets one pool instance.  Dual-buffer:
      - explore_buffer: read-only tasks (Ring 1)
      - execute_buffer: read-write tasks (Ring 2 / 2.5)
    """

    def __init__(self, cell_id: str, config: dict | None = None):
        self.cell_id = cell_id
        cfg = config or {}
        self._explore_executor = ThreadPoolExecutor(
            max_workers=cfg.get("explore_workers", _DEFAULT_EXPLORE_WORKERS),
            thread_name_prefix=f"sub-exp-{cell_id}",
        )
        self._execute_executor = ThreadPoolExecutor(
            max_workers=cfg.get("execute_workers", _DEFAULT_EXECUTE_WORKERS),
            thread_name_prefix=f"sub-exe-{cell_id}",
        )
        self._explore_workers = cfg.get("explore_workers", _DEFAULT_EXPLORE_WORKERS)
        self._execute_workers = cfg.get("execute_workers", _DEFAULT_EXECUTE_WORKERS)
        self._tasks: dict[str, SubAgentTask] = {}
        self._session_history: dict[str, SubAgentTask] = {}
        """Completed tasks retained for SUBAGENT_SESSION_TTL for context reuse."""
        self._lock = threading.RLock()
        self._total_commissioned = 0
        self._cleanup_started = False
        self._start_cleanup()

    def _executor_for(self, card_type: str) -> ThreadPoolExecutor:
        return self._explore_executor if card_type == "explore" else self._execute_executor

    def _start_cleanup(self) -> None:
        """Background thread to evict expired session history entries.  Idempotent."""
        if SUBAGENT_SESSION_TTL <= 0 or self._cleanup_started:
            return
        self._cleanup_started = True

        def _cleanup_loop():
            while True:
                time.sleep(SUBAGENT_SESSION_TTL * 0.5)
                now = time.time()
                with self._lock:
                    expired = [
                        sid
                        for sid, t in self._session_history.items()
                        if t.completed_at and now - t.completed_at > t.ttl
                    ]
                    for sid in expired:
                        self._session_history.pop(sid, None)

        t = threading.Thread(target=_cleanup_loop, daemon=True, name=f"sub-cleanup-{self.cell_id}")
        t.start()

    def commission(
        self,
        spec: SubAgentSpec,
        prompt: str,
        card_type: str = "explore",
        parent_agent_id: str = "",
        context: dict | None = None,
        cell=None,
        territory: list[str] | None = None,
        session_id: str = "",
    ) -> dict:
        """Dispatch to the appropriate executor buffer by card_type.

        If session_id is provided and a completed task with that ID exists
        in session_history, its context is merged into the new task.

        Args:
            territory: Peer Agent's territory to pass to the SubAgent for
                       GateChain G3 scoping.  If None, the SubAgent operates
                       without territory restrictions.
        """
        task_id = f"sub-{parent_agent_id}-{self._total_commissioned}"
        context = context or {}

        # Runtime safety check: reject if spec is not visible to caller
        if (
            cell
            and hasattr(cell, "permission")
            and cell.permission
            and not cell.permission.is_visible(spec.name, parent_agent_id)
        ):
            logger.warning("delegation denied: %s cannot see %s (state machine)", parent_agent_id, spec.name)
            return {"success": False, "error": f"'{spec.name}' is not available", "reason": "not_visible"}

        # Merge previous session context if session_id given
        if session_id:
            with self._lock:
                prev = self._session_history.get(session_id)
                if prev and prev.status in ("completed",):
                    prev_result = prev.get_result().get("result", {})
                    context.setdefault("prev_result", prev_result)
                    context.setdefault("prev_session_id", session_id)

        task = SubAgentTask(
            task_id=task_id,
            spec=spec,
            prompt=prompt,
            parent_agent_id=parent_agent_id,
            context=context,
            cell=cell,
            territory=territory,
            session_id=session_id,
        )
        with self._lock:
            self._tasks[task_id] = task
            self._total_commissioned += 1

        self._executor_for(card_type).submit(task.start)
        logger.debug(
            "subagent_pool: %s -> %s (buf=%s, total=%d)", parent_agent_id, task_id, card_type, self._total_commissioned
        )
        return {"success": True, "task_id": task_id, "buffer": card_type}

    def collect(self, task_id: str, timeout: float = SUBAGENT_RUN_TIMEOUT) -> dict:
        """Wait for and collect a task result, or time out."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = self._tasks.get(task_id)
            if task is None:
                return {"success": False, "error": f"task not found: {task_id}"}
            if task.status in ("completed", "failed", "cancelled"):
                r = task.get_result()
                self._tasks.pop(task_id, None)
                # Retain in session history for context reuse
                if task.ttl > 0 and task.status in ("completed",):
                    with self._lock:
                        self._session_history[task.session_id] = task
                return r
            time.sleep(POLL_INTERVAL_DEFAULT)
        return {
            "success": False,
            "task_id": task_id,
            "error": "timeout",
            "status": (t.status if (t := self._tasks.get(task_id)) else "unknown"),
        }

    def collect_all(self, task_ids: list[str], timeout: float = SUBAGENT_RUN_TIMEOUT) -> dict:
        """Collect results for many tasks, waiting until all finish or timeout."""
        deadline = time.time() + timeout
        results: list[dict] = []
        remaining = set(task_ids)
        while remaining and time.time() < deadline:
            done = set()
            for tid in list(remaining):
                task = self._tasks.get(tid)
                if task is None:
                    results.append({"task_id": tid, "error": "not found"})
                    done.add(tid)
                    continue
                if task.status in ("completed", "failed", "cancelled"):
                    results.append(task.get_result())
                    self._tasks.pop(tid, None)
                    done.add(tid)
            remaining -= done
            if remaining:
                time.sleep(POLL_INTERVAL_DEFAULT)
        for tid in remaining:
            results.append({"task_id": tid, "error": "timeout"})
        return {
            "success": True,
            "completed": sum(1 for r in results if r.get("status") == "completed"),
            "failed": sum(1 for r in results if r.get("status") == "failed"),
            "timed_out": len(remaining),
            "results": results,
        }

    def stats(self) -> dict:
        """Return pool commission and worker statistics."""
        with self._lock:
            return {
                "total_commissioned": self._total_commissioned,
                "tracked": len(self._tasks),
                "explore_workers": self._explore_workers,
                "execute_workers": self._execute_workers,
            }

    def shutdown(self, wait: bool = False) -> None:
        """Shut down both executor buffers. Idempotent."""
        self._explore_executor.shutdown(wait=wait)
        self._execute_executor.shutdown(wait=wait)

    # ── Spec visibility (queried by AgentLoop for tool discovery) ──

    def list_visible_specs(self, agent_id: str, agent_ring: int = 1, cell=None) -> list[dict]:
        """Return SubAgent specs visible to an agent (dict, not SubAgentSpec).

        Delegates to ``Cell.permission.list_visible_specs()`` for gate check,
        then enriches with description + allowed_tools from the spec registry.

        If no Cell permission system is wired, returns all built-in specs as
        visible (backward-compatible fallback).
        """
        all_specs = load_specs()
        if cell and hasattr(cell, "permission") and cell.permission:
            visible_names = cell.permission.list_visible_specs(agent_id, agent_ring)
            return [
                {
                    "name": n,
                    "description": all_specs[n].description[:LOG_TRUNC_100],
                    "read_only": all_specs[n].read_only,
                    "tools": all_specs[n].allowed_tools[:5],
                }
                for n in visible_names
                if n in all_specs
            ]
        # Fallback: all specs visible
        return [
            {
                "name": n,
                "description": s.description[:LOG_TRUNC_100],
                "read_only": s.read_only,
                "tools": s.allowed_tools[:5],
            }
            for n, s in all_specs.items()
        ]

    # ── @mention parsing (migrated from SubAgentDispatcher) ──

    MENTION_RE = re.compile(r"@(\w[\w-]*)\s*(.*)", re.DOTALL)

    def parse_mentions(
        self, text: str, cell=None, agent_id: str = "", agent_ring: int = 1
    ) -> list[tuple[str, str, str]]:
        """Parse @mentions in text, returning (spec_name, before, after).

        If *cell* is provided, only specs visible to the agent are returned
        (delegates to ``Cell.permission.list_visible_specs()``).
        """
        results = []
        remaining = text.strip()
        all_specs = load_specs()
        if cell and hasattr(cell, "permission") and cell.permission:
            visible = set(cell.permission.list_visible_specs(agent_id, agent_ring))
            specs = {n: s for n, s in all_specs.items() if n in visible}
        else:
            specs = all_specs
        while remaining:
            m = self.MENTION_RE.match(remaining)
            if m and m.group(1) in specs:
                results.append((m.group(1), remaining[: m.start()], m.group(2).strip()))
                remaining = m.group(2).strip()
                continue
            break
        return results

    def dispatch_from_text(
        self, text: str, parent_agent_id: str = "", cell=None, card_type: str = "explore", agent_ring: int = 1
    ) -> dict:
        """Parse @mention and dispatch to the pool.

        Uses BUILTIN_SUBAGENTS to resolve spec names.
        Filters by visibility when *cell* has a permission system.
        """
        mentions = self.parse_mentions(text, cell=cell, agent_id=parent_agent_id, agent_ring=agent_ring)
        if not mentions:
            return {"success": False, "error": "no @mention found"}
        spec_name, _before, prompt = mentions[0]
        spec = dict(BUILTIN_SUBAGENTS).get(spec_name)
        if not spec:
            return {"success": False, "error": f"unknown subagent: {spec_name}"}
        return self.commission(spec, prompt, card_type=card_type, parent_agent_id=parent_agent_id, cell=cell)
