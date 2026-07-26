"""Constants: kernel primitives — allocator, sync, process, gatechain, vfs."""

import os as _os_env
from dataclasses import dataclass
from typing import Any, Final


# ── Allocator ──

@dataclass
class AllocatorDefaults:
    tokens: int = 4096
    ring1: int = 32
    ring2: int = 200
    ring3: int = 1000
    sandbox_kb: int = 10240


ALLOCATOR_DEFAULTS: Final = AllocatorDefaults()
ALLOCATOR_FALLBACK_LIMIT: Final[int] = 100
ALLOCATOR_PRESSURE_THRESHOLD: Final[float] = 80.0
ALLOCATOR_OBSERVE_PURPOSE: Final[str] = "observe"


# ── Mutex ──

MUTEX_DEFAULT_TIMEOUT: Final[float] = 30.0
MUTEX_DEFAULT_PRIORITY: Final[float] = 5.0
MUTEX_POLL_INTERVAL: Final[float] = 0.05
MUTEX_DEADLOCK_TIMEOUT: Final[float] = 0.5


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


# ── Event ──


# ── Event bus ──
EVENT_MAX_HISTORY: Final[int] = 200
EVENT_QUERY_LIMIT: Final[int] = 20
HEARTBEAT_INTERVAL: Final[float] = 15.0

# ── Interrupt table ──
INTERRUPT_MAX_HISTORY: Final[int] = 200
INTERRUPT_QUERY_LIMIT: Final[int] = 20

# ── Registry ──
REGISTRY_QUERY_LIMIT: Final[int] = 20

# ── Tool chain ──
TOOLCHAIN_MAX_CALLS: Final[int] = 5000
TOOLCHAIN_QUERY_LIMIT: Final[int] = 20

# ── Device manager ──
DEVICE_HEALTH_INTERVAL: Final[float] = 60.0
DEVICE_DEGRADED_THRESHOLD: Final[float] = 0.5
DEVICE_DOWN_THRESHOLD: Final[float] = 0.9
DEVICE_MIN_CALLS_DEGRADED: Final[int] = 5
DEVICE_MIN_CALLS_DOWN: Final[int] = 10

# ── Watchdog ──
WATCHDOG_INTERVAL: Final[float] = 15.0
WATCHDOG_ZOMBIE_LIMIT: Final[int] = 50
WATCHDOG_IDLE_LIMIT: Final[float] = 300.0
WATCHDOG_INTERRUPT_LIMIT: Final[int] = 1000


# ── Swapper ──

SWAPPER_DEFAULT_INTERVAL: Final[float] = 30.0
SWAPPER_PRESSURE_LOW: Final[float] = 60.0
SWAPPER_PRESSURE_MEDIUM: Final[float] = 75.0
SWAPPER_PRESSURE_HIGH: Final[float] = 90.0
SWAPPER_SWAP_COUNT: Final[int] = 10
SWAPPER_COMPACT_QUERY_LIMIT: Final[int] = 20
SWAPPER_COMPACT_MIN_ENTRIES: Final[int] = 10
SWAPPER_COMPACT_MIN_PER_AGENT: Final[int] = 3
SWAPPER_COMPACT_IMPORTANCE: Final[float] = 0.3
SWAPPER_COMPACT_TAGS: Final[tuple[str, ...]] = ("compacted", "auto")


# ── Resource ──

@dataclass
class ResourceProfileDefaults:
    max_tokens: int = 4096
    max_workers: int = 4
    max_scouts: int = 3
    max_memory: int = 100
    priority: int = 5


RESOURCE_PROFILE_DEFAULTS: Final = ResourceProfileDefaults()


# ── Allocator extras ──
ALLOCATOR_DEFAULT_AMOUNT: Final[int] = 1
ALLOCATOR_PCT_PRECISION: Final[int] = 1
ALLOCATOR_SWAP_SOURCE: Final[str] = "ring1"
ALLOCATOR_SWAP_TARGET: Final[str] = "ring2"
ALLOCATOR_SWAP_COUNT: Final[int] = 5
ALLOCATOR_DISK_RESOURCE: Final[str] = "disk"
ALLOCATE_AMOUNT: Final[int] = 200
ALLOCATOR_DEFAULT_PRIORITY: Final[int] = 5

# ── Allocator resource keys (magic strings) ──
RESOURCE_TOKENS: Final[str] = "tokens"
RESOURCE_RING1: Final[str] = "ring1"
RESOURCE_RING2: Final[str] = "ring2"
RESOURCE_RING3: Final[str] = "ring3"
RESOURCE_SANDBOX_KB: Final[str] = "sandbox_kb"
RESOURCE_PRIORITY: Final[str] = "priority"

# ── Event extras ──
EVENT_STORE_SENDER: Final[str] = "event_store"
EVENT_HEARTBEAT_SENDER: Final[str] = "system"

# ── IPC extras ──
IPC_DEFAULT_PRIORITY: Final[float] = 5.0
IPC_MSG_ID_LENGTH: Final[int] = 12
IPC_REQUEST_TIMEOUT: Final[float] = 5.0

# ── Process table ──
PROCESS_AUDIT_MAX: Final[int] = 1000
PROCESS_INIT_NAME: Final[str] = "kernel"
PROCESS_INIT_ROLE: Final[str] = "init"
PROCESS_INIT_RING: Final[int] = 3
PROCESS_DEFAULT_RING: Final[int] = 1
PROCESS_AUDIT_LOG_LIMIT: Final[int] = 100

# ── Resource extras ──
RESOURCE_FALLBACK_AGENT: Final[str] = "default"
RESOURCE_KEYS: Final[tuple[str, ...]] = ("workers", "scouts", "memory", "tokens")
RESOURCE_DEFAULT_COST: Final[int] = 1

