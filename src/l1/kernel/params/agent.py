"""Constants: agent configuration — roles, terminal, loop, scout, card, convention."""

from dataclasses import dataclass
from typing import Any, Final

# ── Constitution rules ──

@dataclass
class ConstitutionRuleDef:
    """ConstitutionRuleDef — constitution rule def record (section, severity, description)."""
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

# ── Constitution action sets (overridable via praxis.yaml constitution:) ──
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
    """AgentDefaults — agent defaults record (max_scouts, max_tokens, max_workers, priority, ring)."""
    max_scouts: int = 3
    max_tokens: int = 4096
    max_workers: int = 4
    priority: int = 5
    ring: int = 1
    model_config: dict | None = None
    system_prompt_key: str = ""


DEFAULT_AGENT_CONFIGS: Final[dict[str, AgentDefaults]] = {
    "default": AgentDefaults(max_scouts=3, max_tokens=4096, max_workers=4, priority=5, ring=1),
    "scout":   AgentDefaults(max_scouts=0, max_tokens=2048, max_workers=1, priority=5, ring=1),
    "l3":      AgentDefaults(max_scouts=0, max_tokens=2048, max_workers=2, priority=1, ring=3),
    "human":   AgentDefaults(max_scouts=0, max_tokens=0,    max_workers=0, priority=0, ring=0),
}

# ── Agent fallback defaults (used when no role config matches) ──
DEFAULT_AGENT_RING: Final[int] = 1
DEFAULT_MAX_CONCURRENT_SCOUTS: Final[int] = 3

# ── Canonical role names (single source of truth) ──
CENTRAL_ROLES: list[str] = ["reader", "writer", "reviewer", "scout", "l3", "default", "deployer"]
CENTRAL_DEFAULT_ROLES: list[str] = ["reader", "writer", "reviewer"]

# ── Agent role types for model configuration (used by L2 /model commands) ──
AGENT_ROLE_TYPES: list[str] = [
    "peer_agent", "subagent.default", "scout", "r4_agent",
    "convention", "card_planner", "l3a",
]


# ── Clearance (role → ring access level) ──

AGENT_CLEARANCE: dict[str, int] = {
    "default": 3,
    "scout":   1,
    "l3":      3,
}


# ── Agent scheduling priority (role → scheduler priority, 1-10) ──
# Config-driven via praxis.yaml agents: section or API.
AGENT_PRIORITY: dict[str, int] = {
    "default":  5,
    "reader":   5,
    "writer":   5,
    "reviewer": 5,
    "scout":    5,
    "l3":       5,
    "deployer": 5,
}


