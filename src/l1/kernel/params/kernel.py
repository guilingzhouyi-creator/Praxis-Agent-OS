"""Constants: kernel primitives — event, interrupt, registry, vfs, swapper, syscall, tool chain, boot.

Split from:
  allocator/process/resource  → params/allocator.py
  mutex/semaphore/barrier/IPC → params/sync.py
  gatechain                   → params/gatechain.py
"""

from dataclasses import dataclass
from typing import Final

# ── Backward-compatible re-exports (callers can still import from kernel.py) ──
from .allocator import *  # noqa: F401, F403
from .gatechain import *  # noqa: F401, F403
from .sync import *  # noqa: F401, F403

# ── Event bus ──
EVENT_MAX_HISTORY: Final[int] = 200
# Default page size for event-bus history queries
EVENT_QUERY_LIMIT: Final[int] = 20
# Worker threads serving the event bus
EVENT_BUS_WORKERS: Final[int] = 4
# Max events queued before dropping
EVENT_BUS_MAX_QUEUED: Final[int] = 500
# Seconds between kernel heartbeats
HEARTBEAT_INTERVAL: Final[float] = 15.0

# ── Event extras ──
EVENT_STORE_SENDER: Final[str] = "event_store"
EVENT_HEARTBEAT_SENDER: Final[str] = "system"


# ── Interrupt table ──
INTERRUPT_MAX_HISTORY: Final[int] = 200
# Default page size for interrupt-table queries
INTERRUPT_QUERY_LIMIT: Final[int] = 20


# ── Registry ──
# Default page size for registry audit queries
REGISTRY_QUERY_LIMIT: Final[int] = 20


# ── Tool chain ──
TOOLCHAIN_MAX_CALLS: Final[int] = 5000
# Default page size for tool-chain queries
TOOLCHAIN_QUERY_LIMIT: Final[int] = 20


# ── Device manager ──
DEVICE_HEALTH_INTERVAL: Final[float] = 60.0
DEVICE_DEGRADED_THRESHOLD: Final[float] = 0.5
# Health ratio below which a device is marked down
DEVICE_DOWN_THRESHOLD: Final[float] = 0.9
# Minimum calls before degraded status applies
DEVICE_MIN_CALLS_DEGRADED: Final[int] = 5
# Minimum calls before down status applies
DEVICE_MIN_CALLS_DOWN: Final[int] = 10


# ── Watchdog ──
WATCHDOG_INTERVAL: Final[float] = 15.0
WATCHDOG_ZOMBIE_LIMIT: Final[int] = 50
# Max idle seconds before watchdog sweeps
WATCHDOG_IDLE_LIMIT: Final[float] = 300.0
# Interrupt bursts above which watchdog fires
WATCHDOG_INTERRUPT_LIMIT: Final[int] = 1000


# ── Swapper ──

SWAPPER_DEFAULT_INTERVAL: Final[float] = 30.0
# Swap interval applied right after boot
SWAPPER_BOOT_INTERVAL: Final[float] = 60.0
# Memory-pressure percent triggering low-pressure swap
SWAPPER_PRESSURE_LOW: Final[float] = 60.0
# Memory-pressure percent triggering medium-pressure swap
SWAPPER_PRESSURE_MEDIUM: Final[float] = 75.0
# Memory-pressure percent triggering high-pressure swap
SWAPPER_PRESSURE_HIGH: Final[float] = 90.0
# Entries swapped per swap pass
SWAPPER_SWAP_COUNT: Final[int] = 10
# Cap on entries restored per recall
SWAPPER_RECALL_LIMIT: Final[int] = 999999
# Entries scanned per compaction query
SWAPPER_COMPACT_QUERY_LIMIT: Final[int] = 20
# Minimum entries before compaction runs
SWAPPER_COMPACT_MIN_ENTRIES: Final[int] = 10
# Minimum compacted entries kept per agent
SWAPPER_COMPACT_MIN_PER_AGENT: Final[int] = 3
# Importance cutoff for compacted entries
SWAPPER_COMPACT_IMPORTANCE: Final[float] = 0.5
# Tags stamped on compacted entries
SWAPPER_COMPACT_TAGS: Final[tuple[str, ...]] = ("compacted", "auto")
# Importance below which entries swap to ring 3
SWAPPER_SWAP_OUT_IMPORTANCE: Final[float] = 0.3


