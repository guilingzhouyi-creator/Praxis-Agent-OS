"""Kernel constants — single source of truth for all magic numbers/strings.

Every hardcoded value in kernel/ belongs here.
"""

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

HEARTBEAT_INTERVAL: Final[float] = 15.0

# ── Event bus ──
EVENT_MAX_HISTORY: Final[int] = 200
EVENT_QUERY_LIMIT: Final[int] = 20

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
DEVICE_DEGRADED_THRESHOLD: Final[float] = 0.5    # error/call ratio → DEGRADED
DEVICE_DOWN_THRESHOLD: Final[float] = 0.9        # error/call ratio → DOWN
DEVICE_MIN_CALLS_DEGRADED: Final[int] = 5
DEVICE_MIN_CALLS_DOWN: Final[int] = 10

# ── Watchdog ──
WATCHDOG_INTERVAL: Final[float] = 15.0
WATCHDOG_ZOMBIE_LIMIT: Final[int] = 50
WATCHDOG_IDLE_LIMIT: Final[float] = 300.0
WATCHDOG_INTERRUPT_LIMIT: Final[int] = 1000

# ── File cache (Cell-level, shared across agents) ──

FILE_CACHE_MAX_ENTRIES: Final[int] = 500
FILE_CACHE_MAX_SIZE: Final[int] = 10 * 1024 * 1024   # 10MB total
FILE_CACHE_TTL: Final[float] = 60.0                   # seconds


# ── Context register (Cell-level, shared across agent terminals) ──

CONTEXT_REGISTER_MAX_ENTRIES: Final[int] = 200


# ── Scout pool ──

SCOUT_POOL_MIN_IDLE: Final[int] = 2
SCOUT_POOL_MAX_TOTAL: Final[int] = 16
SCOUT_POOL_MAX_PER_AGENT: Final[int] = 4
SCOUT_POOL_IDLE_TIMEOUT: Final[float] = 60.0
SCOUT_CACHE_TTL: Final[float] = 30.0
SCOUT_CACHE_MAX_ENTRIES: Final[int] = 200
SCOUT_SESSION_TIMEOUT: Final[float] = 300.0


# ── ResultStore (tool result cache) ──
RESULT_STORE_MAX_ENTRIES: Final[int] = 500
RESULT_STORE_TTL: Final[float] = 300.0

# ── Sequence monitor (per-Cell anomaly detection) ──
SEQ_MONITOR_NGRAM: Final[int] = 3              # max n-gram context length
SEQ_MONITOR_MIN_SAMPLES: Final[int] = 5         # minimum samples before using a transition
SEQ_MONITOR_ANOMALY_THRESHOLD: Final[float] = 0.05  # geometric mean below this = anomaly
SEQ_MONITOR_PATH: Final[str] = ".praxis_seq_monitor.json"

# ── Reference Channel (async event recorder, non-blocking) ──
RC_PATH: Final[str] = ".praxis_reference_channel.jsonl"
RC_FLUSH_INTERVAL: Final[float] = 5.0        # flush buffered events every 5s
RC_MAX_EVENTS: Final[int] = 100               # or when buffer reaches 100


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


# ── Constitution rules ──

@dataclass
class ConstitutionRuleDef:
    section: str
    severity: str  # MUST | SHOULD | MAY
    description: str


BUILTIN_RULE_DEFS: Final[list[ConstitutionRuleDef]] = [
    ConstitutionRuleDef(section="§2.3", severity="MUST",
                        description="Agent must not write outside its territory"),
    ConstitutionRuleDef(section="§3.1", severity="MUST",
                        description="Agent must not read files outside its territory without L3 approval"),
    ConstitutionRuleDef(section="§3.3", severity="MUST",
                        description="All tool calls must pass GateChain G1-G5"),
    ConstitutionRuleDef(section="§3.4", severity="MUST",
                        description="Cross-unit tool calls require G5 approval"),
    ConstitutionRuleDef(section="§4.5", severity="MUST",
                        description="All modifications must go through sandbox (no direct writes)"),
    ConstitutionRuleDef(section="§4.6", severity="MUST",
                        description="All modifications must be reviewable by L3 before flush"),
    ConstitutionRuleDef(section="§4.7", severity="MUST",
                        description="No Agent may modify the constitution itself"),
    ConstitutionRuleDef(section="§5.1", severity="MUST",
                        description="All tool calls must be logged with audit trail"),
    ConstitutionRuleDef(section="§5.2", severity="SHOULD",
                        description="All decisions must be recorded in memory Ring 2"),
    ConstitutionRuleDef(section="§6.1", severity="MUST",
                        description="Cross-territory changes require peer review"),
    ConstitutionRuleDef(section="§6.2", severity="MUST",
                        description="L3 is the final arbiter of all disputes"),
    ConstitutionRuleDef(section="§7.1", severity="MUST",
                        description="Scouts are read-only and depth=1"),
    ConstitutionRuleDef(section="§7.2", severity="SHOULD",
                        description="Scout findings must be logged before disposal"),
    ConstitutionRuleDef(section="§8.1", severity="MUST",
                        description="Agent context must be built from Ring memory, not raw output"),
    ConstitutionRuleDef(section="§8.2", severity="SHOULD",
                        description="Important decisions must be persisted to Ring 3 (long-term)"),
]

