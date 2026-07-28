"""Constants: system services — persistence, data paths, sandbox, cache, polling."""

import os as _os
import tempfile as _tf
from typing import Final

# ── File cache (Cell-level, shared across agents) ──

FILE_CACHE_MAX_ENTRIES: Final[int] = 500
FILE_CACHE_MAX_SIZE: Final[int] = 10 * 1024 * 1024
FILE_CACHE_TTL: Final[float] = 60.0


# ── Context register (Cell-level, shared across agent terminals) ──

CONTEXT_REGISTER_MAX_ENTRIES: Final[int] = 200


# ── Scout pool ──

SCOUT_POOL_MIN_IDLE: Final[int] = 2
SCOUT_POOL_MAX_TOTAL: Final[int] = 16
SCOUT_POOL_MAX: Final[int] = 16                 # alias for SCOUT_POOL_MAX_TOTAL
SCOUT_POOL_MAX_PER_AGENT: Final[int] = 4
MAX_SCOUTS_PER_AGENT: Final[int] = 4            # alias for SCOUT_POOL_MAX_PER_AGENT
SCOUT_POOL_IDLE_TIMEOUT: Final[float] = 60.0
SCOUT_CACHE_TTL: Final[float] = 30.0
SCOUT_CACHE_MAX_ENTRIES: Final[int] = 200
SCOUT_TIMEOUT: Final[float] = 300.0
TOOL_SCOUT_RUN_TIMEOUT: Final[int] = 180
TOOL_SCOUT_MAX_STEPS: Final[int] = 10


# ── ResultStore (tool result cache) ──
RESULT_STORE_MAX_ENTRIES: Final[int] = 500
RESULT_STORE_TTL: Final[float] = 300.0

# ── Sequence monitor (per-Cell anomaly detection) ──
SEQ_MONITOR_NGRAM: Final[int] = 3
SEQ_MONITOR_MIN_SAMPLES: Final[int] = 5
SEQ_MONITOR_ANOMALY_THRESHOLD: Final[float] = 0.05
SEQ_MONITOR_PATH: Final[str] = _os.environ.get("NOMOS_SEQ_MONITOR_PATH", ".praxis_seq_monitor.json")

# ── Reference Channel (ring buffer + periodic flush) ──
RC_PATH: Final[str] = _os.environ.get("NOMOS_RC_PATH", ".praxis/.praxis_reference_channel.jsonl")
RC_FLUSH_INTERVAL: Final[float] = 5.0
RC_RING_SIZE: Final[int] = 1000
RC_SHA256_TRUNC: Final[int] = 16
RC_EXPORT_LIMIT: Final[int] = 999999


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


# ── Fault tolerance ──
HEARTBEAT_TIMEOUT: Final[float] = 15.0
CRASH_TIMEOUT: Final[float] = 30.0


# ── Network / CI / Cache defaults (consolidated) ──
NET_PEER_TIMEOUT: Final[float] = 60.0
CI_DEFAULT_TIMEOUT: Final[float] = 300.0
CACHE_DEFAULT_TTL: Final[float] = 60.0

# ── CellCache (L2) — per-Cell shared cache sizes ──
CELL_CACHE_HOT_SIZE: Final[int] = 50        # Hot Ring: latest summaries
CELL_CACHE_INDEX_SIZE: Final[int] = 200     # Index Chain: key → summary
CELL_CACHE_KV_SIZE: Final[int] = 100        # KV Cache: full values
CELL_CACHE_HOT_TTL: Final[float] = 300.0    # 5 min
CELL_CACHE_INDEX_TTL: Final[float] = 900.0  # 15 min
CELL_CACHE_KV_TTL: Final[float] = 1800.0    # 30 min
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
MEMORY_RING2_RESTORE_LIMIT: Final[int] = 0
MEMORY_RING3_RESTORE_LIMIT: Final[int] = 0


# ── Request pool ──
REQUEST_POOL_CAPACITY: Final[int] = 8

