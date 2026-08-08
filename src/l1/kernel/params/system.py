"""Constants: system services — persistence, data paths, sandbox, cache, polling."""

import os as _os
import tempfile as _tf
from typing import Final

# ── File cache (Cell-level, shared across agents) ──

FILE_CACHE_MAX_ENTRIES: Final[int] = 500
# Max bytes a single cached file value may occupy
FILE_CACHE_MAX_SIZE: Final[int] = 10 * 1024 * 1024
# Cache entry lifetime in seconds before eviction
FILE_CACHE_TTL: Final[float] = 60.0

# ── Filesystem service (fs_adapter watch polling) ──

FS_WATCH_INTERVAL: Final[float] = 2.0

# ── Central security verdict gate scores (central_security.py) ──

SECURITY_GATE_SCORE_CONSTITUTION: Final[float] = 0.3
# Verdict score added when constitution review errors out
SECURITY_GATE_SCORE_CONSTITUTION_ERROR: Final[float] = 0.5
# Weight of gatechain check failures in the security verdict
SECURITY_GATE_SCORE_GATECHAIN: Final[float] = 0.5
# Weight of authentication failures in the security verdict
SECURITY_GATE_SCORE_AUTH: Final[float] = 0.5
# Weight of insufficient ring clearance in the security verdict
SECURITY_GATE_SCORE_CLEARANCE: Final[float] = 0.1
# Weight of tool-mode (danger) violations in the security verdict
SECURITY_GATE_SCORE_TOOL_MODE: Final[float] = 0.8
# Weight of rate-limit violations in the security verdict
SECURITY_GATE_SCORE_RATE_LIMIT: Final[float] = 0.4


# ── Context register (Cell-level, shared across agent terminals) ──

CONTEXT_REGISTER_MAX_ENTRIES: Final[int] = 200


# ── Scout pool ──

SCOUT_POOL_MIN_IDLE: Final[int] = 2
# Cap on scouts spawned across all agents
SCOUT_POOL_MAX_TOTAL: Final[int] = 16
SCOUT_POOL_MAX: Final[int] = 16  # alias for SCOUT_POOL_MAX_TOTAL
SCOUT_POOL_MAX_PER_AGENT: Final[int] = 4
MAX_SCOUTS_PER_AGENT: Final[int] = 4  # alias for SCOUT_POOL_MAX_PER_AGENT
SCOUT_POOL_IDLE_TIMEOUT: Final[float] = 60.0
SCOUT_CACHE_TTL: Final[float] = 30.0
# Max scout outcomes cached per cell
SCOUT_CACHE_MAX_ENTRIES: Final[int] = 200
# Total wait for scout results before giving up
SCOUT_TIMEOUT: Final[float] = 300.0
SCOUT_COLLECT_TIMEOUT: Final[float] = 310.0  # async scout collection wait (s)
TOOL_SCOUT_RUN_TIMEOUT: Final[int] = 180
TOOL_SCOUT_MAX_STEPS: Final[int] = 10


# ── ResultStore (tool result cache) ──
RESULT_STORE_MAX_ENTRIES: Final[int] = 500
RESULT_STORE_TTL: Final[float] = 300.0

# ── Sequence monitor (per-Cell anomaly detection) ──
SEQ_MONITOR_NGRAM: Final[int] = 3
SEQ_MONITOR_MIN_SAMPLES: Final[int] = 5
# Anomaly score above which a sequence is flagged
SEQ_MONITOR_ANOMALY_THRESHOLD: Final[float] = 0.05
# Persistence file for sequence-monitor state
SEQ_MONITOR_PATH: Final[str] = _os.environ.get("PRAXIS_SEQ_MONITOR_PATH", ".praxis_seq_monitor.json")

# ── Reference Channel (ring buffer + periodic flush) ──
RC_PATH: Final[str] = _os.environ.get("PRAXIS_RC_PATH", ".praxis/.praxis_reference_channel.jsonl")
RC_FLUSH_INTERVAL: Final[float] = 5.0
# Reference-channel ring buffer capacity
RC_RING_SIZE: Final[int] = 1000
# Characters kept when hashing reference entries
RC_SHA256_TRUNC: Final[int] = 16
# Max entries returned by reference-channel exports
RC_EXPORT_LIMIT: Final[int] = 999999


# ── Persistence / data paths ──
PRAXIS_CONFIG_DIR: Final[str] = ".config/praxis"
# Default config directory name (relative/absolute path).
# Enable automatic persistence of runtime state
PERSIST_AUTO: Final[bool] = True
# Seconds between automatic persistence sweeps
PERSIST_INTERVAL: Final[float] = 30.0
# Max event rows returned per query
EVENT_STORE_MAX_QUERY: Final[int] = 5000

# Seconds between card registry auto-saves
CARD_REGISTRY_AUTO_SAVE: Final[float] = 30.0
# Poll interval for dispatching queued cards
CARD_DISPATCH_INTERVAL: Final[float] = 1.0
# Cap on cards waiting in the pending queue
CARD_QUEUE_PENDING_MAX: Final[int] = 200
# Cap on cards queued per cell
CARD_QUEUE_CELL_MAX: Final[int] = 10
# Seconds between card approval-gate auto-saves
CARD_GATE_AUTO_SAVE: Final[float] = 10.0
# Seconds between pending-queue auto-saves
PENDING_QUEUE_AUTO_SAVE: Final[float] = 5.0
# Seconds between issue-table auto-saves
ISSUE_TABLE_AUTO_SAVE: Final[float] = 10.0
# Seconds between approval-gate auto-saves
APPROVAL_GATE_AUTO_SAVE: Final[float] = 5.0
# Seconds between sandbox-state auto-saves (0 = disabled)
SANDBOX_STATE_AUTO_SAVE: Final[float] = 0.0
# Seconds between todo-table auto-saves
TODO_TABLE_AUTO_SAVE: Final[float] = 30.0
# Seconds between transaction-area auto-saves
TRANSACTION_AREA_AUTO_SAVE: Final[float] = 30.0
# Seconds between statechart-state auto-saves
STATECHARTS_AUTO_SAVE: Final[float] = 30.0
# Seconds between execution-result auto-saves
EXECUTION_RESULTS_AUTO_SAVE: Final[float] = 30.0
# Max kept execution records per card (oldest trimmed)
EXECUTION_RESULT_RETENTION: Final[int] = 200
# Seconds between dialogue-session auto-saves
DIALOGUE_SESSION_AUTO_SAVE: Final[float] = 30.0
# Max seconds a card waits in the approval gate
APPROVAL_GATE_WAIT_TIMEOUT: Final[float] = 300.0
# Max idle seconds before a dialogue session expires
DIALOGUE_IDLE_TIMEOUT: Final[float] = 300.0