# ── Constitution action sets ──
# These must be overridden per deployment with your project's actual tool names.
# Example from Portal:
#   CONSTITUTION_FILE_ACTIONS = {"read_file", "write_file", ...}
#   CONSTITUTION_MODIFY_ACTIONS = {"write_file", "replace_string", ...}
#   CONSTITUTION_GATE_ACTIONS = {"run_in_terminal", "deploy", ...}
#   CONSTITUTION_SCOUT_BLOCKED = {"write_file", "delete", ...}

CONSTITUTION_FILE_ACTIONS: frozenset[str] = frozenset({
    "read", "read_file", "grep", "grep_search", "list", "list_dir",
    "search", "find", "stat",
})
CONSTITUTION_MODIFY_ACTIONS: frozenset[str] = frozenset({
    "write", "write_file", "edit", "replace", "replace_string",
    "delete", "rename", "create", "create_file", "format",
    "run", "run_in_terminal",
})
CONSTITUTION_GATE_ACTIONS: frozenset[str] = frozenset({
    "run_in_terminal", "deploy", "db_migrate",
    "user_delete", "delete_user", "destroy",
})
CONSTITUTION_SCOUT_BLOCKED: frozenset[str] = frozenset({
    "write", "write_file", "edit", "replace", "replace_string",
    "delete", "rename", "create", "create_file", "format",
})


# ── Agent identity (fully configurable, not a fixed enum) ──

@dataclass
class AgentDefaults:
    max_scouts: int = 3
    max_tokens: int = 4096
    max_workers: int = 4
    priority: int = 5
    ring: int = 1
    model_config: dict | None = None  # per-agent LLM overrides
    system_prompt_key: str = ""       # empty = auto-resolve by role


DEFAULT_AGENT_CONFIGS: Final[dict[str, AgentDefaults]] = {
    "default": AgentDefaults(max_scouts=3, max_tokens=4096, max_workers=4, priority=5, ring=1),
    "scout":   AgentDefaults(max_scouts=0, max_tokens=2048, max_workers=1, priority=5, ring=1),
    "l3":      AgentDefaults(max_scouts=0, max_tokens=2048, max_workers=2, priority=1, ring=3),
    "human":   AgentDefaults(max_scouts=0, max_tokens=0,    max_workers=0, priority=0, ring=0),
}

# ── Canonical role names (single source of truth) ──
CENTRAL_ROLES: Final[list[str]] = ["reader", "writer", "reviewer", "scout", "l3", "default", "deployer"]
CENTRAL_DEFAULT_ROLES: Final[list[str]] = ["reader", "writer", "reviewer"]


# ── Clearance (role → ring access level) ──

AGENT_CLEARANCE: Final[dict[str, int]] = {
    "default": 1,
    "scout":   1,
    "l3":      3,
}


# ── Territory → role mapping ──

TERRITORY_MAP: Final[dict[str, str]] = {}
TERRITORY_PATHS: Final[dict[str, list[str]]] = {}
SHARED_PATHS: Final[list[str]] = []

# ── Agent reputation defaults ──

AGENT_REPUTATION_DEFAULTS: Final[dict[str, float]] = {
    "default":  0.85,
    "security": 0.95,
    "scout":    0.80,
    "reader":   0.70,
}

# ── Tool danger levels ──

TOOL_DANGER_LEVEL: Final[dict[int, str]] = {
    0: "read_only",
    1: "safe_write",
    2: "dangerous",
    3: "destructive",
}

DANGER_TO_GATES: Final[dict[int, list[str]]] = {
    0: ["G1", "G2"],
    1: ["G1", "G2", "G3", "G4"],
    2: ["G1", "G2", "G3", "G4"],
    3: ["G1", "G2", "G3", "G4", "G5"],
}

# ── Tool sets for cadence/security tracking ──
WRITE_TOOL_NAMES: Final[frozenset[str]] = frozenset({
    "write_file", "edit_file", "edit", "replace_string", "create_file",
})
TERMINAL_TOOL_NAMES: Final[frozenset[str]] = frozenset({
    "bash", "shell", "run_in_terminal", "exec", "powershell",
})


# ── Boot sequence ──

BOOT_MEMORY_WARM_TOKENS: Final[int] = 500
BOOT_CONSTITUTION_CHECK: Final[bool] = True
BOOT_AUTO_EMIT_SIGNAL: Final[bool] = True
TERMINAL_POLL_INTERVAL: Final[float] = 0.05
TERMINAL_MAX_WORKERS: Final[int] = 4
CARD_WAIT_TIMEOUT: Final[float] = 30.0
CELL_L3_SENDER: Final[str] = "l3"
ISSUE_AUTO_CONSENSUS: Final[bool] = True


# ── Allocator extras ──
ALLOCATOR_DEFAULT_AMOUNT: Final[int] = 1
ALLOCATOR_PCT_PRECISION: Final[int] = 1
ALLOCATOR_SWAP_SOURCE: Final[str] = "ring1"
ALLOCATOR_SWAP_TARGET: Final[str] = "ring2"
ALLOCATOR_SWAP_COUNT: Final[int] = 5
ALLOCATOR_DISK_RESOURCE: Final[str] = "disk"

