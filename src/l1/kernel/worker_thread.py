"""WorkerPort adapter — fixed-size thread pool with bounded queue.

Backed by a ``threading.Thread`` pool + ``queue.Queue`` for backpressure.
Supports graceful shutdown, idle timeout, and usage stats.

Usage:
    from l1.kernel.worker_thread import ThreadPoolWorker
    pool = ThreadPoolWorker(min_workers=4, max_workers=32)
    result = pool.submit(some_fn, arg1, arg2)
    pool.shutdown(wait=True)
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from l1.kernel.params.api import (
    WORKER_POOL_IDLE_TIMEOUT,
    WORKER_POOL_MAX,
    WORKER_POOL_MIN,
    WORKER_POOL_QUEUE_SIZE,
    WORKER_POOL_TASK_TIMEOUT,
)
from l1.kernel.ports import Result, WorkerPort

logger = logging.getLogger(__name__)


class _Worker(threading.Thread):
    """Internal worker thread — pulls callables from the job queue."""

    def __init__(self, pool: ThreadPoolWorker, idx: int) -> None:
        super().__init__(daemon=True, name=f"worker-{idx}")
        self._pool = pool
        self._idx = idx

    def run(self) -> None:
        """Main worker loop — execute queued tasks until retired or shut down."""
        pool = self._pool
        while True:
            try:
                item = pool._queue.get(timeout=pool._idle_timeout)
            except queue.Empty:
                # Idle timeout — re-check queue non-blocking before retiring
                try:
                    item = pool._queue.get_nowait()
                except queue.Empty:
                    # Queue still empty — try to shrink
                    if not pool._try_shrink(self):
                        continue  # pool said no, keep polling
                    return  # we were retired
                # Got an item from the non-blocking check — process it below
            if item is None:  # sentinel: shutdown
                pool._queue.task_done()
                return
            fn, args, kwargs, result_holder = item
            try:
                with pool._lock:
                    pool._active += 1
                fn(*args, **kwargs)
                result_holder["success"] = True
            except Exception as e:
                result_holder["success"] = False
                result_holder["error"] = str(e)
                logger.debug("worker-%d: task failed: %s", self._idx, e)
            finally:
                with pool._lock:
                    pool._active -= 1
                    pool._completed += 1
                pool._queue.task_done()


class ThreadPoolWorker(WorkerPort):
    """Fixed-size thread pool implementing WorkerPort.

    Dynamic sizing between *min_workers* and *max_workers*:
      - Starts with *min_workers* threads.
      - Grows up to *max_workers* when the queue backs up.
      - Shrinks back toward *min_workers* after *idle_timeout* of inactivity.
    """

    def __init__(
        self,
        min_workers: int = WORKER_POOL_MIN,
        max_workers: int = WORKER_POOL_MAX,
        queue_size: int = WORKER_POOL_QUEUE_SIZE,
        idle_timeout: float = WORKER_POOL_IDLE_TIMEOUT,
        task_timeout: float = WORKER_POOL_TASK_TIMEOUT,
    ) -> None:
        if max_workers < min_workers:
            max_workers = min_workers
        self._min = min_workers
        self._max = max_workers
        self._queue_size = queue_size
        self._idle_timeout = idle_timeout
        self._task_timeout = task_timeout
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._workers: list[_Worker] = []
        # RLock: _grow() calls _add_worker() while holding this lock, and
        # _add_worker() re-acquires it (AGENTS.md reentrant-lock convention).
        self._lock = threading.RLock()
        self._active = 0
        self._completed = 0
        self._rejected = 0
        self._shutdown = False
        self._next_idx = 0

        # Start minimum workers
        for _ in range(min_workers):
            self._add_worker()

    # ── WorkerPort interface ───────────────────────────────────────────────

    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> Result:
        """Submit a callable for execution. Returns immediately.

        If the queue is full, the oldest pending task is dropped (FIFO eviction).
        """
        if self._shutdown:
            self._rejected += 1
            return Result.fail("pool is shut down")

        result_holder: dict = {"success": False, "error": ""}

        try:
            self._queue.put_nowait((fn, args, kwargs, result_holder))
        except queue.Full:
            # Backpressure: drop oldest pending task
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((fn, args, kwargs, result_holder))
                self._rejected += 1  # the dropped one
            except queue.Empty:
                self._rejected += 1
                return Result.fail("queue full and eviction failed")

        # Grow the pool if the queue is backing up
        if self._queue.qsize() > len(self._workers) * 2:
            self._grow()

        return Result.ok(submitted=True)

    def shutdown(self, wait: bool = True, timeout: float | None = None) -> Result:
        """Shut down the pool. Sends sentinel per worker to drain the queue."""
        self._shutdown = True
        with self._lock:
            n = len(self._workers)
        for _ in range(n):
            self._queue.put(None)  # sentinel
        if wait:
            deadline = None if timeout is None else time.monotonic() + timeout
            for w in list(self._workers):
                remaining = deadline - time.monotonic() if deadline else None
                if remaining is not None and remaining <= 0:
                    break
                w.join(timeout=remaining)
        with self._lock:
            self._workers.clear()
        return Result.ok(shutdown=True)

    def stats(self) -> dict:
        """Return pool sizing, activity, and throughput counters."""
        with self._lock:
            return {
                "pool_size": len(self._workers),
                "active": self._active,
                "queued": self._queue.qsize(),
                "completed": self._completed,
                "rejected": self._rejected,
                "min": self._min,
                "max": self._max,
                "shutdown": self._shutdown,
            }

    # ── Internal ──────────────────────────────────────────────────────────

    def _add_worker(self) -> _Worker:
        with self._lock:
            w = _Worker(self, self._next_idx)
            self._next_idx += 1
            self._workers.append(w)
            w.start()
            return w

    def _grow(self) -> None:
        with self._lock:
            current = len(self._workers)
            if current >= self._max:
                return
            target = min(current + 2, self._max)
            for _ in range(target - current):
                self._add_worker()
            logger.debug("pool grew: %d → %d workers", current, target)

    def _try_shrink(self, worker: _Worker) -> bool:
        """Attempt to retire *worker*. Returns True if the worker should exit."""
        with self._lock:
            current = len(self._workers)
            if current <= self._min or self._shutdown:
                return False
            try:
                self._workers.remove(worker)
            except ValueError:
                return False
            logger.debug("pool shrunk: %d → %d workers", current, current - 1)
            return True