# ── Execution engine / dialogue / transaction defaults ──
EXECUTION_STEP_TIMEOUT: Final[float] = 30.0
DIALOGUE_MAX_TURNS: Final[int] = 20
# Token budget for dialogue context assembly
DIALOGUE_MAX_CONTEXT_TOKENS: Final[int] = 4096
# Persist dialogue state every N exchanged turns
DIALOGUE_PERSIST_EVERY: Final[int] = 5
# Cap on queued transactions per area
TRANSACTION_AREA_MAX_QUEUE: Final[int] = 100

# ── Monitor bus / error bus / record center ──
MONITOR_BUS_MAX_QUEUED: Final[int] = 200
ERROR_BUS_QUERY_LIMIT: Final[int] = 50
# Default row limit for record-center queries
RECORD_CENTER_DEFAULT_LIMIT: Final[int] = 50
# Days records are kept before archival
RECORD_CENTER_RETENTION_DAYS: Final[int] = 30
# Auto-export cadence for the RecordCenter (seconds between JSONL exports)
RECORD_CENTER_AUTO_EXPORT_INTERVAL: Final[float] = 300.0

# ── Memory ring quality scoring (quality_note) ──
MEMORY_RING_SCORE_CHAR_WEIGHT: Final[float] = 0.3
MEMORY_RING_SCORE_TAG_WEIGHT: Final[int] = 5
# Points added for high-importance notes
MEMORY_RING_SCORE_HIGH_IMPORTANCE: Final[int] = 20
# Points added for moderate-importance notes
MEMORY_RING_SCORE_MODERATE_IMPORTANCE: Final[int] = 10
# Points added for long note bodies
MEMORY_RING_SCORE_LONG_TOKENS: Final[int] = 15
# Points added for medium-length note bodies
MEMORY_RING_SCORE_MEDIUM_TOKENS: Final[int] = 5
# Quality score marking a good note
MEMORY_RING_SCORE_GOOD_THRESHOLD: Final[int] = 40
# Quality score marking an average note
MEMORY_RING_SCORE_AVERAGE_THRESHOLD: Final[int] = 15

# ── Statecharts region thresholds (statecharts.py) ──
STATECHART_HEALTH_FAIL_THRESHOLD: Final[int] = 3  # ft: consecutive failures → DEGRADED
STATECHART_HEALTH_SUCCESS_THRESHOLD: Final[int] = 5  # st: consecutive successes → HEALTHY
STATECHART_HEALTH_TIMEOUT: Final[int] = 15  # hto: heartbeat timeout
STATECHART_CRASH_TIMEOUT: Final[int] = 30  # cto: crash timeout
STATECHART_RESOURCE_TOKEN_BUDGET: Final[int] = 73000  # tb: token budget
STATECHART_RESOURCE_MEMORY_LIMIT: Final[int] = 500  # ml: memory limit
STATECHART_COMM_DEGRADE_THRESHOLD: Final[float] = 10.0  # dt: latency degrade threshold
STATECHART_COMM_DISCONNECT_THRESHOLD: Final[float] = 30.0  # dst: disconnect threshold

# ── Model strategy / probe cache (model_strategy.py) ──
MODEL_STRATEGY_MAX_WORKERS: Final[int] = 4
MODEL_STRATEGY_CACHE_TTL: Final[float] = 86400.0  # 24h probe cache

# ── Counter token-rate window (counter.py) ──
COUNTER_TOKEN_RATE_WINDOW: Final[float] = 60.0

# ── L3B message pool default limit (l3b_message_pool.py) ──
L3B_MESSAGE_POOL_DEFAULT_LIMIT: Final[int] = 10

# ── Config watcher interval (config_loader.py) ──
CONFIG_WATCH_INTERVAL: Final[float] = 30.0

# ── Card registry client timeouts (card_registry_protocol.py) ──
CARD_REGISTRY_TIMEOUT: Final[float] = 15.0
CARD_REGISTRY_PUBLISH_TIMEOUT: Final[float] = 30.0


# ── Fault tolerance ──
HEARTBEAT_TIMEOUT: Final[float] = 15.0
CRASH_TIMEOUT: Final[float] = 30.0


# ── Network / CI / Cache defaults (consolidated) ──
NET_PEER_TIMEOUT: Final[float] = 60.0
CI_DEFAULT_TIMEOUT: Final[float] = 300.0
# Default TTL for the L4 result cache
CACHE_DEFAULT_TTL: Final[float] = 60.0

# ── CellCache (L2) — per-Cell shared cache sizes ──
CELL_CACHE_HOT_SIZE: Final[int] = 50  # Hot Ring: latest summaries
CELL_CACHE_INDEX_SIZE: Final[int] = 200  # Index Chain: key → summary
CELL_CACHE_KV_SIZE: Final[int] = 100  # KV Cache: full values
CELL_CACHE_HOT_TTL: Final[float] = 300.0  # 5 min
CELL_CACHE_INDEX_TTL: Final[float] = 900.0  # 15 min
CELL_CACHE_KV_TTL: Final[float] = 1800.0  # 30 min
CONTEXT_MAX_REGISTER_TOKENS: Final[int] = 4096
MEMORY_MIN_CONTENT_LEN: Final[int] = 30
MEMORY_RESTORE_RING2_LIMIT: Final[int] = 50  # reset_agent_context ring2 restore cap


# ── Identity ──
PROOF_TTL: Final[float] = 30.0


# ── Scheduler time slice ──
DEFAULT_QUANTUM: Final[float] = 15.0
MAX_PREEMPT: Final[float] = 60.0


# ── Memory ring capacities ──
RING1_CAPACITY: Final[int] = 32
RING2_CAPACITY: Final[int] = 200
# Long-term memory ring capacity
RING3_CAPACITY: Final[int] = 1000
# Ring-2 entries restored on context rebuild (0 = restore all)
MEMORY_RING2_RESTORE_LIMIT: Final[int] = 0
# Ring-3 entries restored on context rebuild (0 = restore all)
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
# Max rotated log files retained
LOG_MAX_FILES: Final[int] = 5
# Max log entries exported per request
LOG_EXPORT_LIMIT: Final[int] = 10000

# ── Error Bus service ──
ERROR_BUS_BUFFER: Final[int] = 5000
ERROR_BUS_DEDUP_WINDOW: Final[int] = 300
# Max error records exported per request
ERROR_BUS_EXPORT_LIMIT: Final[int] = 10000
# Top-N error sources shown in summaries
ERROR_BUS_TOP_SOURCES: Final[int] = 10