# ── Constitution extras ──
CONSTITUTION_SANDBOX_KEYWORD: Final[str] = "sandbox"
CONSTITUTION_KEYWORD: Final[str] = "constitution"
CONSTITUTION_FILE_EXT: Final[str] = ".nomos-rules.md"
CONSTITUTION_ACTION_LEN_THRESHOLD: Final[int] = 5
CONSTITUTION_SCOUT_AGENT_NAME: Final[str] = "scout"
CONSTITUTION_SHARED_KEYWORD: Final[str] = "shared"
CONSTITUTION_CUSTOM_SECTION: Final[str] = "§custom"

# Sandbox root path for constitutional verification (cross-platform default)
import os as _os
import tempfile as _tf
_SANDBOX_DEFAULT = _os.path.join(_tf.gettempdir(), "nomos-sandbox")
SANDBOX_ROOT_PATH: Final[str] = _os.environ.get("NOMOS_SANDBOX_ROOT", _SANDBOX_DEFAULT)

# ── Event extras ──
EVENT_STORE_SENDER: Final[str] = "event_store"
EVENT_HEARTBEAT_SENDER: Final[str] = "system"

# ── EventBridge ──
BRIDGE_KERNEL_CHANNEL: Final[str] = "bridge:kernel"
BRIDGE_IPC_CHANNEL: Final[str] = "bridge:ipc"
BRIDGE_DEFAULT_SENDER: Final[str] = "ipc_bridge"

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

# ── Swapper extras ──
SWAPPER_PAGER_NOTIFY_COUNT: Final[int] = 5
SWAPPER_COMPACT_CONTENT_PREVIEW: Final[int] = 200
SWAPPER_COMPACT_SUMMARY_COUNT: Final[int] = 3
SWAPPER_COMPACT_SUMMARY_MAXLEN: Final[int] = 500

# ── Mutex extras ──
MUTEX_BOOST_THRESHOLD: Final[float] = 0.5
MUTEX_CYCLE_DETECT_AFTER: Final[float] = 1.0

# ── VFS ──
VFS_DEFAULT_MIN_RING: Final[int] = 1
VFS_PROC_PATH: Final[str] = "/proc"

# ── Persistence ──
PERSIST_AUTO: Final[bool] = True
PERSIST_INTERVAL: Final[float] = 30.0
EVENT_STORE_MAX_QUERY: Final[int] = 5000

CARD_REGISTRY_AUTO_SAVE: Final[float] = 30.0
CARD_DISPATCH_INTERVAL: Final[float] = 1.0
CARD_QUEUE_PENDING_MAX: Final[int] = 200
CARD_QUEUE_CELL_MAX: Final[int] = 10
CARD_GATE_AUTO_SAVE: Final[float] = 10.0
PENDING_QUEUE_AUTO_SAVE: Final[float] = 5.0
ISSUE_TABLE_AUTO_SAVE: Final[float] = 10.0
APPROVAL_GATE_AUTO_SAVE: Final[float] = 5.0
SANDBOX_STATE_AUTO_SAVE: Final[float] = 0.0
TODO_TABLE_AUTO_SAVE: Final[float] = 30.0
TRANSACTION_AREA_AUTO_SAVE: Final[float] = 30.0
STATECHARTS_AUTO_SAVE: Final[float] = 30.0
EXECUTION_RESULTS_AUTO_SAVE: Final[float] = 30.0
DIALOGUE_SESSION_AUTO_SAVE: Final[float] = 30.0
APPROVAL_GATE_WAIT_TIMEOUT: Final[float] = 300.0
DIALOGUE_IDLE_TIMEOUT: Final[float] = 300.0

# ── PAL Router (cost-optimized LLM routing) ──
PAL_FRUGAL_COST: Final[int] = 1
PAL_STANDARD_COST: Final[int] = 10
PAL_FRONTIER_COST: Final[int] = 30
PAL_FRUGAL_THRESHOLD: Final[float] = 0.4
PAL_STANDARD_THRESHOLD: Final[float] = 0.7
PAL_ESCALATE_AFTER: Final[int] = 2
PAL_DOWNGRADE_AFTER: Final[int] = 5
PAL_DEFAULT_TIER: Final[str] = "frugal"

# ── Stagnation detection ──
STAGNATION_SPIN_THRESHOLD: Final[int] = 3
STAGNATION_OSCILLATION_CYCLES: Final[int] = 2
STAGNATION_NO_DRIFT_EPSILON: Final[float] = 0.01
STAGNATION_DIMINISHING_RATE: Final[float] = 0.01
STAGNATION_MAX_ITERATIONS: Final[int] = 30

# ── Syscall ──
SYSCALL_AUDIT_MAX: Final[int] = 5000
SYSCALL_AUDIT_DETAIL_MAXLEN: Final[int] = 200
SYSCALL_AUDIT_QUERY_LIMIT: Final[int] = 100
SYSCALL_AUDIT_CLI_LIMIT: Final[int] = 20
SYSCALL_DEFAULT_FALLBACK: Final[str] = "default"

