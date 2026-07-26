"""Todo table — structured task queue for Peer Agents, auto-persisted.

Each Todo item has priority, status, dependency chain, timing, and result.
Agents dequeue by priority (not FIFO). Supports blocking dependencies.

Persistence: JSON file at TODO_TABLE_PATH, auto-saved every 30s.

Usage:
  todo = TodoTable(agent_id="agent-b")
  todo.add("Modify database config", priority=3, depends_on=["todo-001"])
  todo.add("Add health check", priority=1)
  item = todo.next()  # pops highest-priority non-blocked item
  todo.complete(item.id, result={"ok": True})
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel.params.system import TODO_TABLE_PATH, TODO_TABLE_AUTO_SAVE
from l3._persistable import PersistableMixin

logger = logging.getLogger(__name__)


class TodoStatus(Enum):
    PENDING = auto()
    IN_PROGRESS = auto()
    DONE = auto()
    FAILED = auto()
    BLOCKED = auto()
    CANCELLED = auto()


@dataclass
class TodoItem:
    id: str = ""
    intent: str = ""
    domain: str = ""
    priority: int = 5          # 1=highest, 5=default, 10=lowest
    status: TodoStatus = TodoStatus.PENDING
    depends_on: list[str] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0


class TodoTable(PersistableMixin):
    """Priority-ordered task queue with dependency tracking, auto-persisted."""

    persistence_kind = "todo_table"

    def __init__(self, agent_id: str = "", persist_path: str = ""):
        self.agent_id = agent_id
        self._items: dict[str, TodoItem] = {}
        self._lock = threading.Lock()
        base = persist_path or TODO_TABLE_PATH
        path = base.replace(".json", f"_{agent_id}.json") if agent_id else base
        self._init_persistence(path, TODO_TABLE_AUTO_SAVE)
        self._restore()
        if TODO_TABLE_AUTO_SAVE > 0:
            self._start_auto_save()

    def _serialize(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "items": {tid: {
                "id": it.id, "intent": it.intent, "domain": it.domain,
                "priority": it.priority, "status": it.status.name,
                "depends_on": it.depends_on, "result": it.result,
                "error": it.error, "created_at": it.created_at,
                "started_at": it.started_at, "completed_at": it.completed_at,
            } for tid, it in self._items.items()},
        }

    def _deserialize(self, data: dict) -> bool:
        self._items.clear()
        for tid, d in data.get("items", {}).items():
            self._items[tid] = TodoItem(
                id=d.get("id", tid), intent=d.get("intent", ""),
                domain=d.get("domain", ""), priority=d.get("priority", 5),
                status=TodoStatus[d["status"]],
                depends_on=d.get("depends_on", []),
                result=d.get("result", {}), error=d.get("error", ""),
                created_at=d.get("created_at", 0.0),
                started_at=d.get("started_at", 0.0),
                completed_at=d.get("completed_at", 0.0),
            )
        return True

    def add(self, intent: str, domain: str = "", priority: int = 5,
            depends_on: list[str] | None = None, todo_id: str = "") -> str:
        tid = todo_id or f"{self.agent_id}-{uuid.uuid4().hex[:8]}"
        item = TodoItem(id=tid, intent=intent, domain=domain,
                        priority=priority,
                        depends_on=depends_on or [])
        # Check if dependencies exist — if not, mark as blocked
        with self._lock:
            for dep in item.depends_on:
                if dep not in self._items:
                    item.status = TodoStatus.BLOCKED
                    item.error = f"unknown dependency: {dep}"
                    break
            self._items[tid] = item
        return tid

    def next(self) -> TodoItem | None:
        """Pop the highest-priority non-blocked PENDING item. Returns None if empty."""
        with self._lock:
            candidates = [
                it for it in self._items.values()
                if it.status == TodoStatus.PENDING and not self._is_blocked(it)
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda x: (x.priority, x.created_at))
            best = candidates[0]
            best.status = TodoStatus.IN_PROGRESS
            best.started_at = time.time()
            return best

    def _is_blocked(self, item: TodoItem) -> bool:
        for dep_id in item.depends_on:
            dep = self._items.get(dep_id)
            if dep is None or dep.status not in (TodoStatus.DONE, TodoStatus.CANCELLED):
                return True
        return False

    def get(self, todo_id: str) -> TodoItem | None:
        with self._lock:
            return self._items.get(todo_id)

    def update(self, todo_id: str, status: TodoStatus | None = None,
               result: dict | None = None, error: str = "") -> bool:
        with self._lock:
            item = self._items.get(todo_id)
            if not item:
                return False
            if status is not None:
                item.status = status
            if result is not None:
                item.result = result
            if error:
                item.error = error
            if status in (TodoStatus.DONE, TodoStatus.FAILED, TodoStatus.CANCELLED):
                item.completed_at = time.time()
            # Unblock any items waiting on this one
            if status in (TodoStatus.DONE, TodoStatus.CANCELLED):
                for it in self._items.values():
                    if it.status == TodoStatus.BLOCKED and todo_id in it.depends_on:
                        it.status = TodoStatus.PENDING
                        it.error = ""
            return True

    def cancel(self, todo_id: str) -> bool:
        return self.update(todo_id, status=TodoStatus.CANCELLED)

    def list(self, status: TodoStatus | None = None, limit: int = 20) -> list[dict]:
        with self._lock:
            result = []
            for it in sorted(self._items.values(), key=lambda x: (x.priority, x.created_at)):
                if status and it.status != status:
                    continue
                elapsed = 0.0
                if it.completed_at:
                    elapsed = round(it.completed_at - it.started_at, 2) if it.started_at else 0.0
                elif it.started_at:
                    elapsed = round(time.time() - it.started_at, 1)
                result.append({
                    "id": it.id, "intent": it.intent[:50],
                    "domain": it.domain, "priority": it.priority,
                    "status": it.status.name,
                    "depends_on": it.depends_on,
                    "error": it.error[:40] if it.error else "",
                    "elapsed": elapsed,
                })
                if len(result) >= limit:
                    break
            return result

    def stats(self) -> dict:
        with self._lock:
            counts = {}
            for it in self._items.values():
                counts[it.status.name] = counts.get(it.status.name, 0) + 1
            return {"total": len(self._items), "by_status": counts}

    def clear_done(self) -> int:
        with self._lock:
            done = [tid for tid, it in self._items.items()
                    if it.status in (TodoStatus.DONE, TodoStatus.FAILED, TodoStatus.CANCELLED)]
            for tid in done:
                del self._items[tid]
            return len(done)