# ── Observability Bus defaults ──
OBS_AUDIT_LIMIT: Final[int] = 20


# ── Shell buffer ──
BUFFER_MAX: Final[int] = 2000
SHELL_AUTOCOMPLETE_LIMIT: Final[int] = 15
# Max agent names offered by autocomplete
SHELL_AUTOCOMPLETE_AGENT_LIMIT: Final[int] = 10
# Hard cap on stored shell history entries
SHELL_HISTORY_MAX_LIMIT: Final[int] = 200
# Default number of history entries shown
SHELL_HISTORY_DEFAULT_LIMIT: Final[int] = 20
SHELL_AUTOCOMPLETE_DISPLAY_LIMIT: Final[int] = 15  # commands shown in help
TOOL_RESULT_DISPLAY_LIMIT: Final[int] = 5
SCOUT_FINDINGS_DISPLAY_LIMIT: Final[int] = 5
# Max lean-case entries shown in /skills output
SKILL_LEAN_CASES_LIMIT: Final[int] = 20
SKILL_LIST_DISPLAY_LIMIT: Final[int] = 30  # max skills shown in /skills list
SKILL_WRITE_MIN_RING: Final[int] = 3  # minimum ring clearance to create/update/delete skills
SKILL_WRITE_ROLES: Final[tuple[str, ...]] = ("l3", "reviewer", "deployer")
SKILL_TTL_DAYS: Final[int] = 7  # evolved skills unused for this long are marked stale
SKILL_TTL_EXTEND_PER_USE: Final[int] = 3600  # each bump_usage extends the effective TTL by this many seconds
SKILL_LIBRARY_MAX: Final[int] = 50  # hard cap on evolved skills; curation evicts lowest contribution
SKILL_CATALOG_HOOK_LIMIT: Final[int] = 5  # max skills injected by SkillCatalogHook at session start
# Progressive disclosure: full skill index appended after the curated slots
SKILL_CATALOG_FULL_INDEX_ENABLED: Final[bool] = False  # opt-in full catalog list
SKILL_CATALOG_FULL_INDEX_LIMIT: Final[int] = 50  # max entries in the full index
# Audience-aware session catalogs (strategy → L3A, execution → peers)
SKILL_AUDIENCE_FILTER_ENABLED: Final[bool] = True
# L3A decision layer sees the execution capability list (delegation view)
SKILL_STRATEGY_CAPABILITY_VIEW: Final[bool] = True
SKILL_AUTO_ACTIVATE_BUILTIN: Final[bool] = True  # inject built-in skills into every session's system prompt
# ── Evolved-skill content contract (parity with built-in contract tests) ──
# Evolved (LLM-generated) skills must pass the same content checks as the
# built-in catalog: no project-specific path literals and no instructions
# that violate constitutional rules. Violations are scrubbed/dropped so a
# malformed LLM response cannot register an invalid skill.
SKILL_CONTRACT_FORBIDDEN_PATTERNS: Final[tuple[str, ...]] = (
    r"bypass.{0,20}sandbox",
    r"modify.{0,20}constitution",
    r"write outside.{0,20}territory",
    r"skip.{0,20}gate",
    r"swallow.{0,20}exception",
)
SKILL_CONTRACT_FORBIDDEN_PATHS: Final[tuple[str, ...]] = (
    "src/l",
    "tests/infra",
    "praxis.yaml",
    ".praxis/skills",
    "l1.kernel",
    "l3.",
    "StatsCenter",
    "CardRegistry",
    "GateChain",
)
# ── Evolved-skill conflict detection (R4Agent consistency pass) ──
# Two evolved skills for the same tool whose prompts overlap more than this
# ratio (token-set Jaccard) are flagged as duplicates; rules that directly# contradict (DO vs DON'T on the same topic) are flagged as conflicts.
SKILL_CONFLICT_SIMILARITY: Final[float] = 0.6
SKILL_CONFLICT_SCAN_LIMIT: Final[int] = 50  # evolved skills scanned per tick
# ── Skill posture (productive vs offensive) ──────────────────────────────
# Distinguishes normal project/build work from reverse-engineering / attack
# testing. Offensive skills are registered but NEVER injected into a session
# unless explicitly authorized (default-deny, least privilege).
SKILL_POSTURE_PRODUCTIVE: Final[str] = "productive"  # normal build/dev work (default)
SKILL_POSTURE_OFFENSIVE: Final[str] = "offensive"  # reverse / attack testing
SKILL_POSTURE_DEFAULT: Final[str] = SKILL_POSTURE_PRODUCTIVE
SKILL_POSTURE_VALID: Final[tuple[str, ...]] = (SKILL_POSTURE_PRODUCTIVE, SKILL_POSTURE_OFFENSIVE)
# Skill disclosure depth — full (default) / index (name+desc only) / none (hidden)
SKILL_DISCLOSURE_DEFAULT: Final[str] = "full"
SKILL_DISCLOSURE_VALID: Final[tuple[str, ...]] = ("full", "index", "none")
# Card natures that authorize injecting offensive-posture skills into a
# session. The L3A decision layer marks a card with one of these natures;
# AgentLoop derives the session-level authorization flag from it (default-deny
# otherwise, so offensive skills never leak into ordinary build sessions).
SKILL_OFFENSIVE_AUTHORIZED_NATURES: Final[tuple[str, ...]] = ("offensive",)
# Master switch for the posture gate (soft control, "honest-agent" gate): when
# enabled (default) offensive-posture skills are only injected/usable when the
# driving card nature is in SKILL_OFFENSIVE_AUTHORIZED_NATURES; when disabled
# the gate is bypassed entirely (dedicated pentest frontends may turn it off
# at runtime via the API — this is deliberately not a hard security boundary).
SKILL_OFFENSIVE_ENABLED: Final[bool] = True
# ── Security mode (system posture: productive vs security-test) ───────────
# Combined with harness.mode into get_posture(): productive posture grants no
# attack capability; security-test posture is attack-classified and only
# reaches full_power after an explicit detection-bypass confirmation.
SECURITY_MODE_PRODUCTIVE: Final[str] = "productive"
SECURITY_MODE_TEST: Final[str] = "security-test"
SECURITY_MODE_DEFAULT: Final[str] = SECURITY_MODE_PRODUCTIVE
SECURITY_MODES: Final[tuple[str, ...]] = (SECURITY_MODE_PRODUCTIVE, SECURITY_MODE_TEST)
# ── Danger-action notification queue (kernel/notify.py) ──────────────────
# Bounded in-memory broadcast history kept by the default notify adapter.
NOTIFY_QUEUE_MAX: Final[int] = 50
# Security-team domain bindings (attack posture): domain → skill white-list.
# Activate_attack_team() creates one peer agent per domain and binds its
# skills. Empty by default — security-test mode starts with no attack
# capability until a deployment configures domains.
TEAM_ATTACK_DOMAINS: Final[dict[str, list[str]]] = {}
# Seconds in one hour (timeout baselines)
SECONDS_PER_HOUR: Final[int] = 3600
# Seconds in one day (24h TTL baselines)
SECONDS_PER_DAY: Final[int] = 86400
# Max cell events returned per query
CELL_EVENTS_LIMIT: Final[int] = 20
# Default priority for cron-registered cards
CRON_DEFAULT_PRIORITY: Final[int] = 5
DEFAULT_CELL_INITIAL_ROLES: Final[int] = 3  # max default roles when creating a Cell