# ── Tool timeouts (consolidated) ──
TOOL_BUILD_TIMEOUT: Final[int] = 300
TOOL_DOCKER_TIMEOUT: Final[int] = 300
TOOL_PIP_TIMEOUT: Final[int] = 120
TOOL_GIT_TIMEOUT: Final[int] = 30
TOOL_PING_TIMEOUT: Final[int] = 30
TOOL_HTTP_TIMEOUT_SHORT: Final[int] = 15
TOOL_HTTP_TIMEOUT_MEDIUM: Final[int] = 30
TOOL_HTTP_TIMEOUT_LONG: Final[int] = 60
TOOL_PIP_INSTALL_TIMEOUT: Final[int] = 120
TOOL_NPM_TIMEOUT: Final[int] = 120
TOOL_PYRIGHT_TIMEOUT: Final[int] = 60
TOOL_COMPILE_CHECK_TIMEOUT: Final[int] = 10
TOOL_SCOUT_RUN_TIMEOUT: Final[int] = 180
TOOL_SCOUT_MAX_STEPS: Final[int] = 10

# ── Device rate limit defaults ──
DEVICE_RATE_LIMIT_LLM: Final[int] = 10
DEVICE_RATE_LIMIT_STORAGE: Final[int] = 100

# ── Memory query limits ──
MEMORY_RECALL_LIMIT: Final[int] = 50
MEMORY_RECALL_LIMIT_LARGE: Final[int] = 200
MEMORY_BUILD_CONTEXT_ENTRIES: Final[int] = 10
MEMORY_ALERT_EXPORT_LIMIT: Final[int] = 500
MEMORY_LOG_QUERY_LIMIT: Final[int] = 10000
MEMORY_PAGER_RECALL_LIMIT: Final[int] = 50
SYSCALL_DEFAULT_SIGNAL_TYPE: Final[str] = "TASK_ASSIGN"
SYSCALL_DEFAULT_COST: Final[int] = 1
SYSCALL_DEFAULT_RING: Final[int] = 1
SYSCALL_DEFAULT_RESOURCE: Final[str] = "tokens"
SYSCALL_REGISTER_DEFAULT_AGENT: Final[str] = "kernel"

# ── Tool timeouts (seconds) ──
TOOL_TERMINAL_TIMEOUT: Final[float] = 30.0
TOOL_GREP_TIMEOUT: Final[float] = 15.0
TOOL_HANDLER_TIMEOUT: Final[float] = 60.0  # max seconds per tool handler execution in tool_use

# ── Tool rate limiting (calls/minute per ring) ──
TOOL_RATE_RING_1: Final[int] = 60
TOOL_RATE_RING_2_5: Final[int] = 20
TOOL_RATE_RING_3: Final[int] = 5

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


def role_for_domain(domain: str, fallback: str = "default") -> str:
    """Map a domain path to its agent role."""
    for prefix, role in TERRITORY_MAP.items():
        if domain.startswith(prefix):
            return role
    return fallback


# ── Fault tolerance ──
HEARTBEAT_TIMEOUT: Final[float] = 15.0
CRASH_TIMEOUT: Final[float] = 30.0

# ── Network / CI / Cache defaults (consolidated) ──
NET_PEER_TIMEOUT: Final[float] = 60.0
CI_DEFAULT_TIMEOUT: Final[float] = 300.0
CACHE_DEFAULT_TTL: Final[float] = 60.0
CONTEXT_MAX_REGISTER_TOKENS: Final[int] = 4096
MEMORY_MIN_CONTENT_LEN: Final[int] = 30

# ── Identity ──
PROOF_TTL: Final[float] = 30.0

# ── Scheduler time slice ──
DEFAULT_QUANTUM: Final[float] = 15.0
MAX_PREEMPT: Final[float] = 60.0

# ── Memory ring capacities ──
RING1_CAPACITY: Final[int] = 32
RING2_CAPACITY: Final[int] = 200
RING3_CAPACITY: Final[int] = 1000
MEMORY_RING2_RESTORE_LIMIT: Final[int] = 0  # 0 = unlimited
MEMORY_RING3_RESTORE_LIMIT: Final[int] = 0  # 0 = unlimited

# ── Request pool ──
REQUEST_POOL_CAPACITY: Final[int] = 8

# ── Working set ──
MAX_WORKING_SET_SIZE: Final[int] = 8

# ── Shell/terminal output limits ──
OUTPUT_MAX_LINES: Final[int] = 50
OUTPUT_MAX_CHARS: Final[int] = 4000

# ── Log service ──
LOG_MAX_MEMORY_ENTRIES: Final[int] = 5000
LOG_MAX_FILE_SIZE: Final[int] = 1024 * 1024  # 1MB
LOG_MAX_FILES: Final[int] = 5
LOG_EXPORT_LIMIT: Final[int] = 10000

# ── Error Bus service ──
ERROR_BUS_BUFFER: Final[int] = 5000           # 内存环形缓冲区最大条目
ERROR_BUS_DEDUP_WINDOW: Final[int] = 300      # 去重窗口秒数（5分钟内同类错误合并）
ERROR_BUS_EXPORT_LIMIT: Final[int] = 10000    # 单次导出最大条目

# ── Network service ──
NETWORK_DEFAULT_TIMEOUT: Final[int] = 30
NETWORK_FETCH_MAX_CHARS: Final[int] = 5000

# ── Context register ──
MAX_REGISTER_TOKENS: Final[int] = 4096

# ── Shell buffer ──
BUFFER_MAX: Final[int] = 2000

# ── Token budget ──
DEFAULT_TOKEN_BUDGET: Final[int] = 73000

