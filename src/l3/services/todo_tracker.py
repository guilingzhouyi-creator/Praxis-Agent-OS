"""TodoTracker — persistent task state machine for AgentLoop.

Agent-harness-style: pending -> in_progress -> verifying -> verified | escalated.
State is persisted to JSON for cross-session recovery.
Close gate refuses if any task remains unverified and unwaived.
"""

from __future__ import annotations

import json
import logging
import os

from l1.kernel.params.system import LOG_TRUNC_40
from l1.kernel.paths import get_paths as _gp

logger = logging.getLogger(__name__)


class TodoTracker:
    """Persistent state machine for multi-step task execution.

    Task states:
      pending     - not started
      in_progress - agent is working on it
      verifying   - execution done, verification checks running
      verified    - all checks passed with evidence
      escalated   - max attempts exhausted, needs human review
      waived      - human explicitly waived verification
    """

    TASK_STATUSES = frozenset(
        {
            "pending",
            "in_progress",
            "verifying",
            "verified",
            "escalated",
            "waived",
            "add",
            "completed",
        }
    )

    _STATUS_ALIASES = {"add": "pending", "completed": "verified"}

    def __init__(self, state_path: str = ""):
        self._state_path = (
            state_path or os.environ.get("PRAXIS_TODO_STATE") or os.path.join(_gp().data_dir, "todo_state.json")
        )
        self._items: list[dict] = []
        self._read_cfg()
        self._iteration: int = 0
        self._status: str = "open"
        self._restore()

    def _read_cfg(self) -> None:
        try:
            from l3.config.settings_center import get_center

            center = get_center()
            self._max_iterations = center.get_int("loop.max_iterations", 50)
            self._max_attempts = center.get_int("loop.max_attempts", 3)
            self._continuation_nudge = center.get("loop.continuation_nudge", True)
        except Exception:
            self._max_iterations = 50
            self._max_attempts = 3
            self._continuation_nudge = True

    def _persist(self) -> None:
        try:
            data = {
                "status": self._status,
                "iteration": self._iteration,
                "max_attempts": self._max_attempts,
                "max_iterations": self._max_iterations,
                "tasks": list(self._items),
            }
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._state_path)
        except Exception as e:
            logger.warning("todo persist: %s", e)

    def _restore(self) -> None:
        if not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            self._status = data.get("status", "open")
            self._iteration = data.get("iteration", 0)
            self._max_attempts = data.get("max_attempts", 3)
            self._max_iterations = data.get("max_iterations", 50)
            self._items = data.get("tasks", [])
        except Exception as e:
            logger.warning("todo restore: %s", e)

    def load(self, items: list[dict]) -> None:
        """Replace the task list with normalized copies of the given items."""
        self._items = [dict(item) for item in items]
        for t in self._items:
            t.setdefault("status", "pending")
            t.setdefault("attempts", 0)
            t.setdefault("evidence", [])
            t.setdefault("checks", [])
        self._persist()

    def update(self, content: str, status: str) -> str:
        """Transition a task's status; returns the new status or an error string."""
        if status not in self.TASK_STATUSES:
            return f"error: invalid status '{status}'"
        status = self._STATUS_ALIASES.get(status, status)
        task = self._find(content)
        if task is None:
            if status != "pending" and status != "add":
                return "error: new task must start as 'pending' or 'add'"
            self._items.append(
                {
                    "content": content,
                    "status": "pending" if status == "add" else status,
                    "attempts": 0,
                    "evidence": [],
                    "checks": [],
                }
            )
            self._persist()
            return "pending"
        old = task["status"]
        if old == "verified" and status == "verified":
            return "verified"
        if old == "verified":
            return f"error: task '{content[:LOG_TRUNC_40]}' is already verified"
        if old == "escalated" and status != "waived":
            return f"error: task '{content[:LOG_TRUNC_40]}' is escalated"
        if old == "waived" and status not in ("verified", "waived"):
            return f"error: task '{content[:LOG_TRUNC_40]}' is waived"
        if old == "in_progress" and status == "verifying":
            task["status"] = "verifying"
            self._persist()
            return "verifying"
        if old == "pending" and status == "in_progress":
            task["status"] = "in_progress"
            self._persist()
            return "in_progress"
        task["status"] = status
        self._persist()
        return status

    def record_attempt(self, content: str, phase: str, exit_code: int, evidence: str = "") -> dict:
        """Record an execute/verify attempt; returns the next action to take."""
        task = self._find(content)
        if task is None:
            return {"action": "error", "detail": f"unknown task: {content[:LOG_TRUNC_40]}"}
        if self._status == "closed":
            return {"action": "error", "detail": "loop is closed"}
        if task["status"] in ("verified", "escalated", "waived"):
            return {"action": "error", "detail": f"task is {task['status']}"}
        self._iteration += 1
        if self._iteration >= self._max_iterations:
            self._status = "closed"
            self._persist()
            return {"action": "escalate", "detail": "global iteration cap reached"}
        entry = {"phase": phase, "exit_code": exit_code, "evidence": evidence, "attempt": task["attempts"] + 1}
        task["evidence"].append(entry)
        ok = exit_code == 0
        if phase == "execute":
            if ok:
                task["status"] = "verifying"
                self._persist()
                return {"action": "verify", "task": content[:LOG_TRUNC_40], "detail": "run verification checks"}
            return self._fail_task(task)
        if phase == "verify":
            if task["status"] != "verifying":
                return {"action": "error", "detail": "task not in verify phase"}
            if ok:
                if not evidence:
                    return {"action": "error", "detail": "passing verify requires --evidence"}
                task["status"] = "verified"
                self._persist()
                return {"action": "done", "task": content[:LOG_TRUNC_40], "detail": "verified", "evidence": evidence}
            return self._fail_task(task)
        return {"action": "error", "detail": f"unknown phase: {phase}"}

    def _fail_task(self, task: dict) -> dict:
        task["attempts"] += 1
        if task["attempts"] >= self._max_attempts:
            task["status"] = "escalated"
            self._persist()
            return {
                "action": "escalate",
                "task": task["content"][:40],
                "detail": f"exhausted {self._max_attempts} attempts",
            }
        task["status"] = "pending"
        self._persist()
        return {
            "action": "retry",
            "task": task["content"][:40],
            "detail": f"attempt {task['attempts']}/{self._max_attempts} failed",
        }

    def waive(self, content: str, reason: str = "") -> dict:
        """Mark a task as waived with an optional reason."""
        task = self._find(content)
        if task is None:
            return {"action": "error", "detail": f"unknown task: {content[:LOG_TRUNC_40]}"}
        task["status"] = "waived"
        task["evidence"].append({"phase": "waive", "reason": reason})
        self._persist()
        return {"action": "waived", "task": content[:LOG_TRUNC_40], "detail": reason}

    def can_close(self) -> tuple[bool, list[str]]:
        """Return whether every task is verified/waived, plus blockers."""
        blocked = [t["content"][:60] for t in self._items if t["status"] not in ("verified", "waived")]
        return len(blocked) == 0, blocked

    def has_open_items(self) -> bool:
        """Return whether any task is still pending/in-progress/verifying/escalated."""
        return any(t["status"] in ("pending", "in_progress", "verifying", "escalated") for t in self._items)

    def reminder(self) -> str | None:
        """Build a progress reminder/next-action prompt, or None when idle."""
        if self._status == "closed" or not self._items:
            return None
        in_progress = [t for t in self._items if t["status"] == "in_progress"]
        verifying = [t for t in self._items if t["status"] == "verifying"]
        pending = [t for t in self._items if t["status"] == "pending"]
        escalated = [t for t in self._items if t["status"] == "escalated"]
        lines = []
        if escalated:
            lines.append(f">> ESCALATED: {escalated[0]['content'][:60]} - needs human review")
        if verifying:
            lines.append(f">> Verifying: {verifying[0]['content'][:60]} - run checks")
        if in_progress:
            lines.append(f">> You are currently ON task '{in_progress[0]['content'][:60]}'")
        elif pending:
            lines.append(">> NOTHING is in_progress but tasks remain.")
        if lines or self.has_open_items():
            lines.append("")
            lines.append("Task list:")
            for t in self._items:
                marks = {
                    "pending": "[ ]",
                    "in_progress": "[->]",
                    "verifying": "[?]",
                    "verified": "[V]",
                    "escalated": "[!]",
                    "waived": "[-]",
                }
                mark = marks.get(t["status"], "[?]")
                att = f" (x{t['attempts']})" if t.get("attempts") else ""
                lines.append(f"  {mark} {t['content'][:70]}{att}")
            lines.append("")
            lines.append("Commands:")
            lines.append("  todowrite content=<task> status=in_progress  - start a task")
            lines.append("  todowrite content=<task> status=verifying    - mark done for verification")
            lines.append("  todowrite content=<task> status=verified     - confirm verified")
            lines.append("  todowrite content=<task> status=waived       - skip verification")
            lines.append("Do NOT stop while ANY item is pending or in_progress.")
            return "\n".join(lines)
        return None

    def stats(self) -> dict:
        """Return loop status, iteration, and per-status task counts."""
        by_status: dict[str, int] = {}
        for t in self._items:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        return {
            "status": self._status,
            "iteration": self._iteration,
            "max_iterations": self._max_iterations,
            "total_tasks": len(self._items),
            "by_status": by_status,
        }

    def reset(self) -> None:
        """Clear all tasks/state and remove the persisted state file."""
        self._items.clear()
        self._iteration = 0
        self._status = "open"
        if os.path.exists(self._state_path):
            try:
                os.remove(self._state_path)
            except Exception:
                logger.debug("todo_tracker: state file cleanup failed")

    def _find(self, content: str) -> dict | None:
        for t in self._items:
            if t["content"] == content:
                return t
        return None