# ── Token budget ──
DEFAULT_TOKEN_BUDGET: Final[int] = 73000


# ── Persistence ──
PERSIST_QUERY_LIMIT: Final[int] = 100
PERSIST_EXPORT_LIMIT: Final[int] = 500
# Uncommitted appends before the event store batches a commit
PERSIST_COMMIT_BATCH: Final[int] = 32
# Max interrupt records exported at once
PERSIST_EXPORT_INTERRUPT_LIMIT: Final[int] = 50

# ── Nonce cleanup ──
NONCE_CLEANUP_AGE: Final[float] = 60.0

# ── Poll/sleep intervals ──
POLL_INTERVAL_DEFAULT: Final[float] = 0.1
POLL_INTERVAL_FAST: Final[float] = 0.01
# Slow poll interval for background loops
POLL_INTERVAL_SLOW: Final[float] = 0.05
# Poll interval while a loop is paused
POLL_INTERVAL_PAUSED: Final[float] = 0.5
# Artificial delay injected in mock mode
MOCK_DELAY: Final[float] = 0.05
# Poll interval for handler dispatch loops
POLL_INTERVAL_HANDLER: Final[float] = 0.3
# Seconds between fault-condition checks
FAULT_CHECK_INTERVAL: Final[float] = 5.0
# Seconds between fault recovery retries
FAULT_RETRY_INTERVAL: Final[float] = 1.0
# Backoff sleep between execution retries
EXEC_BACKOFF_INTERVAL: Final[float] = 1.0
# Seconds between scout health checks
SCOUT_MONITOR_INTERVAL: Final[float] = 5.0

# ── Log/display truncation limits ──
LOG_TRUNC_20: Final[int] = 20
LOG_TRUNC_30: Final[int] = 30
# Truncate displayed text to 40 characters
LOG_TRUNC_40: Final[int] = 40
# Truncate displayed text to 50 characters
LOG_TRUNC_50: Final[int] = 50
# Truncate displayed text to 60 characters
LOG_TRUNC_60: Final[int] = 60
# Truncate displayed text to 80 characters
LOG_TRUNC_80: Final[int] = 80
# Truncate displayed text to 100 characters
LOG_TRUNC_100: Final[int] = 100
# Truncate displayed text to 120 characters
LOG_TRUNC_120: Final[int] = 120
# Truncate displayed text to 150 characters
LOG_TRUNC_150: Final[int] = 150
# Truncate displayed text to 200 characters
LOG_TRUNC_200: Final[int] = 200
# Truncate displayed text to 300 characters
LOG_TRUNC_300: Final[int] = 300
# Truncate displayed text to 500 characters
LOG_TRUNC_500: Final[int] = 500
# Truncate displayed text to 1000 characters
LOG_TRUNC_1000: Final[int] = 1000
# Truncate displayed text to 2000 characters
LOG_TRUNC_2000: Final[int] = 2000
# Truncate displayed text to 3000 characters
LOG_TRUNC_3000: Final[int] = 3000
# Truncate displayed text to 4000 characters
LOG_TRUNC_4000: Final[int] = 4000
# Truncate displayed text to 5000 characters
LOG_TRUNC_5000: Final[int] = 5000
# Truncate displayed text to 10000 characters
LOG_TRUNC_10000: Final[int] = 10000

# ── Tool result display limits ──
TOOL_RESULTS_LIMIT_DEFAULT: Final[int] = 100
TOOL_RESULTS_LIMIT_LARGE: Final[int] = 200
# Max issues returned by the issues tool
TOOL_ISSUES_LIMIT: Final[int] = 50
# Max memory entries returned per tool call
TOOL_MEMORY_RESULTS_LIMIT: Final[int] = 20
# Max web search results per tool call
TOOL_WEB_RESULTS_LIMIT: Final[int] = 10
# Max symbols returned by the LSP tool
TOOL_LSP_SYMBOL_LIMIT: Final[int] = 50

# ── Hash display truncation limits ──
HASH_TRUNC_SHORT: Final[int] = 8
# Ultra-short hash display length (in-memory message ids)
HASH_TRUNC_SHORTEST: Final[int] = 4
HASH_TRUNC_MEDIUM: Final[int] = 12
# Shortish hash display length (persisted ids)
HASH_TRUNC_SIX: Final[int] = 6
# Long-form hash display length
HASH_TRUNC_LONG: Final[int] = 16

# ── Scheduler ──
SCHEDULER_BACKGROUND_PRIORITY: Final[int] = 10
SCHEDULER_TASK_RETENTION: Final[int] = 100


# ── Pager / memory recall ──
PAGER_RECALL_LIMIT: Final[int] = 50
MEMORY_RECALL_PAGE_LIMIT: Final[int] = 50  # _comm.py memory recall page size

# ── TUI ──
TUI_REFRESH_MS: Final[int] = 300
TUI_MAX_EVENTS: Final[int] = 200
# Cards shown in the TUI card list (narrow)
TUI_CARD_LIST_LIMIT: Final[int] = 5
# Cards shown in the TUI card list (wide)
TUI_CARD_LIST_LIMIT_WIDE: Final[int] = 8


# ── Context pager ──
CHUNK_SIZE_TOKENS: Final[int] = 512