# ── Allocator resource keys (magic strings) ──
RESOURCE_TOKENS: Final[str] = "tokens"
RESOURCE_RING1: Final[str] = "ring1"
RESOURCE_RING2: Final[str] = "ring2"
RESOURCE_RING3: Final[str] = "ring3"
RESOURCE_SANDBOX_KB: Final[str] = "sandbox_kb"
RESOURCE_PRIORITY: Final[str] = "priority"

# ── Allocator amount ──
ALLOCATE_AMOUNT: Final[int] = 200
ALLOCATOR_DEFAULT_PRIORITY: Final[int] = 5

# ── Persistence ──
PERSIST_QUERY_LIMIT: Final[int] = 100
PERSIST_EXPORT_LIMIT: Final[int] = 500
PERSIST_EXPORT_INTERRUPT_LIMIT: Final[int] = 50

# ── Nonce cleanup ──
NONCE_CLEANUP_AGE: Final[float] = 60.0

# ── Poll/sleep intervals ──
POLL_INTERVAL_DEFAULT: Final[float] = 0.1
POLL_INTERVAL_FAST: Final[float] = 0.01
POLL_INTERVAL_SLOW: Final[float] = 0.05
POLL_INTERVAL_PAUSED: Final[float] = 0.5
MOCK_DELAY: Final[float] = 0.05
POLL_INTERVAL_HANDLER: Final[float] = 0.3      # _term_handlers backoff
FAULT_CHECK_INTERVAL: Final[float] = 5.0       # fault_tolerance check
FAULT_RETRY_INTERVAL: Final[float] = 1.0       # fault_tolerance retry
EXEC_BACKOFF_INTERVAL: Final[float] = 1.0      # execution_engine backoff
SCOUT_MONITOR_INTERVAL: Final[float] = 5.0     # scout monitor loop

# ── Scheduler ──
SCHEDULER_BACKGROUND_PRIORITY: Final[int] = 10

# ── Network fetch ──
NETWORK_FETCH_TIMEOUT: Final[int] = 5

# ── Notify / webhook ──
NOTIFY_WEBHOOK_TIMEOUT: Final[int] = 15

# ── Pager / memory recall ──
PAGER_RECALL_LIMIT: Final[int] = 50

# ── TUI ──
TUI_REFRESH_MS: Final[int] = 300
TUI_MAX_EVENTS: Final[int] = 200
TUI_CARD_LIST_LIMIT: Final[int] = 5
TUI_CARD_LIST_LIMIT_WIDE: Final[int] = 8

# ── Tool defaults ──
TOOL_MEMORY_RECALL_LIMIT: Final[int] = 200
TOOL_MEMORY_RECALL_LARGE: Final[int] = 500
TOOL_FILE_LOCK_TTL: Final[float] = 300.0   # seconds (5 min)
TOOL_AGENT_COORD_TIMEOUT: Final[float] = 60.0
TOOL_L3_LIST_LIMIT: Final[int] = 50

# ── Service-level timeouts ──
CI_SHELL_TIMEOUT: Final[int] = 30
GIT_TIMEOUT: Final[int] = 30
LLM_HTTP_TIMEOUT: Final[int] = 60
LLM_LIGHTWEIGHT_TIMEOUT: Final[int] = 30
SHELL_CMD_TIMEOUT: Final[int] = 30
MEMORY_INIT_TIMEOUT: Final[int] = 30

# ── LLM retry backoff parameters ──
LLM_RATE_LIMIT_WAIT: Final[int] = 60                  # Default wait seconds for 429
LLM_TRANSIENT_BACKOFF_BASE: Final[int] = 3            # multiplier * (retry+1)
LLM_EMPTY_RESPONSE_WAITS: Final[list[int]] = [1, 1, 2, 2, 3]  # per-retry wait
LLM_MAX_RATE_LIMIT_RETRIES: Final[int] = 3
LLM_MAX_OVERFLOW_RETRIES: Final[int] = 2
LLM_MAX_TRANSIENT_RETRIES: Final[int] = 2
LLM_MAX_EMPTY_RETRIES: Final[int] = 3

# ─── LLM provider default URLs ──
LLM_PROVIDER_URLS: Final[dict[str, str]] = {
    "openai":    "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "ollama":    "http://localhost:11434",
}
ANTHROPIC_DEFAULT_URL: Final[str] = LLM_PROVIDER_URLS["anthropic"]
ANTHROPIC_API_VERSION: Final[str] = "2023-06-01"

# ── Default cell ID ──
DEFAULT_CELL_ID: Final[str] = "cell-1"

# ── LLM reasoning / thinking budget ──
REASONING_EFFORT_NONE: Final[str] = "none"
REASONING_EFFORT_LOW: Final[str] = "low"
REASONING_EFFORT_MEDIUM: Final[str] = "medium"
REASONING_EFFORT_HIGH: Final[str] = "high"
DEFAULT_REASONING_EFFORT: Final[str] = REASONING_EFFORT_NONE
DEFAULT_THINKING_BUDGET: Final[int] = 0       # 0 = disabled; 16000 = Anthropic extended thinking

# ── Config directory ──
PRAXIS_CONFIG_DIR: Final[str] = ".config/nomos-praxis"