# ── Working set ──
MAX_WORKING_SET_SIZE: Final[int] = 8

# ── Shell/terminal output limits ──
TERMINAL_OUTPUT_MAX_LINES: Final[int] = 50
TERMINAL_OUTPUT_MAX_CHARS: Final[int] = 4000

# ── Log service ──
LOG_MAX_MEMORY_ENTRIES: Final[int] = 5000
LOG_MAX_FILE_SIZE: Final[int] = 1024 * 1024
LOG_MAX_FILES: Final[int] = 5
LOG_EXPORT_LIMIT: Final[int] = 10000

# ── Error Bus service ──
ERROR_BUS_BUFFER: Final[int] = 5000
ERROR_BUS_DEDUP_WINDOW: Final[int] = 300
ERROR_BUS_EXPORT_LIMIT: Final[int] = 10000

# ── Observability Bus defaults ──
OBS_AUDIT_LIMIT: Final[int] = 20


# ── Shell buffer ──
BUFFER_MAX: Final[int] = 2000
SHELL_AUTOCOMPLETE_LIMIT: Final[int] = 15
SHELL_AUTOCOMPLETE_AGENT_LIMIT: Final[int] = 10
SHELL_HISTORY_MAX_LIMIT: Final[int] = 200

# ── Token budget ──
DEFAULT_TOKEN_BUDGET: Final[int] = 73000


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
POLL_INTERVAL_HANDLER: Final[float] = 0.3
FAULT_CHECK_INTERVAL: Final[float] = 5.0
FAULT_RETRY_INTERVAL: Final[float] = 1.0
EXEC_BACKOFF_INTERVAL: Final[float] = 1.0
SCOUT_MONITOR_INTERVAL: Final[float] = 5.0

# ── Log/display truncation limits ──
LOG_TRUNC_40: Final[int] = 40
LOG_TRUNC_50: Final[int] = 50
LOG_TRUNC_60: Final[int] = 60
LOG_TRUNC_80: Final[int] = 80
LOG_TRUNC_100: Final[int] = 100
LOG_TRUNC_120: Final[int] = 120
LOG_TRUNC_200: Final[int] = 200
LOG_TRUNC_300: Final[int] = 300
LOG_TRUNC_500: Final[int] = 500
LOG_TRUNC_1000: Final[int] = 1000
LOG_TRUNC_2000: Final[int] = 2000
LOG_TRUNC_3000: Final[int] = 3000
LOG_TRUNC_4000: Final[int] = 4000
LOG_TRUNC_5000: Final[int] = 5000
LOG_TRUNC_10000: Final[int] = 10000

# ── Hash display truncation limits ──
HASH_TRUNC_SHORT: Final[int] = 8
HASH_TRUNC_MEDIUM: Final[int] = 12
HASH_TRUNC_LONG: Final[int] = 16

# ── Scheduler ──
SCHEDULER_BACKGROUND_PRIORITY: Final[int] = 10


# ── Pager / memory recall ──
PAGER_RECALL_LIMIT: Final[int] = 50

# ── TUI ──
TUI_REFRESH_MS: Final[int] = 300
TUI_MAX_EVENTS: Final[int] = 200
TUI_CARD_LIST_LIMIT: Final[int] = 5
TUI_CARD_LIST_LIMIT_WIDE: Final[int] = 8


# ── Context pager ──
CHUNK_SIZE_TOKENS: Final[int] = 512


# ── User session ──
SESSION_TIMEOUT: Final[float] = 3600.0


# ── Version ──
KERNEL_VERSION: Final[str] = "0.3.0"
PRAXIS_CODENAME: Final[str] = "Aether"


# ── Memory ring constants ──
MEMORY_RING_WORKING_BUDGET: Final[int] = 8192
MEMORY_RING_SHORT_BUDGET: Final[int] = 32768
MEMORY_RING_LONG_BUDGET: Final[int] = 131072
MEMORY_RING_WORKING_TTL: Final[float] = 1800.0
MEMORY_RING_SHORT_TTL: Final[float] = 86400.0
MEMORY_RING_LONG_TTL: Final[float] = 0.0

