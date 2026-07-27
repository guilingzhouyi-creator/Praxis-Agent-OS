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
from typing import Any

from .subagent_spec import SubAgentSpec, BUILTIN_SUBAGENTS
from .subagent_task import SubAgentTask

logger = logging.getLogger(__name__)

_DEFAULT_EXPLORE_WORKERS = 4
_DEFAULT_EXECUTE_WORKERS = 4


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
        self._tasks: dict[str, SubAgentTask] = {}
        self._lock = threading.RLock()
        self._total_commissioned = 0

    def _executor_for(self, card_type: str) -> ThreadPoolExecutor:
        return self._explore_executor if card_type == "explore" else self._execute_executor

    def commission(self, spec: SubAgentSpec, prompt: str,
                   card_type: str = "explore",
                   parent_agent_id: str = "",
                   context: dict | None = None,
                   cell=None) -> dict:
        """Dispatch to the appropriate executor buffer by card_type."""
        task_id = f"sub-{parent_agent_id}-{self._total_commissioned}"
        task = SubAgentTask(
            task_id=task_id, spec=spec, prompt=prompt,
            parent_agent_id=parent_agent_id, context=context, cell=cell,
        )
        with self._lock:
            self._tasks[task_id] = task
            self._total_commissioned += 1

        self._executor_for(card_type).submit(task.start)
        logger.debug("subagent_pool: %s -> %s (buf=%s, total=%d)",
                     parent_agent_id, task_id, card_type, self._total_commissioned)
        return {"success": True, "task_id": task_id, "buffer": card_type}

    def collect(self, task_id: str, timeout: float = 120.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = self._tasks.get(task_id)
            if task is None:
                return {"success": False, "error": f"task not found: {task_id}"}
            if task.status in ("completed", "failed", "cancelled"):
                r = task.get_result()
                self._tasks.pop(task_id, None)
                return r
            time.sleep(0.1)
        return {"success": False, "task_id": task_id, "error": "timeout",
                "status": self._tasks.get(task_id).status if task_id in self._tasks else "unknown"}

    def collect_all(self, task_ids: list[str],
                    timeout: float = 120.0) -> dict:
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
                time.sleep(0.1)
        for tid in remaining:
            results.append({"task_id": tid, "error": "timeout"})
        return {"success": True, "completed": sum(1 for r in results if r.get("status") == "completed"),
                "failed": sum(1 for r in results if r.get("status") == "failed"),
                "timed_out": len(remaining), "results": results}

    def stats(self) -> dict:
        with self._lock:
            return {"total_commissioned": self._total_commissioned,
                    "tracked": len(self._tasks),
                    "explore_workers": self._explore_executor._max_workers,
                    "execute_workers": self._execute_executor._max_workers}

    # ── @mention parsing (migrated from SubAgentDispatcher) ──

    MENTION_RE = re.compile(r"@(\w[\w-]*)\s*(.*)", re.DOTALL)

    def parse_mentions(self, text: str) -> list[tuple[str, str, str]]:
        """Parse @mentions in text, returning (spec_name, before, after)."""
        results = []
        remaining = text.strip()
        specs = dict(BUILTIN_SUBAGENTS)
        while remaining:
            m = self.MENTION_RE.match(remaining)
            if m and m.group(1) in specs:
                results.append((m.group(1), remaining[:m.start()], m.group(2).strip()))
                remaining = m.group(2).strip()
                continue
            break
        return results

    def dispatch_from_text(self, text: str, parent_agent_id: str = "",
                           cell=None, card_type: str = "explore") -> dict:
        """Parse @mention and dispatch to the pool.
        
        Uses BUILTIN_SUBAGENTS to resolve spec names.
        """
        mentions = self.parse_mentions(text)
        if not mentions:
            return {"success": False, "error": "no @mention found"}
        spec_name, _before, prompt = mentions[0]
        spec = dict(BUILTIN_SUBAGENTS).get(spec_name)
        if not spec:
            return {"success": False, "error": f"unknown subagent: {spec_name}"}
        return self.commission(spec, prompt, card_type=card_type,
                               parent_agent_id=parent_agent_id, cell=cell)