# ── Version ──
KERNEL_VERSION: Final[str] = "0.3.0"
PRAXIS_CODENAME: Final[str] = "Aether"

# ── Constitution ──
CONSTITUTION_DEFAULT_PATH: Final[str] = ".nomos-rules.md"
CONSTITUTION_ENV_VAR: Final[str] = "NOMOS_CONSTITUTION"

# ── Tool chain ──
CHAIN_KEY_ENV_VAR: Final[str] = "PRAXIS_CHAIN_KEY"

# ── Context pager ──
CHUNK_SIZE_TOKENS: Final[int] = 512

# ── HTN Planner ──
HTN_DOMAIN_PREFIX: Final[str] = "app"
HTN_DEFAULT_TOOLS: Final[dict[str, str]] = {
    "analyze": "read_file", "write": "write_file", "create": "create_file",
    "build": "build_project", "test": "test_project", "lint": "lint",
    "scout": "scout_delegate", "fix": "write_file", "extract": "write_file",
    "review": "read_file", "doc": "write_file", "plan": "write_file",
}

# ── Scout ──
MAX_SCOUTS_PER_AGENT: Final[int] = 3
SCOUT_TIMEOUT: Final[float] = 300.0
SCOUT_POOL_MAX: Final[int] = 12

# ── User session ──
SESSION_TIMEOUT: Final[float] = 3600.0

# ── L3A (Card Execution Agent) defaults ──
L3A_MAX_STEPS: Final[int] = 5
L3A_TIMEOUT: Final[float] = 120.0

# ── Kernel network ──
BROADCAST_INTERVAL: Final[float] = 15.0
PEER_TIMEOUT: Final[float] = 60.0
DISCOVERY_PORT_DEFAULT: Final[int] = 42069
PRAXIS_PORT_DEFAULT: Final[int] = 42070
ENV_DISCOVERY_PORT: Final[str] = "PRAXIS_DISCOVERY_PORT"
ENV_PRAXIS_PORT: Final[str] = "PRAXIS_PORT"
ENV_API_TOKEN: Final[str] = "PRAXIS_API_TOKEN"


# ── PraxisRing (tool ring definition) ──

# Canonical ring string constants — single source of truth
RING_1: str = "RING_1"
RING_2_5: str = "RING_2_5"
RING_3: str = "RING_3"

# Ring name → numeric level
RING_NUM_MAP: dict[str, int] = {RING_1: 1, RING_2_5: 2, RING_3: 3}

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

# ── Subprocess defaults ──
RUN_SUBPROCESS_TIMEOUT: Final[int] = 15

# ── Service timeouts (scattered in code, centralized here) ──
LSP_MANAGER_TIMEOUT: Final[float] = 5.0
LSP_MANAGER_LONG_TIMEOUT: Final[float] = 30.0
MCP_BRIDGE_TIMEOUT: Final[float] = 10.0
MCP_BRIDGE_LONG_TIMEOUT: Final[float] = 30.0
SHELL_SESSION_TIMEOUT: Final[float] = 3.0
POOL_QUEUE_TIMEOUT: Final[float] = 1.0
TERM_HANDLER_TIMEOUT: Final[float] = 15.0
TERM_HANDLER_LONG_TIMEOUT: Final[float] = 30.0
API_GATEWAY_QUEUE_TIMEOUT: Final[float] = 30.0
R4_AGENT_JOIN_TIMEOUT: Final[float] = 5.0
SUBAGENT_RUN_TIMEOUT: Final[float] = 120.0
SUBAGENT_JOIN_TIMEOUT: Final[float] = 30.0
SEARCH_MAX_WORKERS: Final[int] = 8

# ── API / network defaults ──
API_GATEWAY_PORT: Final[int] = 8080
API_GATEWAY_HOST: Final[str] = "127.0.0.1"
API_MAX_BODY_BYTES: Final[int] = 1_048_576  # 1 MiB request body cap
MCP_DEFAULT_URL: Final[str] = "http://localhost:3500/mcp/v1"
MCP_TIMEOUT: Final[int] = 5

# ── CORS ──
API_CORS_ORIGIN: Final[str] = "*"
API_CORS_ALLOW_METHODS: Final[str] = "GET, POST, DELETE, OPTIONS"
API_CORS_ALLOW_HEADERS: Final[str] = "Content-Type"

# ── HTTP User-Agent ──
HTTP_USER_AGENT: Final[str] = "NOMOS-Praxis/1.0"
HTTP_TOOL_USER_AGENT: Final[str] = "NOMOS-Agent/1.0"
DUCKDUCKGO_SEARCH_URL: Final[str] = "https://api.duckduckgo.com/"

# ── Process / subprocess ──
ZOMBIE_REAPER_INTERVAL: Final[float] = 60.0
PROCESS_WAIT_TIMEOUT: Final[int] = 5

# ── CI pipeline ──
CI_PIPELINE_CACHE_TTL: Final[float] = 300.0

# ── Direct session ──
DIRECT_SESSION_TIMEOUT: Final[float] = 3600.0

# ── Cell ring buffer sizes ──
CELL_ROLLBACK_RING_SIZE: Final[int] = 20   # max rollback context entries
CELL_HISTORY_RING_SIZE: Final[int] = 100   # max card history entries
CELL_SNAPSHOT_MAX: Final[int] = 50         # max pre-execution file snapshots
CELL_MAILBOX_MAX_PER_AGENT: Final[int] = 100   # max queued messages per agent
CELL_MAILBOX_TTL: Final[float] = 3600.0        # message TTL before auto-discard

