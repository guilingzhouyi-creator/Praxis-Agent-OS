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
SCOUT_MAX_PER_AGENT: Final[int] = 4
SCOUT_POOL_MAX_PER_AGENT: Final[int] = 4
SCOUT_POOL_IDLE_TIMEOUT: Final[float] = 60.0
SCOUT_CACHE_TTL: Final[float] = 30.0
SCOUT_CACHE_MAX_ENTRIES: Final[int] = 200
SCOUT_SESSION_TIMEOUT: Final[float] = 300.0


# ── ResultStore (tool result cache) ──
RESULT_STORE_MAX_ENTRIES: Final[int] = 500
RESULT_STORE_TTL: Final[float] = 300.0

# ── Sequence monitor (per-Cell anomaly detection) ──
SEQ_MONITOR_NGRAM: Final[int] = 3
SEQ_MONITOR_MIN_SAMPLES: Final[int] = 5
SEQ_MONITOR_ANOMALY_THRESHOLD: Final[float] = 0.05
SEQ_MONITOR_PATH: Final[str] = _os.environ.get("NOMOS_SEQ_MONITOR_PATH", ".praxis_seq_monitor.json")

# ── Reference Channel (async event recorder, non-blocking) ──
RC_PATH: Final[str] = _os.environ.get("NOMOS_RC_PATH", ".praxis_reference_channel.jsonl")
RC_FLUSH_INTERVAL: Final[float] = 5.0
RC_MAX_EVENTS: Final[int] = 100
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
OUTPUT_MAX_LINES: Final[int] = 50
OUTPUT_MAX_CHARS: Final[int] = 4000

# ── Log service ──
LOG_MAX_MEMORY_ENTRIES: Final[int] = 5000
LOG_MAX_FILE_SIZE: Final[int] = 1024 * 1024
LOG_MAX_FILES: Final[int] = 5
LOG_EXPORT_LIMIT: Final[int] = 10000

# ── Error Bus service ──
ERROR_BUS_BUFFER: Final[int] = 5000
ERROR_BUS_DEDUP_WINDOW: Final[int] = 300
ERROR_BUS_EXPORT_LIMIT: Final[int] = 10000


# ── Context register ──
MAX_REGISTER_TOKENS: Final[int] = 4096

# ── Shell buffer ──
BUFFER_MAX: Final[int] = 2000

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


# ── Config directory ──
PRAXIS_CONFIG_DIR: Final[str] = ".config/nomos-praxis"


# ── Memory ring constants ──
MEMORY_RING_WORKING_BUDGET: Final[int] = 8192
MEMORY_RING_SHORT_BUDGET: Final[int] = 32768
MEMORY_RING_LONG_BUDGET: Final[int] = 131072
MEMORY_RING_WORKING_TTL: Final[float] = 1800.0
MEMORY_RING_SHORT_TTL: Final[float] = 86400.0
MEMORY_RING_LONG_TTL: Final[float] = 0.0
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


# ── Boot VFS mount paths ──
BOOT_VFS_TEMP_PATH: Final[str] = "/tmp"


# ── Token monitoring (CentralCollector quotas) ──
TOKEN_CELL_QUOTA: Final[int] = 5_000_000
TOKEN_GLOBAL_QUOTA: Final[int] = 50_000_000


# ── Data root directory (XDG-style, overridable via env var) ──
_DEFAULT_DATA_ROOT: Final[str] = _os.path.join(_tf.gettempdir(), "nomos-praxis-data")
PRAXIS_DATA_DIR: Final[str] = _os.environ.get("PRAXIS_DATA_DIR", _DEFAULT_DATA_ROOT)

# ── Data file paths (unified under PRAXIS_DATA_DIR) ──
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
PRAXIS_MESSAGE_GATE_STATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "message_gate.json")
PRAXIS_CELL_STATE_TEMPLATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "cell_{}.json")
PRAXIS_VAULT_SALT: Final[str] = _os.path.join(PRAXIS_DATA_DIR, ".praxis_vault_salt")
PRAXIS_SETTINGS_FILE: Final[str] = ".praxis_settings.json"
PRAXIS_ARCHIVE_DB: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "archive.db")
PRAXIS_MCP_STATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "mcp_state.json")
PRAXIS_SEQ_MONITOR_TEMPLATE: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "seq_monitor_{}.json")
PRAXIS_MONITOR_BUS_LOG: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "monitor_bus.jsonl")


# ── Sandbox ──
SANDBOX_PROFILE_READ_ONLY: Final[str] = "DANGER_0"
SANDBOX_PROFILE_SAFE_WRITE: Final[str] = "DANGER_1"
SANDBOX_PROFILE_NETWORK: Final[str] = "DANGER_2"
SANDBOX_PROFILE_FULL: Final[str] = "DANGER_3"
SANDBOX_PROFILE_HOST: Final[str] = "DANGER_4"
SANDBOX_TMP_ROOT: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "sandbox")
SANDBOX_EXEC_TIMEOUT: Final[float] = 300.0
SANDBOX_MAX_OUTPUT: Final[int] = 5000


# ── State file naming templates ──
SANDBOX_STATE_TEMPLATE: Final[str] = "{cell_id}.state.json"
SNAPSHOT_PATH_TEMPLATE: Final[str] = "{snapshot_id}.snapshot.json"
SKILL_LEAN_CASE_TEMPLATE: Final[str] = "{agent_id}_{tool_name}_{ts}.json"
SKILL_LEAN_DIR: Final[str] = _os.path.join(PRAXIS_DATA_DIR, "skills", "lean")
AGENT_SESSION_TEMPLATE: Final[str] = "{ts}_{prefix}.json"


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


# ── Boot VFS temp path ──
BOOT_VFS_TEMP_PATH: Final[str] = "/tmp"