# ── Mutex extras ──
MUTEX_BOOST_THRESHOLD: Final[float] = 0.5
MUTEX_CYCLE_DETECT_AFTER: Final[float] = 1.0

# ── VFS ──
VFS_DEFAULT_MIN_RING: Final[int] = 1
VFS_PROC_PATH: Final[str] = "/proc"


# ── Syscall ──
SYSCALL_AUDIT_MAX: Final[int] = 5000
SYSCALL_AUDIT_DETAIL_MAXLEN: Final[int] = 200
SYSCALL_AUDIT_QUERY_LIMIT: Final[int] = 100
SYSCALL_AUDIT_CLI_LIMIT: Final[int] = 20
SYSCALL_DEFAULT_FALLBACK: Final[str] = "default"
SYSCALL_DEFAULT_SIGNAL_TYPE: Final[str] = "TASK_ASSIGN"
SYSCALL_DEFAULT_COST: Final[int] = 1
SYSCALL_DEFAULT_RING: Final[int] = 1
SYSCALL_DEFAULT_RESOURCE: Final[str] = "tokens"
SYSCALL_REGISTER_DEFAULT_AGENT: Final[str] = "kernel"

# ── Stagnation detection ──
STAGNATION_SPIN_THRESHOLD: Final[int] = 3
STAGNATION_OSCILLATION_CYCLES: Final[int] = 2
STAGNATION_NO_DRIFT_EPSILON: Final[float] = 0.01
STAGNATION_DIMINISHING_RATE: Final[float] = 0.01
STAGNATION_MAX_ITERATIONS: Final[int] = 30


# ── GateChain ──
LEDGER_MAX_ENTRIES: Final[int] = 200
LEDGER_RECENT_LIMIT: Final[int] = 20
LEDGER_COUNT_WINDOW: Final[float] = 60.0
GATECHAIN_DEFAULT_DANGER: Final[int] = 1
GATECHAIN_DANGER_LEVELS: Final[dict[str, int]] = {
    "deploy": 5, "db_migrate": 4, "user_delete": 5,
    "destroy": 5, "rollback": 4, "migrate": 4,
    "exec": 4, "run_in_terminal": 3, "execute": 3,
    "delete": 3, "write": 2, "replace": 2, "format": 2,
}
GATECHAIN_TOOLS_KEY: Final[str] = "_tools"
GATECHAIN_FREQ_MULTIPLIER: Final[float] = 0.5
GATECHAIN_RISK_WARN_THRESHOLD: Final[float] = 6.0
GATECHAIN_ESCALATION_DANGER: Final[int] = 4
GATECHAIN_SENDER: Final[str] = "gatechain"
GATECHAIN_L3_TARGET: Final[str] = "l3"
GATECHAIN_G5_HISTORY_LIMIT: Final[int] = 10
GATECHAIN_REPEAT_THRESHOLD: Final[int] = 5
GATECHAIN_HIGH_FREQ_THRESHOLD: Final[int] = 3
GATECHAIN_DANGER_WEIGHT: Final[int] = 2
GATECHAIN_HISTORY_WEIGHT: Final[float] = 0.5
GATECHAIN_FREQ_WEIGHT: Final[float] = 1.0
GATECHAIN_G1_INDEX: Final[int] = 0
GATECHAIN_G3_INDEX: Final[int] = 2
GATECHAIN_PATTERN_TEMPLATE: Final[str] = "G1-{g1}_G3-{g3}"

# ── GateChain default query limit ──
GATECHAIN_LEDGER_LIMIT: Final[int] = 100


# ── Tool chain ──
CHAIN_KEY_ENV_VAR: Final[str] = "PRAXIS_CHAIN_KEY"


# ── PraxisRing (tool ring definition) ──

RING_1: Final[str] = "RING_1"
RING_2_5: Final[str] = "RING_2_5"
RING_3: Final[str] = "RING_3"

RING_NUM_MAP: Final[dict[str, int]] = {RING_1: 1, RING_2_5: 2, RING_3: 3}
RING_NAME_MAP: Final[dict[int, str]] = {1: RING_1, 2: RING_2_5, 3: RING_3}

class PraxisRing:
    TOOL_RING_CAPACITY: int = 50


# ── GateStatus (gate check results) ──

class GateStatus:
    PASS: str = "PASS"
    WARN: str = "WARN"
    BLOCK: str = "BLOCK"
    REPORT: str = "REPORT"


# ── RequestPoolConfig (request pool scheduling) ──

@dataclass
class RequestPoolConfig:
    CAPACITY: int = 8
    EVICT_ON_FULL: bool = True
    WEIGHT_REPUTATION: float = 0.40
    WEIGHT_PRIORITY: float = 0.35
    WEIGHT_WAIT: float = 0.25
    MAX_WAIT_S: float = 300.0


# ── WitnessStatus (ring 3 witness result) ──

class WitnessStatus:
    PENDING: str = "PENDING"
    AWAITING: str = "AWAITING"
    STILL_WAITING: str = "STILL_WAITING"
    APPROVED: str = "APPROVED"
    REJECTED: str = "REJECTED"


# ── Cadence tracking ──
CADENCE_MAX_STEPS: Final[int] = 50
CADENCE_MAX_ATTEMPTS: Final[int] = 3


# ── Subprocess defaults ──
RUN_SUBPROCESS_TIMEOUT: Final[int] = 15


# ── Process / subprocess ──
ZOMBIE_REAPER_INTERVAL: Final[float] = 60.0
PROCESS_WAIT_TIMEOUT: Final[int] = 5
