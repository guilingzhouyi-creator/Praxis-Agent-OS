"""L3A session system constants.

Limits are configurable via SettingsCenter (praxis.yaml / .praxis_settings.json).
Compile-time constants here serve only as structural defaults (identity, paths, sizes).
"""

from l1.kernel.params.agent import (
    L3A_AGENT_ID, L3A_MEMORY_RECALL_LIMIT, L3A_MEMORY_TYPE,
    DEFAULT_CELL_ID,
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

# ── Daemon ──
DAEMON_STOP_TIMEOUT: float = 5.0
DAEMON_TICK_INTERVAL: float = 60.0
IDLE_TIMEOUT_DEFAULT: float = 3600.0
MEMORY_MAX_TOKENS: int = 4096

# ── API / Search ──
DEFAULT_SEARCH_LIMIT: int = 20

# ── Inbox ──
INBOX_RELOAD_LIMIT: int = 50
