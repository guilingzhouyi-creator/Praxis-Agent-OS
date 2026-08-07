"""DaemonPool — bounded daemon-worker task pool for fire-and-forget contexts.

Drop-in replacement for the ThreadPoolExecutor usage inside Praxis buses
and boot steps. The one behavioral difference that matters: workers are
daemon threads, so a lingering pool never blocks interpreter exit.

``concurrent.futures.ThreadPoolExecutor`` workers are non-daemon: after
``boot()`` (or any MonitorBus init) the process keeps ``mon_*`` / ``boot_*``
threads alive, and Python's ``threading._shutdown`` joins them indefinitely
— CLI exits hang, and pytest runs after boot tests hang non-deterministically
(threads racing the fixtures). This pool keeps the same ``submit`` /
``shutdown`` / ``_work_queue`` surface while workers die with the process.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

logger = logging.getLogger(__name__)


class DaemonPool:
    """Fixed-size pool of daemon workers pulling callables from a queue.

    Args:
        max_workers: number of daemon worker threads.
        thread_name_prefix: worker name prefix (``f"{prefix}-{i}"``).
        queue_maxsize: bounded task queue; ``submit`` drops silently when full.
    """

    def __init__(self, max_workers: int = 2, thread_name_prefix: str = "daemon", queue_maxsize: int = 0) -> None:
        self._work_queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._lock = threading.Lock()
        self._running = True
        self._max_workers = max_workers
        self._workers: list[threading.Thread] = []
        for i in range(max_workers):
            w = threading.Thread(target=self._loop, daemon=True, name=f"{thread_name_prefix}-{i}")
            w.start()
            self._workers.append(w)

    def _loop(self) -> None:
        while True:
            item = self._work_queue.get()
            if item is None:
                self._work_queue.task_done()
                return
            fn, args, kwargs = item
            try:
                fn(*args, **kwargs)
            except Exception as e:
                logger.debug("daemon task failed: %s", e)
            finally:
                self._work_queue.task_done()

    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> Future:
        """Queue a callable; returns a Future compatible with ``.result()``.

        If the queue is full or the pool is shut down, the task is dropped
        and the returned Future resolves immediately with a RuntimeError.
        """
        fut: Future = Future()

        def _wrapper() -> None:
            try:
                fut.set_result(fn(*args, **kwargs))
            except Exception as e:  # noqa: BLE001
                fut.set_exception(e)

        with self._lock:
            running = self._running
        if not running:
            fut.set_exception(RuntimeError("pool is shut down"))
            return fut
        try:
            self._work_queue.put_nowait((_wrapper, (), {}))
        except queue.Full:
            fut.set_exception(RuntimeError("daemon pool queue full"))
        return fut

    def shutdown(self, wait: bool = True, timeout: float | None = None) -> None:
        """Stop accepting work; sentinel-terminate workers (daemon, so a
        non-wait shutdown never blocks interpreter exit)."""
        with self._lock:
            self._running = False
        for _ in range(len(self._workers)):
            with contextlib.suppress(queue.Full):
                self._work_queue.put_nowait(None)
        if wait:
            for w in self._workers:
                w.join(timeout=timeout)