# ── Agent / Loop defaults ──
AGENT_LOOP_DEFAULT_STEPS: Final[int] = 10
AGENT_LOOP_DEFAULT_TIMEOUT: Final[float] = 120.0
SUBAGENT_LOOP_STEPS: Final[int] = 5
SUBAGENT_LOOP_TIMEOUT: Final[float] = 30.0

# ── Feedback loop / Verifier ──
MAX_SELF_HEAL: Final[int] = 3            # Max self-correction attempts per step
REVIEW_MAX_ROUNDS: Final[int] = 2        # Max peer review rounds before escalation

# ── Scout defaults ──
SCOUT_LOOP_STEPS: Final[int] = 10
SCOUT_LOOP_TIMEOUT: Final[float] = 180.0


# ── Environment variable names (single source of truth) ──
ENV_SANDBOX_ROOT: Final[str] = "NOMOS_SANDBOX_ROOT"
ENV_DEFAULT_CELL: Final[str] = "NOMOS_DEFAULT_CELL"

ARCHIVE_CHECK_INTERVAL: Final[float] = 86400.0
CRON_CHECK_INTERVAL: Final[float] = 60.0      # Cron scheduler tick interval (seconds)
ENV_OPENAI_KEY: Final[str] = "OPENAI_API_KEY"
ENV_DEEPSEEK_KEY: Final[str] = "DEEPSEEK_API_KEY"
ENV_ANTHROPIC_KEY: Final[str] = "ANTHROPIC_API_KEY"
ENV_OLLAMA_URL: Final[str] = "OLLAMA_URL"
ENV_OLLAMA_MODEL: Final[str] = "OLLAMA_MODEL"
ENV_OPENAI_URL: Final[str] = "OPENAI_API_URL"
ENV_OPENAI_MODEL: Final[str] = "OPENAI_MODEL"
ENV_ANTHROPIC_URL: Final[str] = "ANTHROPIC_API_URL"
ENV_ANTHROPIC_MODEL: Final[str] = "ANTHROPIC_MODEL"
ENV_LLM_WS_URL: Final[str] = "LLM_WS_URL"
ENV_LLM_WS_MODEL: Final[str] = "LLM_WS_MODEL"

# ── Archive thresholds (Four-Tier Memory Architecture) ──
ARCHIVE_IMPORTANCE_THRESHOLD: Final[float] = 0.7  # Ring 3 entries with importance >= this get archived on shutdown
ARCHIVE_RESTORE_LIMIT: Final[int] = 100            # Max entries restored from Archive → Ring 3 on boot

# ── R4Agent identity defaults (placeholders — overridable via YAML config) ──
R4_AGENT_ID: Final[str] = "r4-agent"
R4_ROLE: Final[str] = "archivist"
R4_TERRITORY: Final[list[str]] = ["archive", "memory"]

# ── CardBuilder default modes (config-driven — overridable via YAML) ──
CARD_BUILDER_MODES: Final[dict[str, str]] = {
    "build_audit": "PARALLEL_ALL",
    "build_document": "PARALLEL_ALL",
    "build_redesign": "PARALLEL_ALL",
    "build_refactor": "PARALLEL_ALL",
    "build_subtask": "PARALLEL_ALL",
    "build_repair": "EXECUTE",
}

# ── CacheDocument (convention meeting document buffer) ──
CACHE_DOC_MAX_ENTRIES: Final[int] = 200
CACHE_DOC_TTL: Final[float] = 86400.0              # 24h (survives until Agent OS restart)

# ── Injection detection patterns (config-driven — overridable via settings_center) ──
INJECTION_PATTERN_ZH1: Final[str] = r"你(现在|必须|要).*忽略(之前|系统)(指令|设定)"
INJECTION_PATTERN_ZH2: Final[str] = r"你是.*(忽略|无视).*(指令|规则)"

# ── Subprocess / LSP / HTTP timeouts (config-driven) ──
SUBPROCESS_SHORT_TIMEOUT: Final[int] = 5
LSP_DIAG_TIMEOUT: Final[int] = 30
HTTP_CALLBACK_TIMEOUT: Final[int] = 10

# ── Convention session limits (config-driven) ──
CONVENTION_SESSION_MAX_STEPS: Final[int] = 3
CONVENTION_SESSION_TIMEOUT: Final[float] = 300.0
CONVENTION_SUB_MAX_STEPS: Final[int] = 1
CONVENTION_SUB_TIMEOUT: Final[float] = 60.0

# ── GateChain default query limit ──
GATECHAIN_LEDGER_LIMIT: Final[int] = 100

# ── Generalized placeholders (config-driven, override via settings_center) ──

# Model name/URL fallbacks (bootstrap.py, llm.py)
FALLBACK_MODEL: Final[str] = "<model>"
FALLBACK_LLM_API_URL: Final[str] = "<api-url>"
LLM_RATE_LIMIT_DEFAULT: Final[int] = 10
FILESYSTEM_RATE_LIMIT_DEFAULT: Final[int] = 100