# ── Memory importance / pressure thresholds ──
MEMORY_IMPORTANCE_BASE: Final[float] = 0.5
MEMORY_IMPORTANCE_DECISION: Final[float] = 0.3
MEMORY_IMPORTANCE_PATTERN: Final[float] = 0.3
MEMORY_IMPORTANCE_SUMMARY: Final[float] = 0.2
MEMORY_IMPORTANCE_OBSERVATION: Final[float] = 0.1
MEMORY_PRESSURE_HIGH: Final[float] = 0.80
MEMORY_PRESSURE_MEDIUM: Final[float] = 0.60
MEMORY_PROMOTION_THRESHOLD: Final[float] = 0.6
MEMORY_IMPORTANCE_HIGH: Final[float] = 0.7
MEMORY_IMPORTANCE_MODERATE: Final[float] = 0.4
MEMORY_BUILD_CONTEXT_LIMIT: Final[int] = 10
MEMORY_RECALL_DEFAULT_LIMIT: Final[int] = 10
MEMORY_ID_HASH_MOD: Final[int] = 10000
MEMORY_PERSIST_FILE_RING2: Final[str] = "memory_ring2.jsonl"
MEMORY_PERSIST_FILE_RING3: Final[str] = "memory_ring3.db"


# ── Memory query limits ──
MEMORY_RECALL_LIMIT: Final[int] = 50
MEMORY_RECALL_LIMIT_LARGE: Final[int] = 200
MEMORY_BUILD_CONTEXT_ENTRIES: Final[int] = 10
MEMORY_ALERT_EXPORT_LIMIT: Final[int] = 500
MEMORY_LOG_QUERY_LIMIT: Final[int] = 10000
MEMORY_PAGER_RECALL_LIMIT: Final[int] = 50


# ── CI pipeline ──
CI_PIPELINE_CACHE_TTL: Final[float] = 300.0

# ── Direct session ──
DIRECT_SESSION_TIMEOUT: Final[float] = 3600.0


# ── Archive check ──
ARCHIVE_CHECK_INTERVAL: Final[float] = 86400.0
CRON_CHECK_INTERVAL: Final[float] = 60.0

# ── Resource buffer (ring file buffer) ──
RESOURCE_BUFFER_SLOT_CAPACITY: Final[int] = 64
RESOURCE_BUFFER_SLOT_NAME: Final[str] = "slot_{:04d}.dat"
RESOURCE_BUFFER_AUTO_EXPAND: Final[bool] = True
RESOURCE_BUFFER_FLUSH_INTERVAL: Final[float] = 30.0
RESOURCE_BUFFER_HIDDEN_TTL: Final[float] = 300.0


# ── Boot VFS mount paths ──
BOOT_VFS_TEMP_PATH: Final[str] = _tf.gettempdir()


# ── Token monitoring (CentralCollector quotas) ──
TOKEN_CELL_QUOTA: Final[int] = 5_000_000
TOKEN_GLOBAL_QUOTA: Final[int] = 50_000_000


# NOTE: Path constants moved to l1.kernel.paths.PraxisPaths.
# Use: from l1.kernel.paths import get_paths; get_paths().<attr>


# ── Sandbox ──
SANDBOX_PROFILE_READ_ONLY: Final[str] = "DANGER_0"
SANDBOX_PROFILE_SAFE_WRITE: Final[str] = "DANGER_1"
SANDBOX_PROFILE_NETWORK: Final[str] = "DANGER_2"
SANDBOX_PROFILE_FULL: Final[str] = "DANGER_3"
SANDBOX_PROFILE_HOST: Final[str] = "DANGER_4"
# SANDBOX_TMP_ROOT moved to l1.kernel.paths.get_paths().sandbox_root
SANDBOX_EXEC_TIMEOUT: Final[float] = 300.0

