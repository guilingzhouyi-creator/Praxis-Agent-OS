"""Constants: allocator, process table, resource limits."""

from dataclasses import dataclass
from typing import Final

# ── Allocator ──


@dataclass
class AllocatorDefaults:
    """AllocatorDefaults — allocator defaults record (tokens, ring1, ring2, ring3, sandbox_kb)."""

    tokens: int = 4096
    ring1: int = 32
    ring2: int = 200
    ring3: int = 1000
    sandbox_kb: int = 10240


# Shared default resource limits for new processes
ALLOCATOR_DEFAULTS: Final = AllocatorDefaults()
# Resource limit applied when none is configured
ALLOCATOR_FALLBACK_LIMIT: Final[int] = 100
# Usage percent above which pressure is reported
ALLOCATOR_PRESSURE_THRESHOLD: Final[float] = 80.0
# Purpose marking observational (non-greedy) allocations
ALLOCATOR_OBSERVE_PURPOSE: Final[str] = "observe"
# Units granted when no amount is requested
ALLOCATOR_DEFAULT_AMOUNT: Final[int] = 1
# Decimal digits used in usage percentages
ALLOCATOR_PCT_PRECISION: Final[int] = 1
# Usage updates buffered before batch flush
ALLOCATOR_PCB_FLUSH_SIZE: Final[int] = 32
# Ring drained when swapping entries out
ALLOCATOR_SWAP_SOURCE: Final[str] = "ring1"
# Ring receiving swapped-out entries
ALLOCATOR_SWAP_TARGET: Final[str] = "ring2"
# Entries swapped per swap_out call
ALLOCATOR_SWAP_COUNT: Final[int] = 5
# Resource name for disk-backed allocations
ALLOCATOR_DISK_RESOURCE: Final[str] = "disk"
# Units granted by a single allocation
ALLOCATOR_ALLOCATE_AMOUNT: Final[int] = 200
# Default priority for new allocations
ALLOCATOR_DEFAULT_PRIORITY: Final[int] = 5

# Resource key for token budgets
RESOURCE_TOKENS: Final[str] = "tokens"
# Resource key for ring-1 slots
RESOURCE_RING1: Final[str] = "ring1"
# Resource key for ring-2 slots
RESOURCE_RING2: Final[str] = "ring2"
# Resource key for ring-3 slots
RESOURCE_RING3: Final[str] = "ring3"
# Resource key for sandbox disk kilobytes
RESOURCE_SANDBOX_KB: Final[str] = "sandbox_kb"
# Resource key for scheduling priority
RESOURCE_PRIORITY: Final[str] = "priority"


# ── Process table ──
PROCESS_AUDIT_MAX: Final[int] = 1000
PROCESS_INIT_NAME: Final[str] = "kernel"
# Role assigned to the kernel init process
PROCESS_INIT_ROLE: Final[str] = "init"
# Ring granted to the init process
PROCESS_INIT_RING: Final[int] = 3
# Ring granted to ordinary processes
PROCESS_DEFAULT_RING: Final[int] = 1
# Audit log rows kept per process
PROCESS_AUDIT_LOG_LIMIT: Final[int] = 100
# Cap on concurrently registered processes
PROCESS_TABLE_MAX: Final[int] = 500
# Seconds waited for a process to exit
PROCESS_WAIT_TIMEOUT: Final[int] = 5
# Exit code reported when a process is OOM-killed
PROCESS_OOM_EXIT_CODE: Final[int] = -9

# Seconds between zombie-process sweeps
ZOMBIE_REAPER_INTERVAL: Final[float] = 60.0
# Age after which a zombie is reaped
ZOMBIE_MAX_AGE: Final[float] = 300.0
# Seconds between process-table GC passes
PROCESS_GC_INTERVAL: Final[float] = 60.0


# ── Resource ──


@dataclass
class ResourceProfileDefaults:
    """ResourceProfileDefaults — resource profile defaults record (max_tokens, max_workers, max_scouts, max_memory, priority)."""

    max_tokens: int = 4096
    max_workers: int = 4
    max_scouts: int = 3
    max_memory: int = 100
    priority: int = 5


# Shared default resource profile for agents
RESOURCE_PROFILE_DEFAULTS: Final = ResourceProfileDefaults()
# Agent profile used when none is registered
RESOURCE_FALLBACK_AGENT: Final[str] = "default"
# Resource keys recognized in profiles
RESOURCE_KEYS: Final[tuple[str, ...]] = ("workers", "scouts", "memory", "tokens")
# Default token cost of a resource unit
RESOURCE_DEFAULT_COST: Final[int] = 1