# Agent terminal / loop defaults
AGENT_TERMINAL_MAX_SCOUTS: Final[int] = 3
AGENT_TERMINAL_STDIN_MAX: Final[int] = 200
AGENT_TERMINAL_STDOUT_MAX: Final[int] = 500
AGENT_TERMINAL_STDERR_MAX: Final[int] = 200
AGENT_LOOP_MAX_WORKERS: Final[int] = 4
AGENT_LOOP_FUTURE_TIMEOUT: Final[float] = 30.0
AGENT_TERMINAL_WORKER_JOIN_TIMEOUT: Final[float] = 2.0

# Boot VFS mount paths
BOOT_VFS_TEMP_PATH: Final[str] = "/tmp"

# API gateway default port
API_GATEWAY_DEFAULT_PORT: Final[int] = 8080

# ── Token monitoring (CentralCollector quotas) ──
TOKEN_CELL_QUOTA: Final[int] = 5_000_000    # Max tokens per Cell before warning
TOKEN_GLOBAL_QUOTA: Final[int] = 50_000_000  # Max tokens total across all Cells

# ── Data root directory (XDG-style, overridable via env var) ──
import os as _os
import tempfile as _tf
_DEFAULT_DATA_ROOT: Final[str] = _os.path.join(_tf.gettempdir(), "nomos-praxis-data")
PRAXIS_DATA_DIR: Final[str] = _os.environ.get("PRAXIS_DATA_DIR", _DEFAULT_DATA_ROOT)

# ── Data file paths (unified under PRAXIS_DATA_DIR) ──
# All .praxis_* state files should go here, not in CWD.
PRAXIS_EVENTS_DB: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "events.db")
PRAXIS_STATE_JSON: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "state.json")
PRAXIS_CARD_REGISTRY: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "card_registry.json")
PRAXIS_CARD_GATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "card_gate.json")
PRAXIS_PENDING_QUEUE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "pending_queue.json")
PRAXIS_MUTE_STATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "mute_state.json")
PRAXIS_MODE_STATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "mode.json")
PRAXIS_TODO_STATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "todo_state.json")
PRAXIS_CHAIN_KEY: Final[str] = _os.path.join(PRAXIS_DATA_DIR, ".chain_key")
PRAXIS_ISSUE_TABLE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "issue_table.json")
PRAXIS_APPROVAL_GATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "approval_gate.json")
PRAXIS_SANDBOX_STATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "sandbox_state.json")
PRAXIS_TODO_TABLE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "todo_table.json")
PRAXIS_TRANSACTION_AREA: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "transaction_area.json")
PRAXIS_STATECHARTS: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "statecharts.json")
PRAXIS_EXECUTION_RESULTS: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "execution_results.json")
PRAXIS_DIALOGUE_SESSION: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "dialogue_session.json")

# ── Backward-compatible aliases for old .praxis_* names ──
PERSIST_PATH = PRAXIS_STATE_JSON
PERSIST_DB_PATH = PRAXIS_EVENTS_DB
CARD_REGISTRY_PATH = PRAXIS_CARD_REGISTRY
CARD_GATE_PATH = PRAXIS_CARD_GATE
PENDING_QUEUE_PATH = PRAXIS_PENDING_QUEUE
ISSUE_TABLE_PATH = PRAXIS_ISSUE_TABLE
APPROVAL_GATE_PATH = PRAXIS_APPROVAL_GATE
SANDBOX_STATE_PATH = PRAXIS_SANDBOX_STATE
TODO_TABLE_PATH = PRAXIS_TODO_TABLE
TRANSACTION_AREA_PATH = PRAXIS_TRANSACTION_AREA
STATECHARTS_PATH = PRAXIS_STATECHARTS
EXECUTION_RESULTS_PATH = PRAXIS_EXECUTION_RESULTS
DIALOGUE_SESSION_PATH = PRAXIS_DIALOGUE_SESSION

# ── R4Agent skill evolution ──
SKILL_EVOLVED_DIR: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "skills", "evolved")

# ── Convention protocol ──
CONVENTION_MAX_ROUNDS: Final[int] = 2              # Sequential cross-examination rounds
CONVENTION_MAX_AGENTS: Final[int] = 16             # Max agents per convention
CONVENTION_TIMEOUT: Final[float] = 600.0           # Per-round timeout 10min
CONVENTION_ARCHIVE_IMPORTANCE: Final[float] = 0.85  # Discussion result archive importance

# ── Priority gradient (config-driven — overridable via settings_center / YAML) ──
# 1-10 scale, calibrated so that LLM-parsed priority maps to a descriptive label
PRIORITY_GRADIENT: Final[dict[str, int]] = {
    "critical":   10,
    "high":       8,
    "normal":     5,
    "low":        3,
    "trivial":    1,
}

def resolve_priority(value: Any, default: int = 5) -> int:
    """Resolve a priority value against the gradient table.

    Accepts:
      - int (1-10): passed through, clamped to [1, 10]
      - str: looked up in PRIORITY_GRADIENT (case-insensitive)
      - None / other: returns default

    This is the single entry point for all priority resolution,
    making the gradient system config-driven and testable.
    """
    if isinstance(value, int):
        return max(1, min(10, value))
    if isinstance(value, str):
        return PRIORITY_GRADIENT.get(value.lower(), default)
    return default
