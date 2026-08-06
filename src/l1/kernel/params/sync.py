"""Constants: sync primitives — mutex, semaphore, barrier, rwlock."""

from typing import Final

# ── Mutex ──

MUTEX_DEFAULT_TIMEOUT: Final[float] = 30.0
MUTEX_DEFAULT_PRIORITY: Final[float] = 5.0
MUTEX_POLL_INTERVAL: Final[float] = 0.05
MUTEX_DEADLOCK_TIMEOUT: Final[float] = 0.5
MUTEX_BOOST_THRESHOLD: Final[float] = 0.5
MUTEX_CYCLE_DETECT_AFTER: Final[float] = 1.0
MUTEX_CYCLE_DEBOUNCE: Final[float] = 60.0
MUTEX_CYCLE_MAX_DEPTH: Final[int] = 20


# ── Semaphore ──

SEMAPHORE_DEFAULT_MAX: Final[int] = 3
SEMAPHORE_DEFAULT_TIMEOUT: Final[float] = 30.0
SEMAPHORE_POLL_INTERVAL: Final[float] = 0.1


# ── Barrier ──

BARRIER_DEFAULT_COUNT: Final[int] = 3
BARRIER_DEFAULT_TIMEOUT: Final[float] = 60.0


# ── RWLock ──

RWLOCK_DEFAULT_TIMEOUT: Final[float] = 30.0
RWLOCK_POLL_INTERVAL: Final[float] = 0.05


# ── IPC extras ──

IPC_DEFAULT_PRIORITY: Final[float] = 5.0
IPC_MSG_ID_LENGTH: Final[int] = 12
IPC_REQUEST_TIMEOUT: Final[float] = 5.0
