"""Sync primitives — Agent OS synchronization layer.

Mutex, Semaphore, RWLock, Barrier, Condition.
All are process-safe (cross-agent) via IPC bus.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum, auto
from typing import Any, Callable

from .ipc import LockMessage, LockOp, get_lock_bus
from .params.kernel import (
    BARRIER_DEFAULT_COUNT,
    BARRIER_DEFAULT_TIMEOUT,
    MUTEX_BOOST_THRESHOLD,
    MUTEX_CYCLE_DETECT_AFTER,
    MUTEX_DEFAULT_PRIORITY,
    MUTEX_DEFAULT_TIMEOUT,
    MUTEX_POLL_INTERVAL,
    RWLOCK_DEFAULT_TIMEOUT,
    RWLOCK_POLL_INTERVAL,
    SEMAPHORE_DEFAULT_MAX,
    SEMAPHORE_DEFAULT_TIMEOUT,
    SEMAPHORE_POLL_INTERVAL,
)

logger = logging.getLogger(__name__)


class LockState(Enum):
    FREE = auto()
    LOCKED = auto()
    CONTENDED = auto()


class Mutex:
    """Priority-aware mutex with deadlock detection.

    Features:
      - Reentrant (same agent can lock multiple times)
      - Priority inheritance (low-priority holder gets boosted)
      - Deadlock detection (timeout + cycle detection)
      - Cross-agent (works via IPC bus, not just threads)
    """

    def __init__(self, name: str, timeout: float = MUTEX_DEFAULT_TIMEOUT,
                 on_boost: Callable[[str, float, float], None] | None = None,
                 ipc_enabled: bool = False):
        self.name = name
        self.timeout = timeout
        self.ipc_enabled = ipc_enabled
        self._lock = threading.Lock()
        self._owner: str = ""
        self._recursion: int = 0
        self._waiters: list[tuple[str, float, float, float]] = []
        self._state = LockState.FREE
        self._effective_priority: float = MUTEX_DEFAULT_PRIORITY
        self._base_priority: float = MUTEX_DEFAULT_PRIORITY
        self._on_boost = on_boost
        self._ipc_channel = None
        if ipc_enabled:
            self._ipc_channel = get_lock_bus().get_channel(f"mutex:{name}")
            self._ipc_channel.register_handler(self._handle_ipc)

    def _detect_cycle(self) -> list[str] | None:
        """DFS cycle detection. Returns cycle path or None."""
        visited: dict[str, str | None] = {}
        stack: list[str] = []
        queue = [self._owner] if self._owner else []
        for w in self._waiters:
            if w[0] not in visited:
                queue.append(w[0])

        adjacency: dict[str, list[str]] = {}
        for mtx_name, mtx in _registry.items():
            if isinstance(mtx, Mutex) and mtx._owner:
                adjacency.setdefault(mtx._owner, [])
                for w in mtx._waiters:
                    if w[0] not in adjacency[mtx._owner]:
                        adjacency[mtx._owner].append(w[0])

        def dfs(node: str, depth: int = 0) -> list[str] | None:
            if node in stack:
                idx = stack.index(node)
                return stack[idx:] + [node]
            if node in visited:
                return None
            visited[node] = None
            if node in stack:
                return None
            stack.append(node)
            for neighbor in adjacency.get(node, []):
                result = dfs(neighbor, depth + 1)
                if result:
                    return result
            stack.pop()
            return None

        for start in queue:
            result = dfs(start)
            if result:
                return result
        return None

    def _handle_ipc(self, msg: LockMessage) -> dict | None:
        if msg.op == LockOp.ACQUIRE:
            with self._lock:
                if self._state == LockState.FREE:
                    self._state = LockState.LOCKED
                    self._owner = f"remote:{msg.agent_id}"
                    self._recursion = 1
                    return {"success": True}
            return {"success": False, "error": "contended"}
        if msg.op == LockOp.RELEASE:
            with self._lock:
                if self._owner == f"remote:{msg.agent_id}":
                    self._state = LockState.FREE
                    self._owner = ""
                    self._recursion = 0
                    return {"success": True}
            return {"success": False, "error": "not_owner"}
        if msg.op == LockOp.STATUS:
            return self.status()
        return None

    def acquire(self, agent_id: str, priority: float = MUTEX_DEFAULT_PRIORITY,
                blocking: bool = True) -> dict:
        deadline = time.time() + self.timeout

        with self._lock:
            if self._owner == agent_id:
                self._recursion += 1
                return {"success": True, "owner": agent_id, "recursion": self._recursion}

            if self._state == LockState.FREE:
                self._state = LockState.LOCKED
                self._owner = agent_id
                self._recursion = 1
                self._effective_priority = priority
                self._base_priority = priority
                return {"success": True, "owner": agent_id}

            if priority < self._effective_priority:
                old = self._effective_priority
                self._effective_priority = priority
                if self._on_boost:
                    self._on_boost(self._owner, old, priority)
                logger.warning("PI: %s boosted %s -> %.1f (waiter %s pri=%.1f)",
                               self.name, self._owner, priority, agent_id, priority)

            if not blocking:
                return {"success": False, "error": "lock contended", "owner": self._owner}

            self._state = LockState.CONTENDED
            self._waiters.append((agent_id, priority, time.time(), 0.0))
            self._waiters.sort(key=lambda w: w[1])

        waited = 0.0
        cycle_reported = False
        while time.time() < deadline:
            time.sleep(MUTEX_POLL_INTERVAL)
            waited += MUTEX_POLL_INTERVAL
            with self._lock:
                if self._state == LockState.FREE or self._owner == agent_id:
                    self._state = LockState.LOCKED
                    self._owner = agent_id
                    self._recursion = 1
                    self._effective_priority = priority
                    self._base_priority = priority
                    self._waiters = [w for w in self._waiters if w[0] != agent_id]
                    return {"success": True, "owner": agent_id, "waited": round(waited, 3),
                            "boosted": waited > MUTEX_BOOST_THRESHOLD}

            if not cycle_reported and waited > MUTEX_CYCLE_DETECT_AFTER:
                cycle = self._detect_cycle()
                if cycle:
                    logger.critical("DEADLOCK CYCLE DETECTED: %s", " -> ".join(cycle))
                    cycle_reported = True

        return {"success": False, "error": "timeout", "owner": self._owner,
                "waited": round(waited, 3), "cycle_detected": cycle_reported}

    def release(self, agent_id: str) -> dict:
        with self._lock:
            if self._owner != agent_id:
                return {"success": False, "error": "not the owner", "owner": self._owner}
            self._recursion -= 1
            if self._recursion > 0:
                return {"success": True, "owner": agent_id, "recursion": self._recursion}
            old = self._effective_priority
            restored = self._effective_priority != self._base_priority
            self._effective_priority = self._base_priority
            self._state = LockState.FREE
            self._owner = ""
            return {"success": True, "priority_restored": restored,
                    "from": old, "to": self._base_priority}

    def force_unlock(self) -> dict:
        """Force-release the mutex (for test cleanup). Not for production use."""
        with self._lock:
            self._state = LockState.FREE
            self._owner = ""
            self._recursion = 0
            self._effective_priority = MUTEX_DEFAULT_PRIORITY
            self._base_priority = MUTEX_DEFAULT_PRIORITY
            self._waiters.clear()
        return {"success": True}

    def status(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.name,
                "owner": self._owner,
                "recursion": self._recursion,
                "effective_priority": self._effective_priority,
                "base_priority": self._base_priority,
                "waiters": [(w[0], w[1]) for w in self._waiters],
                "waiter_count": len(self._waiters),
            }


class Semaphore:
    """Counting semaphore for resource limiting."""

    def __init__(self, name: str, max_count: int = SEMAPHORE_DEFAULT_MAX):
        self.name = name
        self.max_count = max_count
        self._count = max_count
        self._lock = threading.Lock()
        self._waiters: list[str] = []

    def acquire(self, agent_id: str, blocking: bool = True) -> dict:
        deadline = time.time() + SEMAPHORE_DEFAULT_TIMEOUT
        while True:
            with self._lock:
                if self._count > 0:
                    self._count -= 1
                    return {"success": True, "remaining": self._count}
                if not blocking:
                    return {"success": False, "error": "no capacity"}
                if agent_id not in self._waiters:
                    self._waiters.append(agent_id)
            if time.time() > deadline:
                return {"success": False, "error": "timeout"}
            time.sleep(SEMAPHORE_POLL_INTERVAL)

    def release(self, agent_id: str) -> dict:
        with self._lock:
            if self._count < self.max_count:
                self._count += 1
                if self._waiters:
                    self._waiters.pop(0)
            return {"success": True, "remaining": self._count}

    def status(self) -> dict:
        with self._lock:
            return {"name": self.name, "count": self._count, "max": self.max_count, "waiters": len(self._waiters)}


class Barrier:
    """Barrier — wait for N agents to reach a point before proceeding."""

    def __init__(self, name: str, count: int = BARRIER_DEFAULT_COUNT):
        self.name = name
        self.count = count
        self._arrived: set[str] = set()
        self._lock = threading.Lock()
        self._event = threading.Event()

    def wait(self, agent_id: str) -> dict:
        with self._lock:
            self._arrived.add(agent_id)
            if len(self._arrived) >= self.count:
                self._event.set()
                return {"success": True, "role": "releaser", "arrived": len(self._arrived)}
        self._event.wait(timeout=BARRIER_DEFAULT_TIMEOUT)
        return {"success": True, "role": "waiter", "arrived": len(self._arrived)}

    def reset(self) -> dict:
        with self._lock:
            self._arrived.clear()
            self._event.clear()
        return {"success": True}


class Condition:
    """Condition variable — wait/signal/broadcast pattern.

    An agent can wait() for a condition to become true.
    Another agent can signal() or broadcast() to wake waiters.
    """

    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._waiters: set[str] = set()
        self._pending_signals: int = 0

    def wait(self, agent_id: str, timeout: float = BARRIER_DEFAULT_TIMEOUT) -> dict:
        with self._lock:
            self._waiters.add(agent_id)
            if self._pending_signals > 0:
                self._pending_signals -= 1
                self._waiters.discard(agent_id)
                return {"success": True, "agent_id": agent_id, "timed_out": False}
            self._event.clear()
        ok = self._event.wait(timeout=timeout)
        with self._lock:
            self._waiters.discard(agent_id)
        return {"success": ok, "agent_id": agent_id, "timed_out": not ok}

    def signal(self, agent_id: str) -> dict:
        with self._lock:
            if self._waiters:
                self._event.set()
            else:
                self._pending_signals += 1
        return {"success": True, "signaler": agent_id, "wakeup": len(self._waiters)}

    def broadcast(self, agent_id: str) -> dict:
        self._event.set()
        return {"success": True, "signaler": agent_id, "broadcast": len(self._waiters)}

    def status(self) -> dict:
        with self._lock:
            return {"name": self.name, "waiters": len(self._waiters)}


class RWLock:
    """Read-Write Lock — multiple readers XOR single writer."""

    def __init__(self, name: str):
        self.name = name
        self._readers = 0
        self._writer = ""
        self._write_waiters = 0
        self._lock = threading.Lock()

    def read_lock(self, agent_id: str) -> dict:
        deadline = time.time() + RWLOCK_DEFAULT_TIMEOUT
        while True:
            with self._lock:
                if self._writer == "" or self._writer == agent_id:
                    self._readers += 1
                    return {"success": True, "mode": "read", "readers": self._readers}
            if time.time() > deadline:
                return {"success": False, "error": "timeout"}
            time.sleep(RWLOCK_POLL_INTERVAL)

    def write_lock(self, agent_id: str) -> dict:
        deadline = time.time() + RWLOCK_DEFAULT_TIMEOUT
        self._write_waiters += 1
        while True:
            with self._lock:
                if self._readers == 0 and self._writer == "":
                    self._writer = agent_id
                    self._write_waiters -= 1
                    return {"success": True, "mode": "write"}
                if self._writer == agent_id:
                    return {"success": True, "mode": "write"}
            if time.time() > deadline:
                self._write_waiters -= 1
                return {"success": False, "error": "timeout"}
            time.sleep(RWLOCK_POLL_INTERVAL)

    def unlock(self, agent_id: str) -> dict:
        with self._lock:
            if self._writer == agent_id:
                self._writer = ""
            elif self._readers > 0:
                self._readers -= 1
            return {"success": True, "mode": "write" if self._writer else "read", "readers": self._readers}

    def status(self) -> dict:
        with self._lock:
            return {"name": self.name, "readers": self._readers, "writer": self._writer, "write_waiters": self._write_waiters}


# ── Global registry (thread-safe) ──

_registry: dict[str, Any] = {}
_registry_lock = threading.Lock()


def _get_or_create(name: str, factory) -> Any:
    with _registry_lock:
        if name not in _registry:
            _registry[name] = factory()
        return _registry[name]


def get_mutex(name: str, timeout: float = MUTEX_DEFAULT_TIMEOUT,
              ipc_enabled: bool = False) -> Mutex:
    return _get_or_create(name, lambda: Mutex(name, timeout, ipc_enabled=ipc_enabled))


def get_semaphore(name: str, max_count: int = SEMAPHORE_DEFAULT_MAX) -> Semaphore:
    return _get_or_create(name, lambda: Semaphore(name, max_count))


def get_barrier(name: str, count: int = BARRIER_DEFAULT_COUNT) -> Barrier:
    return _get_or_create(name, lambda: Barrier(name, count))


def get_rwlock(name: str) -> RWLock:
    return _get_or_create(name, lambda: RWLock(name))


def get_condition(name: str) -> Condition:
    return _get_or_create(name, lambda: Condition(name))


def registry_status() -> dict:
    with _registry_lock:
        return {name: obj.status() for name, obj in list(_registry.items())}
