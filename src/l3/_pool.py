"""Worker pool — generic concurrency layer.

Manages a pool of worker threads for task execution.
Supports priority queuing, timeout, callbacks, and graceful shutdown.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel.params.system import POLL_INTERVAL_DEFAULT
from l2.i18n import t as _t

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """TaskState — enum of task state variants."""

    PENDING = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()
    TIMEOUT = auto()


@dataclass
class WorkTask:
    """WorkTask — work task record (id, fn, args, kwargs, priority)."""

    id: str
    fn: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    priority: int = 5
    timeout: float = 0
    state: TaskState = TaskState.PENDING
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    callback: Callable | None = None


class WorkerPool:
    """Generic thread pool with priority queue.

    Usage:
        pool = WorkerPool(size=4)
        pool.submit("task-1", fn=my_func, args=(1,2), priority=1)
        pool.submit("task-2", fn=my_func, args=(3,4), priority=5)
        pool.wait_all()
    """

    def __init__(self, size: int = 4):
        self._size = size
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._tasks: dict[str, WorkTask] = {}
        self._lock = threading.Lock()
        self._workers: list[threading.Thread] = []
        self._running = True
        self._active_count = 0

        for i in range(size):
            t = threading.Thread(target=self._worker_loop, args=(i,), daemon=True)
            self._workers.append(t)
            t.start()

    def submit(
        self,
        task_id: str,
        fn: Callable,
        args: tuple = (),
        kwargs: dict | None = None,
        priority: int = 5,
        timeout: float = 0,
        callback: Callable | None = None,
    ) -> dict:
        """Submit a task to the pool and return an ack dict."""
        task = WorkTask(
            id=task_id,
            fn=fn,
            args=args,
            kwargs=kwargs or {},
            priority=priority,
            timeout=timeout,
            callback=callback,
        )
        with self._lock:
            self._tasks[task_id] = task
        # PriorityQueue: lower number = higher priority
        self._queue.put((priority, task.created_at, task))
        return {"success": True, "id": task_id}

    def get(self, task_id: str) -> dict:
        """Return task state/result for a task id."""
        with self._lock:
            task = self._tasks.get(task_id)
        if not task:
            return {"success": False, "error": _t("core.task_not_found")}
        return {
            "success": True,
            "id": task.id,
            "state": task.state.name,
            "result": task.result,
            "error": task.error,
            "elapsed": task.completed_at - task.started_at if task.completed_at else 0,
        }

    def list(self) -> dict:
        """List all tracked tasks with their states."""
        with self._lock:
            items = [{"id": t.id, "state": t.state.name} for t in self._tasks.values()]
        return {"success": True, "tasks": items, "count": len(items), "active": self._active_count}

    def cancel(self, task_id: str) -> dict:
        """Cancel a pending task; returns success or error dict."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.state == TaskState.PENDING:
                task.state = TaskState.FAILED
                return {"success": True}
        return {"success": False, "error": _t("core.task_not_found_or_running")}

    def wait_all(self, timeout: float = 30) -> None:
        """Block until all tasks finish or the timeout elapses."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                pending = sum(1 for t in self._tasks.values() if t.state in (TaskState.PENDING, TaskState.RUNNING))
                if pending == 0:
                    return
            time.sleep(POLL_INTERVAL_DEFAULT)

    def stats(self) -> dict:
        """Return pool statistics (size, active workers, task states)."""
        with self._lock:
            states: dict[str, int] = {}
            for t in self._tasks.values():
                states[t.state.name] = states.get(t.state.name, 0) + 1
        return {
            "pool_size": self._size,
            "active_workers": self._active_count,
            "tasks": states,
            "total": len(self._tasks),
        }

    def shutdown(self) -> dict:
        """Stop the worker pool; returns drain status dict."""
        self._running = False
        return {"success": True, "drained": self._queue.qsize()}

    def _worker_loop(self, idx: int) -> None:
        while self._running:
            try:
                _, _, task = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            task.state = TaskState.RUNNING
            task.started_at = time.time()
            self._active_count += 1

            try:
                if task.timeout > 0:
                    # Run with timeout via another thread
                    result_q: queue.Queue = queue.Queue()
                    t = threading.Thread(
                        target=lambda rq=result_q, tk=task: rq.put(tk.fn(*tk.args, **tk.kwargs)), daemon=True
                    )
                    t.start()
                    t.join(timeout=task.timeout)
                    if t.is_alive():
                        task.state = TaskState.TIMEOUT
                        task.error = "timeout"
                    else:
                        task.result = result_q.get_nowait()
                        task.state = TaskState.DONE
                else:
                    task.result = task.fn(*task.args, **task.kwargs)
                    task.state = TaskState.DONE
            except Exception as e:
                task.state = TaskState.FAILED
                task.error = str(e)
            finally:
                task.completed_at = time.time()
                self._active_count -= 1
                if task.callback:
                    try:
                        task.callback(task)
                    except Exception as e:
                        logger.warning("_pool: %s", e)


_pools: dict[str, WorkerPool] = {}
_pool_lock = threading.Lock()


def get_pool(name: str = "default", size: int = 4) -> WorkerPool:
    """Return the named shared pool, creating it on first use."""
    with _pool_lock:
        if name not in _pools:
            _pools[name] = WorkerPool(size)
        return _pools[name]


def shutdown_all() -> None:
    """Shut down every registered shared pool."""
    for pool in _pools.values():
        pool.shutdown()