# ── Fault tolerance ──
FAULT_AUTONOMOUS_RECONNECT_INTERVAL: Final[float] = 5.0

# ── Workspace ──
WORKSPACE_MAX_RECENT: Final[int] = 20

# ── Verify cadence ──
VERIFY_CMDS: Final[frozenset[str]] = frozenset({
    "cargo", "tsc", "make", "npm", "pytest", "mvn", "gradle",
    "gcc", "clang", "dotnet", "ruff", "black", "mypy", "pyright",
    "go build", "go test", "cargo check", "cargo test",
})
SANDBOX_MAX_OUTPUT: Final[int] = 5000

# ── Permission defaults ──
PERMISSION_DEFAULT_POLICY: Final[str] = "allow_all"
"""Default Cell delegation policy (legacy). 'allow_all' = any Peer Agent can delegate any SubAgent."""
GLOBAL_SUBAGENT_ENABLED: Final[bool] = False
"""Global kill switch for all SubAgent delegation. False = all specs invisible system-wide."""


# ── State file naming templates (format strings, not paths) ──
SANDBOX_STATE_TEMPLATE: Final[str] = "{cell_id}.state.json"
SNAPSHOT_PATH_TEMPLATE: Final[str] = "{snapshot_id}.snapshot.json"
SKILL_LEAN_CASE_TEMPLATE: Final[str] = "{agent_id}_{tool_name}_{ts}.json"
AGENT_SESSION_TEMPLATE: Final[str] = "{ts}_{prefix}.json"


# ── Think quota (ThinkQuotaRegistry defaults) ──
THINK_BUDGET_GLOBAL_DEFAULT: Final[int] = 0
THINK_REASONING_DEFAULT: Final[str] = "none"


# ── Cell PMU (Performance Monitoring Unit) defaults ──
PMU_HISTORY_SIZE: Final[int] = 3600
PMU_SNAPSHOT_INTERVAL: Final[float] = 60.0
PMU_COUNTER_GROUPS: Final[list[str]] = [
    "cards", "tools", "cache", "scouts", "bus", "token", "agent", "watchdog",
]


# ── I-Cache (Instruction Cache) defaults ──
ICACHE_MAX_ENTRIES: Final[int] = 500
ICACHE_TTL: Final[float] = 3600.0          # 1 hour — instruction data changes slowly
ICACHE_LFU_DECAY: Final[float] = 0.95     # frequency counter decay per tick


# ── Context governance / compression thresholds ──
CONTEXT_PRESSURE_WARN: Final[float] = 0.60
CONTEXT_PRESSURE_MEDIUM: Final[float] = 0.80
CONTEXT_PRESSURE_CRITICAL: Final[float] = 0.95
CONTEXT_BUILD_MAX_TOKENS: Final[int] = 4096
CONTEXT_BUILD_MIN_TOKENS: Final[int] = 1024

# ── MMU + TLB (Memory Management Unit) defaults ──
TLB_MAX_ENTRIES: Final[int] = 64
TLB_DEFAULT_RING: Final[int] = 1
TLB_CLEARANCE_FALLBACK: Final[int] = 1


# ── InterruptController (Priority Interrupt) defaults ──
IRQ_TABLE_SIZE: Final[int] = 32
IRQ_PRIORITY_LEVELS: Final[int] = 4        # NMI=0, HIGH=1, NORMAL=2, LOW=3


# ── StatsCenter (Unified Statistics Center) defaults ──
STATS_BUCKET_SIZE: Final[int] = 600               # seconds per bucket (10 min)
STATS_HISTORY_BUCKETS: Final[int] = 144            # 24h of buckets
STATS_SSE_BUFFER: Final[int] = 100                 # max SSE events buffered per subscriber
STATS_DEFAULT_WINDOW: Final[str] = "5m"            # default query window