# ── Search engine defaults (L4 search/) ──
SEARCH_DEFAULT_RESULTS: Final[int] = 20
SYMBOL_SEARCH_RESULTS: Final[int] = 30
# Doc matches returned per search
DOC_SEARCH_RESULTS: Final[int] = 10
# Score bonus for exact symbol-name match
SEARCH_SCORE_FULL_MATCH: Final[float] = 2.0
# Score bonus for name-substring match
SEARCH_SCORE_NAME_MATCH: Final[float] = 1.0
SEARCH_CACHE_MAX: Final[int] = 200  # search_engine.py result cache cap
SEARCH_SCORE_DOCSTRING_MATCH: Final[float] = 0.5
SEARCH_SCORE_MODULE_MATCH: Final[float] = 0.3
# Score bonus for package-level matches
SEARCH_SCORE_PACKAGE_MATCH: Final[float] = 0.2
# Score for exact symbol-name hits
SEARCH_SYMBOL_EXACT_MATCH: Final[float] = 1.0
# Score for partial symbol-name hits
SEARCH_SYMBOL_PARTIAL_MATCH: Final[float] = 0.5
# Score for symbol hits via assignment
SEARCH_SYMBOL_ASSIGN_MATCH: Final[float] = 0.3
# Hard cap on search results returned
SEARCH_MAX_RESULTS: Final[int] = 200
# Directories skipped during code search
SEARCH_EXCLUDE_DIRS: Final[set[str]] = {
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "target",
    "build",
    "dist",
    ".tox",
}
# File extensions skipped during code search
SEARCH_EXCLUDE_EXTS: Final[set[str]] = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".bin",
    ".class",
    ".o",
    ".a",
    ".lib",
}


# ── User session ──
SESSION_TIMEOUT: Final[float] = 3600.0


# ── Version ──
KERNEL_VERSION: Final[str] = "0.4.2"
PRAXIS_CODENAME: Final[str] = "Aether"


# ── Memory ring constants ──
MEMORY_RING_WORKING_BUDGET: Final[int] = 8192
MEMORY_RING_SHORT_BUDGET: Final[int] = 32768
# Long-term ring token budget
MEMORY_RING_LONG_BUDGET: Final[int] = 131072
# Working-ring entry lifetime in seconds
MEMORY_RING_WORKING_TTL: Final[float] = 1800.0
# Short-ring entry lifetime in seconds
MEMORY_RING_SHORT_TTL: Final[float] = 86400.0
# Long-ring entry lifetime (0 = never expire)
MEMORY_RING_LONG_TTL: Final[float] = 0.0

# ── Memory importance / pressure thresholds ──
MEMORY_IMPORTANCE_BASE: Final[float] = 0.5
MEMORY_IMPORTANCE_DECISION: Final[float] = 0.3
# Importance weight for pattern observations
MEMORY_IMPORTANCE_PATTERN: Final[float] = 0.3
# Importance weight for summaries
MEMORY_IMPORTANCE_SUMMARY: Final[float] = 0.2
# Importance weight for raw observations
MEMORY_IMPORTANCE_OBSERVATION: Final[float] = 0.1
# Usage ratio marking high memory pressure
MEMORY_PRESSURE_HIGH: Final[float] = 0.80
# Usage ratio marking medium memory pressure
MEMORY_PRESSURE_MEDIUM: Final[float] = 0.60
# Seconds between memory-pressure rechecks
MEMORY_PRESSURE_INTERVAL: Final[float] = 60.0
# Recall ratio above which entries are promoted
MEMORY_PROMOTION_THRESHOLD: Final[float] = 0.6
# Importance cutoff for high-priority retention
MEMORY_IMPORTANCE_HIGH: Final[float] = 0.7
# Importance cutoff for very-high-priority retention
MEMORY_IMPORTANCE_VERY_HIGH: Final[float] = 0.85
# Importance cutoff for critical retention
MEMORY_IMPORTANCE_CRITICAL: Final[float] = 0.9
# Importance cutoff for moderate retention
MEMORY_IMPORTANCE_MODERATE: Final[float] = 0.4
# Max entries folded into built context
MEMORY_BUILD_CONTEXT_LIMIT: Final[int] = 10
# Default recall limit for memory queries
MEMORY_RECALL_DEFAULT_LIMIT: Final[int] = 10
# Modulus hashing memory ids across rings
MEMORY_ID_HASH_MOD: Final[int] = 10000
# Filename for ring-2 persistence
MEMORY_PERSIST_FILE_RING2: Final[str] = "memory_ring2.jsonl"
# Filename for ring-3 persistence
MEMORY_PERSIST_FILE_RING3: Final[str] = "memory_ring3.db"
MEMORY_GRAPH_LLM_TIMEOUT: Final[float] = 10.0  # LLM semantic-extraction timeout (seconds)


# ── Memory query limits ──
MEMORY_RECALL_LIMIT: Final[int] = 50
MEMORY_RECALL_LIMIT_LARGE: Final[int] = 200
# Entries included when building agent context
MEMORY_BUILD_CONTEXT_ENTRIES: Final[int] = 10
# Max memory alerts exported per request
MEMORY_ALERT_EXPORT_LIMIT: Final[int] = 500
# Max memory-log rows returned per query
MEMORY_LOG_QUERY_LIMIT: Final[int] = 10000
# Pager page size for memory recall
MEMORY_PAGER_RECALL_LIMIT: Final[int] = 50