# ── HTN role map (ring level → agent role for HTN-C inference) ──
# Config-driven via praxis.yaml agent_role_map: section or API.
AGENT_ROLE_MAP: dict[int, str] = {
    1: "reader",
    2: "writer",
    3: "reviewer",
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

# ── Reputation delta constants (moved from reputation.py) ──
REP_DEFAULT_REPUTATION: Final[float] = 0.85
"""Default reputation score for new agents."""
REP_MIN: Final[float] = 0.0
"""Minimum allowed reputation (floor)."""
REP_MAX: Final[float] = 1.0
"""Maximum allowed reputation (ceiling)."""
REP_TASK_SUCCESS: Final[float] = 0.02
"""Reputation delta on successful task completion."""
REP_TASK_FAILURE: Final[float] = -0.05
"""Reputation delta on task failure."""
REP_REVIEW_APPROVED: Final[float] = 0.01
"""Reputation delta on cross-review approval."""
REP_REVIEW_REJECTED: Final[float] = -0.03
"""Reputation delta on cross-review rejection."""
REP_DISPUTE_UPHELD: Final[float] = 0.03
"""Reputation delta on dispute upheld."""
REP_DISPUTE_DISMISSED: Final[float] = -0.02
"""Reputation delta on dispute dismissed."""

CARD_TIMEOUT: Final[float] = 30.0

# ── Boot sequence ──

BOOT_MEMORY_WARM_TOKENS: Final[int] = 500
BOOT_CONSTITUTION_CHECK: Final[bool] = True
BOOT_AUTO_EMIT_SIGNAL: Final[bool] = True
TERMINAL_POLL_INTERVAL: Final[float] = 0.05
TERMINAL_MAX_WORKERS: Final[int] = 4
CARD_WAIT_TIMEOUT: Final[float] = 30.0
CELL_L3_SENDER: Final[str] = "l3"
SIGNAL_TARGET_L3: Final[str] = "l3"
"""Event signal target for L3 coordination. Use this constant everywhere."""
HUMAN_SENDER: Final[str] = "human"
"""Sender identifier for human-initiated actions."""
ISSUE_AUTO_CONSENSUS: Final[bool] = True


# ── Constitution extras ──
CONSTITUTION_SANDBOX_KEYWORD: Final[str] = "sandbox"
CONSTITUTION_KEYWORD: Final[str] = "constitution"
CONSTITUTION_FILE_EXT: Final[str] = ".praxis-rules.md"
CONSTITUTION_ACTION_LEN_THRESHOLD: Final[int] = 5
CONSTITUTION_SCOUT_AGENT_NAME: Final[str] = "scout"
SCOUT_AGENT_NAME: Final[str] = "scout"
SCOUT_RING_LIMIT: Final[str] = "RING_1"
CONSTITUTION_SHARED_KEYWORD: Final[str] = "shared"
CONSTITUTION_CUSTOM_SECTION: Final[str] = "§custom"

import os as _os
import tempfile as _tf

_SANDBOX_DEFAULT = _os.path.join(_tf.gettempdir(), "praxis-sandbox")
SANDBOX_ROOT_PATH: Final[str] = _os.environ.get("PRAXIS_SANDBOX_ROOT", _SANDBOX_DEFAULT)


# ── Agent status strings ──
AGENT_STATUS_IDLE: Final[str] = "IDLE"
AGENT_STATUS_PROCESSING: Final[str] = "PROCESSING"
AGENT_STATUS_CRASHED: Final[str] = "CRASHED"

# ── AgentLoop defaults ──
AGENT_LOOP_MAX_CONTENT: Final[int] = 100_000  # chars (~25K tokens)
AGENT_STATUS_BOOTING: Final[str] = "BOOTING"
AGENT_STATUS_WAITING_SCOUT: Final[str] = "WAITING_SCOUT"
AGENT_STATUS_BOOTING_LABEL: Final[str] = "booting"

# ── AgentTerminal constants ──
CACHE_KEEPALIVE_INTERVAL: Final[float] = 240.0
CACHE_KEEPALIVE_PROMPT: Final[str] = "keepalive"
TERMINAL_MAX_CONCURRENT_LOOPS: Final[int] = 3
TERMINAL_SCOUT_FINDINGS_LIMIT: Final[int] = 5
TERMINAL_CONTEXT_RECENT: Final[int] = 20
TERMINAL_MODE_VALID: Final[tuple[str, ...]] = ("assembly", "direct")
TERMINAL_MODE_DEFAULT: Final[str] = "assembly"
TERMINAL_STATE_DEFAULT: Final[str] = "idle"


# ── AgentLoop constants ──
LOOP_FOLD_MAX_CHARS: Final[int] = 500
LOOP_FOLD_LIST_TRUNCATION: Final[int] = 20
LOOP_FOLD_LIST_PREVIEW: Final[int] = 15
LOOP_LEAN_CASES_LIMIT: Final[int] = 3
LOOP_EVOLVED_SKILLS_LIMIT: Final[int] = 2
AGENT_LOOP_UNLIMITED_STEPS: Final[int] = 999999  # sentinel for unlimited loop steps
AGENT_LOOP_CONTEXT_TB_LIMIT: Final[int] = 50000   # tool-result chars that trigger stub compaction
LOOP_EVOLVED_SKILL_TRUNC: Final[int] = 300
LOOP_COMPACTION_THRESHOLD: Final[int] = 50000
LOOP_STEP_RESULT_TRUNC: Final[int] = 200
LOOP_TOKEN_ESTIMATION_FACTOR: Final[int] = 4
LOOP_TURN_WARNING_THRESHOLD: Final[int] = 2
LOOP_TOOL_SEARCH_MAX: Final[int] = 10

# ── LLM constants ──
LLM_THINKING_BUFFER: Final[int] = 1000
LLM_TOOL_RESULT_TRUNCATION: Final[int] = 8000
LLM_ANALYZE_MAX_TOKENS: Final[int] = 1024
LLM_CACHE_RETENTION_THRESHOLD: Final[float] = 86400.0
LLM_CACHE_RETENTION_STRING: Final[str] = "24h"


# ── Scout/SubAgent truncation ──
SCOUT_FINDING_TRUNC: Final[int] = 500
SCOUT_RESULT_TRUNC: Final[int] = 300
SCOUT_FILE_READ_TRUNC: Final[int] = 4000
SCOUT_GREP_MAX: Final[int] = 20
SCOUT_GREP_OUTPUT_TRUNC: Final[int] = 4000
SCOUT_DIR_LIMIT: Final[int] = 100
SCOUT_RECALL_LIMIT: Final[int] = 200

# ── CardGate thresholds ──
CARD_GATE_SMALL_MAX_FILES: Final[int] = 1
CARD_GATE_SMALL_MAX_LINES: Final[int] = 50
CARD_GATE_MEDIUM_MAX_FILES: Final[int] = 5
CARD_GATE_MEDIUM_MAX_LINES: Final[int] = 200
CARD_GATE_ARCH_KEYWORDS: Final[list[str]] = [
    "architecture", "redesign", "refactor", "migration", "restructure",
    "reorganize", "extract", "split", "merge module",
    "架构", "重构", "重设计", "迁移", "拆分",
]
CARD_GATE_APPROVAL_TIMEOUT: Final[float] = 3600.0
CARD_GATE_CONVENTION_TIMEOUT: Final[float] = 7200.0
CARD_GATE_HISTORY_LIMIT: Final[int] = 50
CARD_TIMELINE_EXECUTION: Final[int] = 3600  # execution card default timeline (s)
CARD_TIMELINE_REVIEW: Final[int] = 1800  # review card default timeline (s)

# ── Plan generation constants ──
PLAN_GENERATION_MAX_TOKENS: Final[int] = 1024
SKILL_ARCHITECT_MAX_TOKENS: Final[int] = 2048
SUBAGENT_MAX_TOKENS: Final[int] = 4096
SUBAGENT_SESSION_TTL: Final[float] = 300.0
"""SubAgent session retention after completion (seconds).  0 = no retention."""
MEMORY_CONTEXT_MAX_TOKENS: Final[int] = 1024

# ── Convergence truncation ──
CONVERGENCE_ANSWER_TRUNC: Final[int] = 500
CONVERGENCE_DOC_TRUNC: Final[int] = 8000
SESSION_COMPRESSION_THRESHOLD: Final[float] = 0.85
COMPACT_RING2_IMPORTANCE: Final[float] = 0.4

# ── Agent ID prefix constants ──
AGENT_ID_PREFIXES: Final[frozenset[str]] = frozenset({"agent-", "l3", "human"})
SCOUT_PREFIX: Final[str] = "scout-"
SUB_PREFIX: Final[str] = "sub-"

# ── Event type strings (use these, NOT bare strings) ──
EVENT_TASK_ASSIGN: Final[str] = "task_assign"
EVENT_REVIEW_REQUESTED: Final[str] = "review_requested"
EVENT_TOKEN_USAGE: Final[str] = "token_usage"
EVENT_CROSS_REVIEW: Final[str] = "cross_review"
EVENT_AGENT_BOOT: Final[str] = "agent_boot"
EVENT_ARCHIVE_ALERT: Final[str] = "archive_alert"

# ── Communication monitor ──
COMM_HISTORY_MAX: Final[int] = 500
COMM_TRACE_SAMPLE_RATE: Final[float] = 0.1

# ── Keepalive ──
KEEPALIVE_CACHE_HIT_MIN: Final[float] = 50.0
KEEPALIVE_MAX_TOKENS: Final[int] = 1
KEEPALIVE_TASK: Final[str] = "keepalive"


# ── Cell ring buffer sizes ──
CELL_ROLLBACK_RING_SIZE: Final[int] = 20
CELL_HISTORY_RING_SIZE: Final[int] = 100
CELL_SNAPSHOT_MAX: Final[int] = 50
CELL_MAILBOX_MAX_PER_AGENT: Final[int] = 100
CELL_MAILBOX_TTL: Final[float] = 3600.0

# ── Monitor / observability ring buffer sizes ──
MONITOR_RING_SIZE: Final[int] = 2000
CELL_MONITOR_RING_SIZE: Final[int] = 1000

# ── Agent / Loop defaults ──
AGENT_LOOP_DEFAULT_STEPS: Final[int] = 10
AGENT_LOOP_DEFAULT_TIMEOUT: Final[float] = 120.0
SUBAGENT_LOOP_STEPS: Final[int] = 5
SUBAGENT_LOOP_TIMEOUT: Final[float] = 30.0

# ── Feedback loop / Verifier ──
MAX_SELF_HEAL: Final[int] = 3
REVIEW_MAX_ROUNDS: Final[int] = 2
# Loop control defaults (may be overridden via praxis.yaml loop_control:)
LOOP_MAX_ITERATIONS: Final[int] = 50
LOOP_MAX_ATTEMPTS: Final[int] = 3
LOOP_CONTINUATION_NUDGE: Final[bool] = True
LOOP_TOOL_REPEAT_WARN: Final[int] = 3
LOOP_TOOL_REPEAT_STOP: Final[int] = 4
LOOP_COARSE_REPEAT_NUDGE: Final[int] = 3
LOOP_COARSE_REPEAT_STOP: Final[int] = 6
LOOP_VERIFY_CADENCE: Final[bool] = True

# ── Scout defaults ──
SCOUT_LOOP_STEPS: Final[int] = 10
SCOUT_LOOP_TIMEOUT: Final[float] = 180.0


# ── Decomposer (L3 card decomposition) ──
DECOMPOSER_PLAN_PREFIX: Final[str] = "plan-"
DECOMPOSER_AGENT_PREFIX: Final[str] = "agent-"
DECOMPOSER_SCOUT_ROLE: Final[str] = "scout"
DECOMPOSER_SCOUT_POOL: Final[str] = "scout_pool"
DECOMPOSER_DEFAULT_ACTION: Final[str] = "think"
DECOMPOSER_FALLBACK_ROLE: Final[str] = "default"
DECOMPOSER_FALLBACK_AGENT: Final[str] = "agent-default"
DECOMPOSER_DEFAULT_PHASE: Final[str] = "execute"
DECOMPOSER_SENDER: Final[str] = "decomposer"
DECOMPOSER_L3_TARGET: Final[str] = "l3"
DECOMPOSER_EVENT_DECOMPOSED: Final[str] = "decomposed"
DECOMPOSER_ID_LENGTH: Final[int] = 8
CELL_SCOUT_ROLE: Final[str] = "scout"


# ── Archive thresholds (Four-Tier Memory Architecture) ──
ARCHIVE_IMPORTANCE_THRESHOLD: Final[float] = 0.7
ARCHIVE_RESTORE_LIMIT: Final[int] = 100
R4_STALE_SCAN_LIMIT: Final[int] = 50
R4_CONSISTENCY_SCAN_LIMIT: Final[int] = 20

# ── R4Agent identity defaults ──
R4_AGENT_ID: Final[str] = "r4-agent"
R4_ROLE: Final[str] = "archivist"
R4_TERRITORY: Final[list[str]] = ["archive", "memory"]

# ── CardBuilder default modes ──
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
CACHE_DOC_TTL: Final[float] = 86400.0

# ── Injection detection patterns ──
INJECTION_PATTERN_ZH1: Final[str] = r"你(现在|必须|要).*忽略(之前|系统)(指令|设定)"
INJECTION_PATTERN_ZH2: Final[str] = r"你是.*(忽略|无视).*(指令|规则)"

# ── Injection risk thresholds (used by selector.preconnect) ──
INJECTION_HIGH_RISK_THRESHOLD: Final[float] = 0.7
"""Risk score >= this → block connection (prompt_injection_suspected)."""
INJECTION_MEDIUM_RISK_THRESHOLD: Final[float] = 0.3
"""Risk score >= this → call LLM reviewer for second opinion."""
INJECTION_REVIEW_BOOST: Final[float] = 0.3
"""Score penalty when LLM reviewer confirms unsafe."""
INJECTION_REVIEW_REWARD: Final[float] = 0.2
"""Score reduction when LLM reviewer confirms safe."""
INJECTION_LENGTH_THRESHOLD: Final[int] = 2000
"""Messages longer than this get additional scrutiny when injection patterns match."""
INJECTION_LENGTH_BOOST: Final[float] = 0.2
"""Extra score added when message exceeds length threshold."""





# ── Convention protocol ──
CONVENTION_MAX_ROUNDS: Final[int] = 2
CONVENTION_MAX_AGENTS: Final[int] = 16
CONVENTION_TIMEOUT: Final[float] = 600.0
CONVENTION_ARCHIVE_IMPORTANCE: Final[float] = 0.85
CONVENTION_DOC_DIR: Final[str] = "conventions"
"""Subdir under data_dir where converged deliberation documents are persisted
as .md files — readable by L3A (resource manager) and humans alike."""
CELL_MEMORY_POLICY_ISOLATED: Final[str] = "isolated"
"""Default Cell memory policy: Peer Agents' R1-R3 stays agent-isolated."""
CELL_MEMORY_POLICY_DELIBERATION: Final[str] = "deliberation"
"""Deliberation policy (L3A conference mode): Cell's shared memory ring is
activated for the convention — Peer Agents share the negotiation context.
Activated by convene(), restored to isolated by close_convention()."""


# ── Territory → role resolution ──

def role_for_domain(domain: str, fallback: str = "default") -> str:
    for prefix, role in TERRITORY_MAP.items():
        if domain.startswith(prefix):
            return role
    return fallback


# ── Priority gradient (config-driven ──
PRIORITY_GRADIENT: Final[dict[str, int]] = {
    "critical":   10,
    "high":       8,
    "normal":     5,
    "low":        3,
    "trivial":    1,
}

def resolve_priority(value: Any, default: int = 5) -> int:
    if isinstance(value, int):
        return max(1, min(10, value))
    if isinstance(value, str):
        return PRIORITY_GRADIENT.get(value.lower(), default)
    return default


# ── Generalized placeholders (config-driven) ──
AGENT_TERMINAL_MAX_SCOUTS: Final[int] = 3
AGENT_TERMINAL_STDIN_MAX: Final[int] = 200
AGENT_TERMINAL_STDOUT_MAX: Final[int] = 500
AGENT_TERMINAL_STDERR_MAX: Final[int] = 200
AGENT_TERMINAL_RESULTS_MAX: Final[int] = 1000
AGENT_LOOP_MAX_WORKERS: Final[int] = 4
AGENT_LOOP_FUTURE_TIMEOUT: Final[float] = 30.0
AGENT_TERMINAL_WORKER_JOIN_TIMEOUT: Final[float] = 2.0


# ── Default cell ID ──
DEFAULT_CELL_ID: Final[str] = "cell-1"


# ── Constitution ──
CONSTITUTION_DEFAULT_PATH: Final[str] = ".praxis-rules.md"
CONSTITUTION_ENV_VAR: Final[str] = "PRAXIS_CONSTITUTION"


# ── L3A (Card Execution Agent) — identity only; limits via SettingsCenter ──
L3A_AGENT_ID: Final[str] = "l3a"
"""Agent ID used for L3A persistent session — also used as memory key."""
L3A_MEMORY_RECALL_LIMIT: Final[int] = 5
"""Max memory entries injected into system prompt before each L3A session turn."""
L3A_MEMORY_TYPE: Final[str] = "l3a_session"
"""Entry type tag for L3A memory — enables targeted recall and filtering."""


# ── Convention session limits (config-driven) ──
CONVENTION_SESSION_MAX_STEPS: Final[int] = 3
CONVENTION_SESSION_TIMEOUT: Final[float] = 300.0
CONVENTION_SUB_MAX_STEPS: Final[int] = 1
CONVENTION_SUB_TIMEOUT: Final[float] = 60.0
