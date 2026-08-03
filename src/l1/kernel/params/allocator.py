"""Constants: allocator, process table, resource limits."""

from dataclasses import dataclass
from typing import Final

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
ALLOCATOR_DEFAULT_AMOUNT: Final[int] = 1
ALLOCATOR_PCT_PRECISION: Final[int] = 1
ALLOCATOR_SWAP_SOURCE: Final[str] = "ring1"
ALLOCATOR_SWAP_TARGET: Final[str] = "ring2"
ALLOCATOR_SWAP_COUNT: Final[int] = 5
ALLOCATOR_DISK_RESOURCE: Final[str] = "disk"
ALLOCATOR_ALLOCATE_AMOUNT: Final[int] = 200
ALLOCATOR_DEFAULT_PRIORITY: Final[int] = 5

RESOURCE_TOKENS: Final[str] = "tokens"
RESOURCE_RING1: Final[str] = "ring1"
RESOURCE_RING2: Final[str] = "ring2"
RESOURCE_RING3: Final[str] = "ring3"
RESOURCE_SANDBOX_KB: Final[str] = "sandbox_kb"
RESOURCE_PRIORITY: Final[str] = "priority"


# ── Process table ──
PROCESS_AUDIT_MAX: Final[int] = 1000
PROCESS_INIT_NAME: Final[str] = "kernel"
PROCESS_INIT_ROLE: Final[str] = "init"
PROCESS_INIT_RING: Final[int] = 3
PROCESS_DEFAULT_RING: Final[int] = 1
PROCESS_AUDIT_LOG_LIMIT: Final[int] = 100
PROCESS_TABLE_MAX: Final[int] = 500
PROCESS_WAIT_TIMEOUT: Final[int] = 5
PROCESS_OOM_EXIT_CODE: Final[int] = -9

ZOMBIE_REAPER_INTERVAL: Final[float] = 60.0
ZOMBIE_MAX_AGE: Final[float] = 300.0


# ── Resource ──

@dataclass
class ResourceProfileDefaults:
    max_tokens: int = 4096
    max_workers: int = 4
    max_scouts: int = 3
    max_memory: int = 100
    priority: int = 5


RESOURCE_PROFILE_DEFAULTS: Final = ResourceProfileDefaults()
RESOURCE_FALLBACK_AGENT: Final[str] = "default"
RESOURCE_KEYS: Final[tuple[str, ...]] = ("workers", "scouts", "memory", "tokens")
RESOURCE_DEFAULT_COST: Final[int] = 1