# ── User profile side-channel ──
PROFILE_KIND_PREFERENCE: Final[str] = "preference"
PROFILE_KIND_DOMAIN_FOCUS: Final[str] = "domain_focus"
# Profile kind for decision-style entries
PROFILE_KIND_DECISION_STYLE: Final[str] = "decision_style"
# Profile kind for rejection-pattern entries
PROFILE_KIND_REJECTION: Final[str] = "rejection"
# Profile kind for habit entries
PROFILE_KIND_HABIT: Final[str] = "habit"
# Profile kind for correction entries
PROFILE_KIND_CORRECTION: Final[str] = "correction"
# Profile kind for trait entries
PROFILE_KIND_TRAIT: Final[str] = "trait"
# Profile kind for user-defined entries
PROFILE_KIND_CUSTOM: Final[str] = "custom"
# All recognized profile kinds (ordering defines ranking)
PROFILE_KINDS: Final[tuple[str, ...]] = (
    PROFILE_KIND_PREFERENCE,
    PROFILE_KIND_DOMAIN_FOCUS,
    PROFILE_KIND_DECISION_STYLE,
    PROFILE_KIND_REJECTION,
    PROFILE_KIND_HABIT,
    PROFILE_KIND_CORRECTION,
    PROFILE_KIND_TRAIT,
    PROFILE_KIND_CUSTOM,
)
# Hard cap on stored entries per user
PROFILE_MAX_ENTRIES_PER_USER: Final[int] = 500
# Hard cap on stored profile entries per user (oldest evicted on overflow).
# Default entry lifetime (90 days; 0 = never expires)
PROFILE_ENTRY_TTL_DEFAULT: Final[float] = 90 * 24 * 3600
# Default profile entry lifetime (90 days); 0 = never expires.
# Entries folded into a profile snapshot
PROFILE_SNAPSHOT_ENTRIES: Final[int] = 40
# Max entries folded into a profile snapshot for injection.
# Minimum raw entries before a refine pass
PROFILE_REFINE_MIN_ENTRIES: Final[int] = 5
# Minimum raw entries before a refine pass is worthwhile.
# Max raw entries fed to the refiner per pass
PROFILE_REFINE_MAX_RAW: Final[int] = 30
# Max raw entries fed to the LLM refiner per pass.
# Refiner LLM call timeout in seconds
PROFILE_REFINE_TIMEOUT: Final[float] = 20.0
# Refiner LLM call timeout (seconds).
# Confidence decay per decay cycle
PROFILE_DECAY_CONFIDENCE: Final[float] = 0.05
# Confidence decay per decay cycle (0 = disabled).
# Seconds between decay cycles
PROFILE_DECAY_INTERVAL: Final[float] = 3600.0
# Decay cycle interval in seconds (0 = disabled).
# R4 fonds used for profile persistence
PROFILE_FONDS: Final[str] = "user_profile"
# R4 fonds for profile persistence (series = user_id).
# Fallback profile user id
PROFILE_USER_DEFAULT: Final[str] = "default"
# Fallback user id when none is provided.
# Monitor-bus event name on profile updates
PROFILE_EMIT_EVENT: Final[str] = "stats.user_profile.updated"
# Monitor-bus event emitted on profile mutations.


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
# Glob matching resource-buffer slot files
RESOURCE_BUFFER_SLOT_GLOB: Final[str] = "slot_*.dat"
# Grow slot files automatically on overflow
RESOURCE_BUFFER_AUTO_EXPAND: Final[bool] = True
# Seconds between pending-to-slot flushes
RESOURCE_BUFFER_FLUSH_INTERVAL: Final[float] = 30.0
# Sleep between flush-loop polling rounds
RESOURCE_BUFFER_FLUSH_LOOP_SLEEP: Final[float] = 5.0
# Seconds a hidden file stays before cleanup
RESOURCE_BUFFER_HIDDEN_TTL: Final[float] = 300.0
# Subdirectory holding pending writes
RESOURCE_BUFFER_PENDING_DIR: Final[str] = "_pending"
# Subdirectory holding staged files
RESOURCE_BUFFER_HIDDEN_DIR: Final[str] = "_hidden"
# Checkpoint filename inside the buffer root
RESOURCE_BUFFER_CHECKPOINT_FILE: Final[str] = "_checkpoint.dat"
# Journal filename inside the buffer root
RESOURCE_BUFFER_JOURNAL_FILE: Final[str] = "_journal.jsonl"
# Root directory name for buffer storage
RESOURCE_BUFFER_ROOT_DIR: Final[str] = "resource_buffer"


# ── Lifecycle state ──
LIFECYCLE_STATE_FILE: Final[str] = ".praxis/lifecycle.json"


# ── Thread shutdown timeouts ──
THREAD_JOIN_TIMEOUT: Final[float] = 5.0  # daemon/service thread join on shutdown
THREAD_JOIN_TIMEOUT_QUICK: Final[float] = 2.0  # light thread join (poll/reference channels)


# ── L3B Message Pool ──
L3B_HOT_RING_SIZE: Final[int] = 200
L3B_MAILBOX_MAXLEN: Final[int] = 200
# Weight of load factor in the L3B routing score
L3B_LOAD_SCORE_WEIGHT: Final[float] = 0.6
# Base score given to every L3B peer
L3B_LOAD_SCORE_BASE: Final[float] = 0.4
# Queue fill ratio triggering persistence
L3B_PERSIST_HIGH_WATERMARK: Final[float] = 0.8
# Queued messages above which backpressure engages
L3B_BACKPRESSURE_THRESHOLD: Final[int] = 1000
# Seconds between backpressure rechecks
L3B_BACKPRESSURE_COOLDOWN: Final[float] = 30.0
# Subdirectory for L3B message persistence
L3B_MESSAGE_DIR: Final[str] = "l3b_messages"
# SQLite filename for L3B message metadata
L3B_MESSAGE_DB: Final[str] = "messages.db"


# ── File naming templates ──
LOG_EXPORT_FILE: Final[str] = "export_{ts}.json"
LOG_ROTATE_FILE: Final[str] = "log_{ts}.json"
# Filename template for error exports
ERROR_EXPORT_FILE: Final[str] = "error_export_{ts}.json"
# Filename template for record exports
RECORDS_EXPORT_FILE: Final[str] = "records_{ts}.json"
# Filename for agent snapshot exports
AGENT_SNAPSHOT_FILE: Final[str] = "snapshot.json"
# Filename for agent transcript exports
AGENT_TRANSCRIPT_FILE: Final[str] = "transcript.jsonl"
# Filename template for card YAML exports
CARD_YAML_EXPORT: Final[str] = "{name}.card.yaml"
# Filename template for agent checkpoints
CHECKPOINT_JSON_FILE: Final[str] = "{agent_id}.json"
# Filename for alert exports
ALERTS_FILE: Final[str] = "alerts.json"
# Glob matching boot snapshot files
BOOT_SNAPSHOT_GLOB: Final[str] = "*_boot.json"
# Glob matching snapshot files
SNAPSHOT_GLOB: Final[str] = "*.snapshot.json"
# Glob matching rotated log files
LOG_ROTATE_GLOB: Final[str] = "log_*.json"
# Filename template for patch exports
PATCH_JSON_FILE: Final[str] = "{patch_id}.json"


# ── Config file path templates (for discovery / fallback) ──
TOOLS_CONFIG_PATH: Final[str] = "config/tools.yaml"
COMMANDS_CONFIG_PATH: Final[str] = "config/commands.yaml"
# Main deployment config file name (used as fallback when paths unavailable)
PRAXIS_CONFIG_FILE: Final[str] = "config/praxis.yaml"


# ── Memory subdirectory names ──
MEMORY_AGENT_SESSIONS_DIR: Final[str] = "AGENT/sessions"
MEMORY_OPS_DIR: Final[str] = "ops"
# Subdirectory for phase memory
MEMORY_PHASE_DIR: Final[str] = "PHASE"
# Subdirectory for DSL memory
MEMORY_DSL_DIR: Final[str] = "DSL"
# Filename of the DSL compiler script
MEMORY_DSL_COMPILER: Final[str] = "compiler.py"
# Filename for the workspace index
MEMORY_WORKSPACES_FILE: Final[str] = "workspaces.json"


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
# Sandbox profile with network access (DANGER_2)
SANDBOX_PROFILE_NETWORK: Final[str] = "DANGER_2"
# Sandbox profile with full write access (DANGER_3)
SANDBOX_PROFILE_FULL: Final[str] = "DANGER_3"
# Sandbox profile with host-level access (DANGER_4)
SANDBOX_PROFILE_HOST: Final[str] = "DANGER_4"
# SANDBOX_TMP_ROOT moved to l1.kernel.paths.get_paths().sandbox_root

