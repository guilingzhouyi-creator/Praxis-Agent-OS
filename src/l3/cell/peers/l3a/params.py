"""L3A session system constants.

Limits are configurable via SettingsCenter (praxis.yaml / .praxis_settings.json).
Compile-time constants here serve only as structural defaults (identity, paths, sizes).
"""

from l1.kernel.params.agent import (
    L3A_AGENT_ID,
    L3A_MEMORY_RECALL_LIMIT,
    L3A_MEMORY_TYPE,
)

AGENT_ID = L3A_AGENT_ID
MEMORY_RECALL_LIMIT = L3A_MEMORY_RECALL_LIMIT
MEMORY_TYPE = L3A_MEMORY_TYPE

MANAGED_OUTPUT_MAX_BYTES: int = 50000
MANAGED_OUTPUT_DIR: str = "l3a_outputs"

INBOX_RING_TAG: str = "l3a_inbox"
INBOX_IMPORTANCE: float = 0.7

EPOCH_SNAPSHOT_KEY: str = "l3a_context_epoch"

SESSION_HISTORY_MAX_TOKENS: int = 32000
SESSION_HISTORY_TRUNC: int = 50

SID_LENGTH: int = 8
SESSION_ARCHIVE_TYPE: str = "l3a_session_archive"
FONDS: str = "AGENT:l3a"
SERIES: str = "l3a_session"

# ── SubAgent pool tuning ──
SA_MAX_WORKERS: int = 4
SA_CARD_PLANNER_MAX_STEPS: int = 8
SA_CARD_PLANNER_TIMEOUT: float = 60.0
SA_INVESTIGATOR_MAX_STEPS: int = 6
SA_INVESTIGATOR_TIMEOUT: float = 45.0
SA_DEFAULT_TIMEOUT: float = 30.0
SA_SPAWN_TID_LEN: int = 8

# ── SubAgent LLM defaults (fallback when ModelService unavailable) ──
SA_DEFAULT_MAX_TOKENS: int = 2048
SA_DEFAULT_TEMPERATURE: float = 0.3

# ── L3A session model defaults (compile-time fallback in L3AModelConfig) ──
L3A_MODEL_MAX_TOKENS: int = 4096
L3A_MODEL_TEMPERATURE: float = 0.7

# ── ManagedToolOutput spill truncation ratios ──
OUTPUT_SPILL_HEAD_DIVISOR: int = 2        # keep text[:max_bytes // 2]
OUTPUT_SPILL_TAIL_DIVISOR: int = 4        # keep text[-(max_bytes // 4):]

# ── Daemon ──
DAEMON_STOP_TIMEOUT: float = 5.0
DAEMON_TICK_INTERVAL: float = 60.0
IDLE_TIMEOUT_DEFAULT: float = 3600.0
MEMORY_MAX_TOKENS: int = 4096
CONTEXT_WINDOW_FALLBACK: int = 128000     # used when LLM port query fails

# ── API / Search ──
DEFAULT_SEARCH_LIMIT: int = 20

# ── Inbox ──
INBOX_RELOAD_LIMIT: int = 50

# ── Session paging / compression / limits ──
SESSION_PAGE_SIZE: int = 20                  # default page size for history paging
SESSION_COMPRESS_KEEP: int = 10              # keep_last default for compress()
SESSION_MEMORY_WINDOW_SECONDS: float = 3600.0  # memory_usage() aggregation window
SESSION_MAX_STEPS_UNLIMITED: int = 999999    # sentinel for "unlimited" step cap

# ── Reasoning trail (thinking-mode ingestion) ──
REASONING_TRAIL_MAX_TURNS: int = 8           # max thinking rounds folded into one memory entry
REASONING_TRAIL_IMPORTANCE: float = 0.6