# ── VFS ──
VFS_DEFAULT_MIN_RING: Final[int] = 1
VFS_PROC_PATH: Final[str] = "/proc"


# ── Syscall ──
SYSCALL_AUDIT_MAX: Final[int] = 5000
SYSCALL_AUDIT_DETAIL_MAXLEN: Final[int] = 200
# Max syscall audit rows returned per query
SYSCALL_AUDIT_QUERY_LIMIT: Final[int] = 100
# Audit rows shown in CLI output
SYSCALL_AUDIT_CLI_LIMIT: Final[int] = 20
# Audit rows buffered before flush
AUDIT_FLUSH_SIZE: Final[int] = 32
# Fallback handler for unknown syscalls
SYSCALL_DEFAULT_FALLBACK: Final[str] = "default"
# Default signal type for syscall dispatch
SYSCALL_DEFAULT_SIGNAL_TYPE: Final[str] = "TASK_ASSIGN"
# Default token cost of a syscall
SYSCALL_DEFAULT_COST: Final[int] = 1
# Default ring required to invoke a syscall
SYSCALL_DEFAULT_RING: Final[int] = 1
# Default resource charged per syscall
SYSCALL_DEFAULT_RESOURCE: Final[str] = "tokens"
# Agent id that registers syscalls
SYSCALL_REGISTER_DEFAULT_AGENT: Final[str] = "kernel"


# ── Stagnation detection ──
STAGNATION_SPIN_THRESHOLD: Final[int] = 3
STAGNATION_OSCILLATION_CYCLES: Final[int] = 2
# Max score drift tolerated before stagnation
STAGNATION_NO_DRIFT_EPSILON: Final[float] = 0.01
# Score decay applied per stagnation pass
STAGNATION_DIMINISHING_RATE: Final[float] = 0.01
# Max stagnation passes before escalation
STAGNATION_MAX_ITERATIONS: Final[int] = 30


# ── Tool chain (extra) ──
CHAIN_KEY_ENV_VAR: Final[str] = "PRAXIS_CHAIN_KEY"


# ── PraxisRing (tool ring definition) ──

RING_1: Final[str] = "RING_1"
# Name of the intermediate privilege ring
RING_2_5: Final[str] = "RING_2_5"
# Name of the highest privilege ring
RING_3: Final[str] = "RING_3"

# Ring name to numeric level mapping
RING_NUM_MAP: Final[dict[str, int]] = {RING_1: 1, RING_2_5: 2, RING_3: 3}
# Numeric ring level to name mapping
RING_NAME_MAP: Final[dict[int, str]] = {1: RING_1, 2: RING_2_5, 3: RING_3}


class PraxisRing:
    """PraxisRing — praxis ring record (TOOL_RING_CAPACITY)."""

    # Tool entries per ring in PraxisRing records
    TOOL_RING_CAPACITY: int = 50


# ── RequestPoolConfig (request pool scheduling) ──


@dataclass
class RequestPoolConfig:
    """RequestPoolConfig — request pool config record (CAPACITY, EVICT_ON_FULL, WEIGHT_REPUTATION, WEIGHT_PRIORITY, WEIGHT_WAIT)."""

    # Default request pool capacity
    CAPACITY: int = 8
    # Evict lowest-weight request when the pool is full
    EVICT_ON_FULL: bool = True
    # Weight of reputation in the eviction score
    WEIGHT_REPUTATION: float = 0.40
    # Weight of priority in the eviction score
    WEIGHT_PRIORITY: float = 0.35
    # Weight of wait time in the eviction score
    WEIGHT_WAIT: float = 0.25
    # Max seconds a request may wait in the pool
    MAX_WAIT_S: float = 300.0


# ── Boot / Shutdown ──
BOOT_STEP_TIMEOUT: Final[float] = 60.0
SHUTDOWN_TIMEOUT: Final[float] = 30.0


# ── Cadence tracking ──
CADENCE_MAX_STEPS: Final[int] = 50
CADENCE_MAX_ATTEMPTS: Final[int] = 3


# ── Subprocess defaults ──
RUN_SUBPROCESS_TIMEOUT: Final[int] = 15