# ── Sandbox diff / cross-review tuning ──
DIFF_CONTEXT_LINES: Final[int] = 3  # context lines before/after a hunk
DIFF_CHAR_LEVEL_MAX_LINES: Final[int] = 10  # replace hunks <= N lines get char-level diff
DIFF_PINGPONG_WINDOW_SECONDS: Final[float] = 30.0  # same-agent rapid edit warn window
SANDBOX_EXEC_TIMEOUT: Final[float] = 300.0

# ── Fault tolerance ──
FAULT_AUTONOMOUS_RECONNECT_INTERVAL: Final[float] = 5.0

# ── Workspace ──
WORKSPACE_MAX_RECENT: Final[int] = 20

# ── Verify cadence ──
VERIFY_CMDS: Final[frozenset[str]] = frozenset(
    {
        "cargo",
        "tsc",
        "make",
        "npm",
        "pytest",
        "mvn",
        "gradle",
        "gcc",
        "clang",
        "dotnet",
        "ruff",
        "black",
        "mypy",
        "pyright",
        "go build",
        "go test",
        "cargo check",
        "cargo test",
    }
)
# Max bytes captured from sandbox command output
SANDBOX_MAX_OUTPUT: Final[int] = 5000

# ── Permission defaults ──
# ── Vault / credential vault ──
VAULT_FILENAME: Final[str] = "credential_vault.enc"
VAULT_SALT_FILENAME: Final[str] = ".praxis_vault_salt"
# AES-256 key size for vault encryption
VAULT_KEY_BYTES: Final[int] = 32
# Nonce length for vault AEAD encryption
VAULT_NONCE_LENGTH: Final[int] = 12
# HMAC signing key size for auth tokens
AUTH_SIGN_KEY_BYTES: Final[int] = 32
# Filename for MCP connection state
MCP_STATE_FILENAME: Final[str] = "mcp_state.json"
# HTTP status treated as MCP success
MCP_STATUS_OK: Final[int] = 200

# ── File editor ──
FILE_EDITOR_MAX_HISTORY: Final[int] = 100

# ── Card registry ──
CARD_STALE_ESCALATE_SECONDS: Final[int] = 3600  # QUEUED card older than this is escalated


# ── Ops console defaults ──
OPS_MAX_ALERTS: Final[int] = 200
OPS_CONSOLE_POOL_WARN_RATIO: Final[float] = 0.9
# Seconds between ops-console refreshes
OPS_CONSOLE_INTERVAL: Final[float] = 15.0
# Context ratio triggering transcript compression
SESSION_COMPRESS_THRESHOLD: Final[float] = 0.85
# Seconds without response before an agent is flagged
AGENT_UNRESPONSIVE_TIMEOUT: Final[float] = 60.0
# Interrupt count above which a cell is reported busy
INTERRUPT_HIGH_COUNT: Final[int] = 100


# ── Supervisor defaults ──
SUPERVISOR_WAIT_TIMEOUT: Final[float] = 5.0
SUPERVISOR_MONITOR_INTERVAL: Final[float] = 10.0
# Seconds between idle-supervisor sweeps
SUPERVISOR_IDLE_INTERVAL: Final[float] = 60.0
# Replicas spawned for ordinary supervised services
SUPERVISOR_DEFAULT_REPLICAS: Final[int] = 1
# Replicas spawned for sandbox services
SUPERVISOR_SANDBOX_REPLICAS: Final[int] = 2
# Replicas spawned for LLM engine workers
SUPERVISOR_LLM_REPLICAS: Final[int] = 4


# ── CI defaults ──
CI_MAX_RUNS: Final[int] = 50
CI_DEFAULT_LOG_LINES: Final[int] = 100
# Default row cap for CI run listings
CI_DEFAULT_LIST_LIMIT: Final[int] = 20

# ── CI review (card-triggered) ──
CI_REVIEW_MAX_CONCURRENT: Final[int] = 2  # Concurrent review cap; excess queues
CI_REVIEW_QUEUE_CAP: Final[int] = 64  # Bounded review queue (anti-blowup)
CI_REVIEW_MAX_FILES: Final[int] = 50  # Per-card changed-file cap for targeted gates
CI_REVIEW_TIMEOUT: Final[float] = 300.0  # Per-card gate pipeline total timeout (s)
CI_REVIEW_DEDUP_TTL: Final[float] = 3600.0  # card_id+state dedup window (s)
CI_REVIEW_PERSIST_FILE: Final[str] = "ci_reviews.jsonl"  # Report file (relative to data_dir)
CI_REVIEW_ARCHIVE_FONDS: Final[str] = "ci"  # R4 archive fonds
CI_REVIEW_ARCHIVE_SERIES: Final[str] = "reviews"
CI_REVIEW_AUTOTEST_CACHE_TTL: Final[float] = 300.0  # AutoTest L2 cache consume window (s)
CI_REVIEW_RUFF_CMD: Final[str] = "python -m ruff check {files}"
CI_REVIEW_MYPY_CMD: Final[str] = "python -m mypy {files}"
# Pytest command template for CI review gates
CI_REVIEW_PYTEST_CMD: Final[str] = "python -m pytest {files} -x -q"

# ── CI review control-plane permissions (per-surface write gates) ──
CI_CONTROL_API_WRITABLE: Final[bool] = True  # API surface may mutate ci.review.*
CI_CONTROL_SHELL_WRITABLE: Final[bool] = True  # L2 Shell surface may mutate ci.review.*


# ── LLM defaults (shared between L3 and L4) ──
LLM_DEFAULT_CONTEXT_WINDOW: Final[int] = 128000
LLM_PROBE_MAX_TOKENS: Final[int] = 5
# Minimum tool usage count to rank in searches
TOOL_SEARCH_MIN_COUNT: Final[int] = 10
# Max tool names returned per search
TOOL_SEARCH_MAX_RESULTS: Final[int] = 10
# Max tools offered per search result set
TOOL_SEARCH_MAX_TOOLS: Final[int] = 20
# Messages kept in the LLM context trail
CONTEXT_TRAIL_TRUNC: Final[int] = 30


# ── Sandbox defaults ──
SANDBOX_DEFAULT_TIMEOUT: Final[float] = 300.0


# ── LSP ──
LSP_PYTHON_EXT: Final[str] = ".py"


