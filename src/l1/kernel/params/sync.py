"""Constants: sync primitives — mutex, semaphore, barrier, rwlock."""

from typing import Final

# ── Locking primitives (mutex / semaphore / rwlock share one default timeout) ──

# Default acquire timeout shared by mutex, semaphore and rwlock (seconds).
# Change here to retune all three; keep the per-primitive names as aliases
# so callers stay readable and can diverge later if ever needed.
LOCK_DEFAULT_TIMEOUT: Final[float] = 30.0

# ── Mutex ──

MUTEX_DEFAULT_TIMEOUT: Final[float] = LOCK_DEFAULT_TIMEOUT
# Default priority used by new mutexes and boost inheritance baseline
MUTEX_DEFAULT_PRIORITY: Final[float] = 5.0
# Poll interval while a waiter spins before rechecking lock state
MUTEX_POLL_INTERVAL: Final[float] = 0.05
# Wait time before deadlock detection flags a holder as stuck
MUTEX_DEADLOCK_TIMEOUT: Final[float] = 0.5
# Wait-fraction threshold above which a holder gets priority-boosted
MUTEX_BOOST_THRESHOLD: Final[float] = 0.5
# Seconds a waiter waits before cycle detection starts scanning
MUTEX_CYCLE_DETECT_AFTER: Final[float] = 1.0
# Minimum interval between cycle-detection scans (debounce window)
MUTEX_CYCLE_DEBOUNCE: Final[float] = 60.0
# Maximum dependency depth traced per cycle scan
MUTEX_CYCLE_MAX_DEPTH: Final[int] = 20


# ── Semaphore ──

SEMAPHORE_DEFAULT_MAX: Final[int] = 3
# Default acquire timeout for semaphore slots (seconds)
SEMAPHORE_DEFAULT_TIMEOUT: Final[float] = LOCK_DEFAULT_TIMEOUT
# Poll interval while waiting for a free semaphore slot
SEMAPHORE_POLL_INTERVAL: Final[float] = 0.1


# ── Barrier ──

BARRIER_DEFAULT_COUNT: Final[int] = 3
# Default wait timeout for barrier arrival (seconds)
BARRIER_DEFAULT_TIMEOUT: Final[float] = 60.0


# ── RWLock ──

RWLOCK_DEFAULT_TIMEOUT: Final[float] = LOCK_DEFAULT_TIMEOUT
# Poll interval while waiting for a read/write lock
RWLOCK_POLL_INTERVAL: Final[float] = 0.05


# ── IPC extras ──

IPC_DEFAULT_PRIORITY: Final[float] = 5.0
# Length (chars) of generated IPC message IDs
IPC_MSG_ID_LENGTH: Final[int] = 12
# Default timeout for IPC request/response round trips (seconds)
IPC_REQUEST_TIMEOUT: Final[float] = 5.0
