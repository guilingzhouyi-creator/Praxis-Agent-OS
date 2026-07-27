from __future__ import annotations
import logging
import re
import threading
import time
import uuid
from typing import Any

from .agent.subagent_spec import SubAgentSpec, BUILTIN_SUBAGENTS
from .agent.subagent_task import SubAgentTask

logger = logging.getLogger(__name__)


class SubAgentDispatcher:
    """SubAgent dispatcher — @mention parsing + task scheduling + lifecycle."""

    # @mention regex: "@agent-name rest of prompt"
    MENTION_RE = re.compile(r"@(\w[\w-]*)\s*(.*)", re.DOTALL)

    def __init__(self):
        self._specs: dict[str, SubAgentSpec] = dict(BUILTIN_SUBAGENTS)
        self._tasks: dict[str, SubAgentTask] = {}
        self._lock = threading.RLock()

    def parse_mentions(self, text: str) -> list[tuple[str, str, str]]:
        """Parse @mentions in text.

        Returns:
            [(mention_name, full_text_before_rest, remaining_text), ...]
        """
        results = []
        remaining = text.strip()
        while remaining:
            m = self.MENTION_RE.match(remaining)
            if m:
                name = m.group(1)
                rest = m.group(2).strip()
                if name in self._specs:
                    results.append((name, remaining[:m.start()], rest))
                    remaining = rest
                    continue
            break
        return results

    def dispatch(self, spec_name: str, prompt: str,
                 parent_agent_id: str = "",
                 context: dict | None = None,
                 cell=None) -> dict:
        """Dispatch a sub-agent task."""
        with self._lock:
            spec = self._specs.get(spec_name)
            if not spec:
                return {"success": False, "error": f"unknown subagent: {spec_name}"}

            task_id = f"sub-{uuid.uuid4().hex[:12]}"
            task = SubAgentTask(
                task_id=task_id,
                spec=spec,
                prompt=prompt,
                parent_agent_id=parent_agent_id,
                context=context,
                cell=cell,
            )
            self._tasks[task_id] = task

        return task.start()

    def dispatch_from_text(self, text: str, parent_agent_id: str = "",
                           cell=None) -> dict:
        """Auto-parse @mention from text and dispatch."""
        mentions = self.parse_mentions(text)
        if not mentions:
            return {"success": False, "error": "no @mention found"}

        results = []
        for name, before, rest in mentions:
            r = self.dispatch(name, rest, parent_agent_id, cell=cell)
            results.append(r)

        return {"success": True, "dispatched": len(results), "results": results}

    def get_task(self, task_id: str) -> SubAgentTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> dict:
        task = self.get_task(task_id)
        if not task:
            return {"success": False, "error": f"task not found: {task_id}"}
        return task.cancel()

    def list_tasks(self, status: str = "") -> list[dict]:
        with self._lock:
            tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return [t.get_result() for t in tasks]

    def register_spec(self, spec: SubAgentSpec) -> dict:
        with self._lock:
            self._specs[spec.name] = spec
        return {"success": True, "spec": spec.to_dict()}

    def list_specs(self) -> dict:
        with self._lock:
            return {
                "success": True,
                "count": len(self._specs),
                "specs": {n: s.to_dict() for n, s in self._specs.items()},
            }