# ── Permission defaults ──
PERMISSION_DEFAULT_POLICY: Final[str] = "allow_all"
# Default Cell delegation policy (legacy). 'allow_all' = any Peer Agent can delegate any SubAgent.
# Master switch for subagent delegation support
GLOBAL_SUBAGENT_ENABLED: Final[bool] = False
# Global kill switch for all SubAgent delegation. False = all specs invisible system-wide.


# ── State file naming templates (format strings, not paths) ──
SANDBOX_STATE_TEMPLATE: Final[str] = "{cell_id}.state.json"
SNAPSHOT_PATH_TEMPLATE: Final[str] = "{snapshot_id}.snapshot.json"
# Filename template for skill lean-case traces
SKILL_LEAN_CASE_TEMPLATE: Final[str] = "{agent_id}_{tool_name}_{ts}.json"
# Filename template for agent session exports
AGENT_SESSION_TEMPLATE: Final[str] = "{ts}_{prefix}.json"


# ── Think quota (ThinkQuotaRegistry defaults) ──
THINK_BUDGET_GLOBAL_DEFAULT: Final[int] = 0
THINK_REASONING_DEFAULT: Final[str] = "none"


# ── Cell PMU (Performance Monitoring Unit) defaults ──
PMU_HISTORY_SIZE: Final[int] = 3600
PMU_SNAPSHOT_INTERVAL: Final[float] = 60.0
# PMU counter groups exposed in snapshots
PMU_COUNTER_GROUPS: Final[list[str]] = [
    "cards",
    "tools",
    "cache",
    "scouts",
    "bus",
    "token",
    "memory",
    "agent",
    "watchdog",
    "icache",
    "tlb",
    "interrupt",
]
PMU_QUERY_LIMIT: Final[int] = 100  # query_history() default limit
PMU_RATE_WINDOW: Final[float] = 60.0  # delta()/rate() default window (seconds)
PMU_RATE_MIN_SECONDS: Final[float] = 0.1  # rate() denominator floor


# ── Cell Watchdog defaults ──
CELL_WATCHDOG_POLL_INTERVAL: Final[float] = 5.0
CELL_WATCHDOG_DEFAULT_TIMEOUT: Final[float] = 30.0
# Unresponsive ticks before watchdog escalation
CELL_WATCHDOG_UNRESPONSIVE_ESCALATION: Final[int] = 3
# Seconds to wait for watchdog join on stop
CELL_WATCHDOG_STOP_JOIN_TIMEOUT: Final[float] = 5.0


# ── Cell component tuning ──
CELL_BUFFER_DEFAULT_MAXLEN: Final[int] = 50  # CircularBuffer() default capacity
CELL_CACHE_SEARCH_LIMIT: Final[int] = 10  # CellCache.search() default limit
CELL_CACHE_CONTEXT_MAX_TOKENS: Final[int] = 2048  # CellCache.get_cell_context() cap
CELL_MONITOR_EVENT_LIMIT: Final[int] = 50  # CellMonitor.get_events() default limit
TOKEN_CHARS_PER_TOKEN: Final[int] = 4  # len(text) // 4 char→token estimate
SESSION_MSG_OVERHEAD: Final[int] = 10  # per-message token overhead in projections
TOKEN_MERGER_INTERVAL: Final[float] = 60.0  # CellTokenMerger poll interval (seconds)
CELL_RING_NORMALIZE: Final[float] = 3.0  # ring / 3.0 scheduler weight normalization
SNAPSHOT_CACHE_KEY_LIMIT: Final[int] = 100  # card snapshot cache-keys cap
CROSS_REVIEW_TIMEOUT: Final[float] = 60.0  # blocking cross-review wait
SUBAGENT_ORCHESTRATE_VERIFY_TIMEOUT: Final[float] = 60.0  # scout verify wait in fork-join
CARD_DEFAULT_PRIORITY: Final[int] = 5  # default card priority
CARD_DEFAULT_SIZE: Final[str] = "large"  # default card size (large | disputed)
TOKEN_HISTORY_WINDOW_SECONDS: Final[int] = 300  # CentralCollector 5min buckets
TOKEN_HISTORY_MAX: Final[int] = 288  # 288 × 300s = 24h of buckets
TOKEN_HISTORY_SHOWN: Final[int] = 48  # last 4h shown in global_summary


# ── I-Cache (Instruction Cache) defaults ──
ICACHE_MAX_ENTRIES: Final[int] = 500
ICACHE_TTL: Final[float] = 3600.0  # 1 hour — instruction data changes slowly
ICACHE_LFU_DECAY: Final[float] = 0.95  # frequency counter decay per tick
ICACHE_DECAY_INTERVAL: Final[int] = 100  # decay frequencies every N cache accesses
ICACHE_SEARCH_LIMIT: Final[int] = 20  # ICache.search() default limit


# ── Discussion / convergence buffer ──
CONVERGENCE_BUFFER_SIZE: Final[int] = 100
# Max answers kept per-phase in CellAnswerRepo in-memory ring buffer.


# ── Context governance / compression thresholds ──
CONTEXT_PRESSURE_WARN: Final[float] = 0.60
CONTEXT_PRESSURE_MEDIUM: Final[float] = 0.80
# Context fill ratio triggering critical pressure
CONTEXT_PRESSURE_CRITICAL: Final[float] = 0.95
# Upper token bound for context building
CONTEXT_BUILD_MAX_TOKENS: Final[int] = 4096
# Lower token bound for context building
CONTEXT_BUILD_MIN_TOKENS: Final[int] = 1024

# ── MMU + TLB (Memory Management Unit) defaults ──
TLB_MAX_ENTRIES: Final[int] = 64
TLB_DEFAULT_RING: Final[int] = 1
# Ring clearance assumed when TLB lookup misses
TLB_CLEARANCE_FALLBACK: Final[int] = 1


# ── InterruptController (Priority Interrupt) defaults ──
IRQ_TABLE_SIZE: Final[int] = 32
IRQ_PRIORITY_LEVELS: Final[int] = 4  # NMI=0, HIGH=1, NORMAL=2, LOW=3
IRQ_DISPATCH_BATCH: Final[int] = 5  # max queued IRQ events dispatched per call


# ── StatsCenter (Unified Statistics Center) defaults ──
STATS_BUCKET_SIZE: Final[int] = 600  # seconds per bucket (10 min)
STATS_HISTORY_BUCKETS: Final[int] = 144  # 24h of buckets
STATS_SSE_BUFFER: Final[int] = 100  # max SSE events buffered per subscriber
STATS_DEFAULT_WINDOW: Final[str] = "5m"  # default query window
STATS_TOP_LIMIT: Final[int] = 10  # default row cap for cross-cell ranking
STATS_TIMELINE_LIMIT: Final[int] = 20  # l2 extra.py timeline query default
