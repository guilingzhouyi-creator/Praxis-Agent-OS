"""Constants: kernel primitives — event, interrupt, registry, vfs, swapper, syscall, tool chain, boot.

Split from:
  allocator/process/resource  → params/allocator.py
  mutex/semaphore/barrier/IPC → params/sync.py
  gatechain                   → params/gatechain.py
"""

import os as _os_env
from dataclasses import dataclass
from typing import Any, Final

# ── Backward-compatible re-exports (callers can still import from kernel.py) ──
from .allocator import *  # noqa: F401, F403
from .sync import *       # noqa: F401, F403
from .gatechain import *  # noqa: F401, F403


# ── Event bus ──
EVENT_MAX_HISTORY: Final[int] = 200
EVENT_QUERY_LIMIT: Final[int] = 20
EVENT_BUS_WORKERS: Final[int] = 4
HEARTBEAT_INTERVAL: Final[float] = 15.0

# ── Event extras ──
EVENT_STORE_SENDER: Final[str] = "event_store"
EVENT_HEARTBEAT_SENDER: Final[str] = "system"


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
SWAPPER_RECALL_LIMIT: Final[int] = 999999
SWAPPER_COMPACT_QUERY_LIMIT: Final[int] = 20
SWAPPER_COMPACT_MIN_ENTRIES: Final[int] = 10
SWAPPER_COMPACT_MIN_PER_AGENT: Final[int] = 3
SWAPPER_COMPACT_IMPORTANCE: Final[float] = 0.3
SWAPPER_COMPACT_TAGS: Final[tuple[str, ...]] = ("compacted", "auto")
SWAPPER_SWAP_OUT_IMPORTANCE: Final[float] = 0.3
SWAPPER_COMPACT_IMPORTANCE: Final[float] = 0.5


# ── VFS ──
VFS_DEFAULT_MIN_RING: Final[int] = 1
VFS_PROC_PATH: Final[str] = "/proc"


# ── Syscall ──
SYSCALL_AUDIT_MAX: Final[int] = 5000
SYSCALL_AUDIT_DETAIL_MAXLEN: Final[int] = 200
SYSCALL_AUDIT_QUERY_LIMIT: Final[int] = 100
SYSCALL_AUDIT_CLI_LIMIT: Final[int] = 20
AUDIT_FLUSH_SIZE: Final[int] = 32
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


# ── Tool chain (extra) ──
CHAIN_KEY_ENV_VAR: Final[str] = "PRAXIS_CHAIN_KEY"


# ── PraxisRing (tool ring definition) ──

RING_1: Final[str] = "RING_1"
RING_2_5: Final[str] = "RING_2_5"
RING_3: Final[str] = "RING_3"

RING_NUM_MAP: Final[dict[str, int]] = {RING_1: 1, RING_2_5: 2, RING_3: 3}
RING_NAME_MAP: Final[dict[int, str]] = {1: RING_1, 2: RING_2_5, 3: RING_3}


class PraxisRing:
    TOOL_RING_CAPACITY: int = 50


# ── RequestPoolConfig (request pool scheduling) ──

@dataclass
class RequestPoolConfig:
    CAPACITY: int = 8
    EVICT_ON_FULL: bool = True
    WEIGHT_REPUTATION: float = 0.40
    WEIGHT_PRIORITY: float = 0.35
    WEIGHT_WAIT: float = 0.25
    MAX_WAIT_S: float = 300.0


# ── Boot / Shutdown ──
BOOT_STEP_TIMEOUT: Final[float] = 60.0
SHUTDOWN_TIMEOUT: Final[float] = 30.0


# ── Cadence tracking ──
CADENCE_MAX_STEPS: Final[int] = 50
CADENCE_MAX_ATTEMPTS: Final[int] = 3


# ── Subprocess defaults ──
RUN_SUBPROCESS_TIMEOUT: Final[int] = 15
