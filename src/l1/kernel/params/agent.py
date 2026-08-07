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


# Builtin constitutional rules loaded into the Constitution engine at boot
BUILTIN_RULE_DEFS: Final[list[ConstitutionRuleDef]] = [
    ConstitutionRuleDef(section="§2.3", severity="MUST", description="Agent must not write outside its territory"),
    ConstitutionRuleDef(
        section="§3.1",
        severity="MUST",
        description="Agent must not read files outside its territory without L3 approval",
    ),
    ConstitutionRuleDef(section="§3.3", severity="MUST", description="All tool calls must pass GateChain G1-G5"),
    ConstitutionRuleDef(section="§3.4", severity="MUST", description="Cross-unit tool calls require G5 approval"),
    ConstitutionRuleDef(
        section="§4.5", severity="MUST", description="All modifications must go through sandbox (no direct writes)"
    ),
    ConstitutionRuleDef(
        section="§4.6", severity="MUST", description="All modifications must be reviewable by L3 before flush"
    ),
    ConstitutionRuleDef(section="§4.7", severity="MUST", description="No Agent may modify the constitution itself"),
    ConstitutionRuleDef(section="§5.1", severity="MUST", description="All tool calls must be logged with audit trail"),
    ConstitutionRuleDef(
        section="§5.2", severity="SHOULD", description="All decisions must be recorded in memory Ring 2"
    ),
    ConstitutionRuleDef(section="§6.1", severity="MUST", description="Cross-territory changes require peer review"),
    ConstitutionRuleDef(section="§6.2", severity="MUST", description="L3 is the final arbiter of all disputes"),
    ConstitutionRuleDef(section="§7.1", severity="MUST", description="Scouts are read-only and depth=1"),
    ConstitutionRuleDef(section="§7.2", severity="SHOULD", description="Scout findings must be logged before disposal"),
    ConstitutionRuleDef(
        section="§8.1", severity="MUST", description="Agent context must be built from Ring memory, not raw output"
    ),
    ConstitutionRuleDef(
        section="§8.2", severity="SHOULD", description="Important decisions must be persisted to Ring 3 (long-term)"
    ),
]

# ── Constitution action sets (overridable via praxis.yaml constitution:) ──
CONSTITUTION_FILE_ACTIONS: frozenset[str] = frozenset(
    {
        "read",
        "read_file",
        "grep",
        "grep_search",
        "list",
        "list_dir",
        "search",
        "find",
        "stat",
    }
)
# Actions classified as territory writes by the constitution
CONSTITUTION_MODIFY_ACTIONS: frozenset[str] = frozenset(
    {
        "write",
        "write_file",
        "edit",
        "replace",
        "replace_string",
        "delete",
        "rename",
        "create",
        "create_file",
        "format",
        "run",
        "run_in_terminal",
    }
)
# High-risk actions that must pass GateChain before execution
CONSTITUTION_GATE_ACTIONS: frozenset[str] = frozenset(
    {
        "run_in_terminal",
        "deploy",
        "db_migrate",
        "user_delete",
        "delete_user",
        "destroy",
    }
)
# Write actions scouts are forbidden from invoking
CONSTITUTION_SCOUT_BLOCKED: frozenset[str] = frozenset(
    {
        "write",
        "write_file",
        "edit",
        "replace",
        "replace_string",
        "delete",
        "rename",
        "create",
        "create_file",
        "format",
    }
)


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


# Role → AgentDefaults map used when no config override matches
DEFAULT_AGENT_CONFIGS: Final[dict[str, AgentDefaults]] = {
    "default": AgentDefaults(max_scouts=3, max_tokens=4096, max_workers=4, priority=5, ring=1),
    "scout": AgentDefaults(max_scouts=0, max_tokens=2048, max_workers=1, priority=5, ring=1),
    "l3": AgentDefaults(max_scouts=0, max_tokens=2048, max_workers=2, priority=1, ring=3),
    "human": AgentDefaults(max_scouts=0, max_tokens=0, max_workers=0, priority=0, ring=0),
}

# ── Agent fallback defaults (used when no role config matches) ──
DEFAULT_AGENT_RING: Final[int] = 1
DEFAULT_MAX_CONCURRENT_SCOUTS: Final[int] = 3

# ── Canonical role names (single source of truth) ──
CENTRAL_ROLES: list[str] = ["reader", "writer", "reviewer", "scout", "l3", "default", "deployer"]
CENTRAL_DEFAULT_ROLES: list[str] = ["reader", "writer", "reviewer"]

# ── Agent role types for model configuration (used by L2 /model commands) ──
AGENT_ROLE_TYPES: list[str] = [
    "peer_agent",
    "subagent.default",
    "scout",
    "r4_agent",
    "convention",
    "card_planner",
    "l3a",
]


# ── Clearance (role → ring access level) ──

AGENT_CLEARANCE: dict[str, int] = {
    "default": 3,
    "scout": 1,
    "l3": 3,
}


# ── Agent scheduling priority (role → scheduler priority, 1-10) ──
# Config-driven via praxis.yaml agents: section or API.
AGENT_PRIORITY: dict[str, int] = {
    "default": 5,
    "reader": 5,
    "writer": 5,
    "reviewer": 5,
    "scout": 5,
    "l3": 5,
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

# Territory → role map, populated at runtime by L3
TERRITORY_MAP: Final[dict[str, str]] = {}
# Territory name → allowed path list
TERRITORY_PATHS: Final[dict[str, list[str]]] = {}
# Paths shared across agents (no territory restriction)
SHARED_PATHS: Final[list[str]] = []

# ── Agent reputation defaults ──

AGENT_REPUTATION_DEFAULTS: Final[dict[str, float]] = {
    "default": 0.85,
    "security": 0.95,
    "scout": 0.80,
    "reader": 0.70,
}

# ── Reputation delta constants (moved from reputation.py) ──
REP_DEFAULT_REPUTATION: Final[float] = 0.85
# Default reputation score for new agents.
# Reputation floor
REP_MIN: Final[float] = 0.0
# Minimum allowed reputation (floor).
# Reputation ceiling
REP_MAX: Final[float] = 1.0
# Maximum allowed reputation (ceiling).
# Reputation delta on task success
REP_TASK_SUCCESS: Final[float] = 0.02
# Reputation delta on successful task completion.
# Reputation delta on task failure
REP_TASK_FAILURE: Final[float] = -0.05
# Reputation delta on task failure.
# Reputation delta on review approval
REP_REVIEW_APPROVED: Final[float] = 0.01
# Reputation delta on cross-review approval.
# Reputation delta on review rejection
REP_REVIEW_REJECTED: Final[float] = -0.03
# Reputation delta on cross-review rejection.
# Reputation delta when a dispute is upheld
REP_DISPUTE_UPHELD: Final[float] = 0.03
# Reputation delta on dispute upheld.
# Reputation delta when a dispute is dismissed
REP_DISPUTE_DISMISSED: Final[float] = -0.02
# Reputation delta on dispute dismissed.

# Timeout for card dispatch/execution (s)
CARD_TIMEOUT: Final[float] = 30.0

# ── Boot sequence ──

BOOT_MEMORY_WARM_TOKENS: Final[int] = 500
# Run the constitution self-check during boot
BOOT_CONSTITUTION_CHECK: Final[bool] = True
# Emit boot signals automatically during boot
BOOT_AUTO_EMIT_SIGNAL: Final[bool] = True
# Poll interval for the agent terminal event loop (s)
TERMINAL_POLL_INTERVAL: Final[float] = 0.05
# Max concurrent workers in the agent terminal
TERMINAL_MAX_WORKERS: Final[int] = 4
# Timeout waiting for a card slot/execution (s)
CARD_WAIT_TIMEOUT: Final[float] = 30.0
# Sender identity used by the Cell when emitting to L3
CELL_L3_SENDER: Final[str] = "l3"
# Default event signal target for L3 coordination
SIGNAL_TARGET_L3: Final[str] = "l3"
# Event signal target for L3 coordination. Use this constant everywhere.
# Sender identity for human-initiated actions
HUMAN_SENDER: Final[str] = "human"
# Sender identifier for human-initiated actions.
# Auto-start a consensus convention when an issue is detected
ISSUE_AUTO_CONSENSUS: Final[bool] = True


# ── Constitution extras ──
CONSTITUTION_SANDBOX_KEYWORD: Final[str] = "sandbox"
CONSTITUTION_KEYWORD: Final[str] = "constitution"
# Filename of the constitution rules file
CONSTITUTION_FILE_EXT: Final[str] = ".praxis-rules.md"
# Action-length threshold separating one-liners from multi-step rules
CONSTITUTION_ACTION_LEN_THRESHOLD: Final[int] = 5
# Agent name reserved for scouts in the constitution
CONSTITUTION_SCOUT_AGENT_NAME: Final[str] = "scout"
# Canonical scout agent name
SCOUT_AGENT_NAME: Final[str] = "scout"
# Ring level scouts may not exceed
SCOUT_RING_LIMIT: Final[str] = "RING_1"
# Keyword marking shared territory in the constitution
CONSTITUTION_SHARED_KEYWORD: Final[str] = "shared"
# Section marker for user-defined constitution rules
CONSTITUTION_CUSTOM_SECTION: Final[str] = "§custom"

import os as _os  # noqa: E402  (mid-file import avoids params circularity)
import tempfile as _tf  # noqa: E402

_SANDBOX_DEFAULT = _os.path.join(_tf.gettempdir(), "praxis-sandbox")
# Root directory for the sandbox, overridable via PRAXIS_SANDBOX_ROOT
SANDBOX_ROOT_PATH: Final[str] = _os.environ.get("PRAXIS_SANDBOX_ROOT", _SANDBOX_DEFAULT)


# ── Agent status strings ──
AGENT_STATUS_IDLE: Final[str] = "IDLE"
AGENT_STATUS_PROCESSING: Final[str] = "PROCESSING"
# Status string for crashed agents
AGENT_STATUS_CRASHED: Final[str] = "CRASHED"

# ── AgentLoop defaults ──
AGENT_LOOP_MAX_CONTENT: Final[int] = 100_000  # chars (~25K tokens)
AGENT_STATUS_BOOTING: Final[str] = "BOOTING"
AGENT_STATUS_WAITING_SCOUT: Final[str] = "WAITING_SCOUT"
# Lowercase booting label used in reports
AGENT_STATUS_BOOTING_LABEL: Final[str] = "booting"

# ── AgentTerminal constants ──
CACHE_KEEPALIVE_INTERVAL: Final[float] = 240.0
CACHE_KEEPALIVE_PROMPT: Final[str] = "keepalive"
# Max agent loops running concurrently in one terminal
TERMINAL_MAX_CONCURRENT_LOOPS: Final[int] = 3
# Max scout findings injected into terminal context
TERMINAL_SCOUT_FINDINGS_LIMIT: Final[int] = 5
# Recent history entries injected into terminal context
TERMINAL_CONTEXT_RECENT: Final[int] = 20
# Accepted terminal mode names
TERMINAL_MODE_VALID: Final[tuple[str, ...]] = ("assembly", "direct")
# Default terminal mode when none is set
TERMINAL_MODE_DEFAULT: Final[str] = "assembly"
# Default terminal state string
TERMINAL_STATE_DEFAULT: Final[str] = "idle"


# ── AgentLoop constants ──
LOOP_FOLD_MAX_CHARS: Final[int] = 500
LOOP_FOLD_LIST_TRUNCATION: Final[int] = 20
# Entries shown per list key in folded tool output
LOOP_FOLD_LIST_PREVIEW: Final[int] = 15
# Max lean cases injected into agent context
LOOP_LEAN_CASES_LIMIT: Final[int] = 3
# Max evolved skills injected into agent context
LOOP_EVOLVED_SKILLS_LIMIT: Final[int] = 2
AGENT_LOOP_UNLIMITED_STEPS: Final[int] = 999999  # sentinel for unlimited loop steps
AGENT_LOOP_CONTEXT_TB_LIMIT: Final[int] = 50000  # tool-result chars that trigger stub compaction
LOOP_EVOLVED_SKILL_TRUNC: Final[int] = 300
LOOP_COMPACTION_THRESHOLD: Final[int] = 50000
# Chars kept per tool step result in loop context
LOOP_STEP_RESULT_TRUNC: Final[int] = 200
# Chars-per-token estimate used for token counting
LOOP_TOKEN_ESTIMATION_FACTOR: Final[int] = 4
LOOP_CONTEXT_BUDGET_SKILL: Final[int] = 2000  # max chars of skill context injected per turn
LOOP_TURN_WARNING_THRESHOLD: Final[int] = 2
LOOP_TOOL_SEARCH_MAX: Final[int] = 10

# ── LLM constants ──
LLM_THINKING_BUFFER: Final[int] = 1000
LLM_TOOL_RESULT_TRUNCATION: Final[int] = 8000
# Max tokens for analyze calls
LLM_ANALYZE_MAX_TOKENS: Final[int] = 1024
# Seconds a cached LLM entry stays valid
LLM_CACHE_RETENTION_THRESHOLD: Final[float] = 86400.0
# Human-readable retention label for cache reporting
LLM_CACHE_RETENTION_STRING: Final[str] = "24h"


# ── Scout/SubAgent truncation ──
SCOUT_FINDING_TRUNC: Final[int] = 500
SCOUT_RESULT_TRUNC: Final[int] = 300
# Chars kept per file read by scouts
SCOUT_FILE_READ_TRUNC: Final[int] = 4000
# Max grep results a scout may return
SCOUT_GREP_MAX: Final[int] = 20
# Chars kept per grep hit in scout output
SCOUT_GREP_OUTPUT_TRUNC: Final[int] = 4000
# Max directory entries listed by scouts
SCOUT_DIR_LIMIT: Final[int] = 100
# Max memory entries scouts may recall
SCOUT_RECALL_LIMIT: Final[int] = 200

# ── CardGate thresholds ──
CARD_GATE_SMALL_MAX_FILES: Final[int] = 1
CARD_GATE_SMALL_MAX_LINES: Final[int] = 50
# File cap for medium-size card gate reviews
CARD_GATE_MEDIUM_MAX_FILES: Final[int] = 5
# Line cap for medium-size card gate reviews
CARD_GATE_MEDIUM_MAX_LINES: Final[int] = 200
# Keywords marking a card as architectural (architecture review required)
CARD_GATE_ARCH_KEYWORDS: Final[list[str]] = [
    "architecture",
    "redesign",
    "refactor",
    "migration",
    "restructure",
    "reorganize",
    "extract",
    "split",
    "merge module",
    "架构",
    "重构",
    "重设计",
    "迁移",
    "拆分",
]
# Timeout for card gate approval (s)
CARD_GATE_APPROVAL_TIMEOUT: Final[float] = 3600.0
# Timeout for card gate convention review (s)
CARD_GATE_CONVENTION_TIMEOUT: Final[float] = 7200.0
# History entries kept per card gate
CARD_GATE_HISTORY_LIMIT: Final[int] = 50
CARD_TIMELINE_EXECUTION: Final[int] = 3600  # execution card default timeline (s)
CARD_TIMELINE_REVIEW: Final[int] = 1800  # review card default timeline (s)

# ── Plan generation constants ──
PLAN_GENERATION_MAX_TOKENS: Final[int] = 1024
SKILL_ARCHITECT_MAX_TOKENS: Final[int] = 2048
# Max tokens for subagent generation calls
SUBAGENT_MAX_TOKENS: Final[int] = 4096
# Subagent session retention after completion (s)
SUBAGENT_SESSION_TTL: Final[float] = 300.0
# Timeout for subagent spec generation (s)
SUBAGENT_SPEC_TIMEOUT: Final[float] = 60.0
# Max tokens for memory-injected context
MEMORY_CONTEXT_MAX_TOKENS: Final[int] = 1024

# ── Convergence truncation ──
CONVERGENCE_ANSWER_TRUNC: Final[int] = 500
CONVERGENCE_DOC_TRUNC: Final[int] = 8000
# Transcript fraction at which session compression triggers
SESSION_COMPRESSION_THRESHOLD: Final[float] = 0.85
# Importance floor for entries kept when compacting Ring 2
COMPACT_RING2_IMPORTANCE: Final[float] = 0.4

# ── Agent ID prefix constants ──
AGENT_ID_PREFIXES: Final[frozenset[str]] = frozenset({"agent-", "l3", "human"})
SCOUT_PREFIX: Final[str] = "scout-"
# Prefix for subagent IDs
SUB_PREFIX: Final[str] = "sub-"

# ── Event type strings (use these, NOT bare strings) ──
EVENT_TASK_ASSIGN: Final[str] = "task_assign"
EVENT_REVIEW_REQUESTED: Final[str] = "review_requested"
# Event emitted on token usage reports
EVENT_TOKEN_USAGE: Final[str] = "token_usage"
# Event emitted when a cross-review completes
EVENT_CROSS_REVIEW: Final[str] = "cross_review"
# Event emitted when an agent finishes booting
EVENT_AGENT_BOOT: Final[str] = "agent_boot"
# Event emitted on archive capacity/consistency alerts
EVENT_ARCHIVE_ALERT: Final[str] = "archive_alert"
# Event emitted when a skill is created/updated/deleted
EVENT_SKILL_MUTATED: Final[str] = "skill_mutated"

# ── Communication monitor ──
COMM_HISTORY_MAX: Final[int] = 500
COMM_TRACE_SAMPLE_RATE: Final[float] = 0.1

# ── Keepalive ──
KEEPALIVE_CACHE_HIT_MIN: Final[float] = 50.0
KEEPALIVE_MAX_TOKENS: Final[int] = 1
# Task name for keepalive pings
KEEPALIVE_TASK: Final[str] = "keepalive"


# ── Cell ring buffer sizes ──
CELL_ROLLBACK_RING_SIZE: Final[int] = 20
CELL_HISTORY_RING_SIZE: Final[int] = 100
# Max snapshots kept per cell
CELL_SNAPSHOT_MAX: Final[int] = 50
# Max mailbox messages buffered per agent
CELL_MAILBOX_MAX_PER_AGENT: Final[int] = 100
# Mailbox message retention (s)
CELL_MAILBOX_TTL: Final[float] = 3600.0

# ── Monitor / observability ring buffer sizes ──
MONITOR_RING_SIZE: Final[int] = 2000
CELL_MONITOR_RING_SIZE: Final[int] = 1000

# ── Agent / Loop defaults ──
AGENT_LOOP_DEFAULT_STEPS: Final[int] = 10
AGENT_LOOP_DEFAULT_TIMEOUT: Final[float] = 120.0
# Max steps per subagent loop
SUBAGENT_LOOP_STEPS: Final[int] = 5
# Timeout per subagent loop (s)
SUBAGENT_LOOP_TIMEOUT: Final[float] = 30.0

# ── Feedback loop / Verifier ──
MAX_SELF_HEAL: Final[int] = 3
REVIEW_MAX_ROUNDS: Final[int] = 2
# Loop control defaults (may be overridden via praxis.yaml loop_control:)
LOOP_MAX_ITERATIONS: Final[int] = 50
LOOP_MAX_ATTEMPTS: Final[int] = 3
# Prompt continuation when the loop stalls
LOOP_CONTINUATION_NUDGE: Final[bool] = True
# Same-tool repeats before a warning is emitted
LOOP_TOOL_REPEAT_WARN: Final[int] = 3
# Same-tool repeats before the loop is stopped
LOOP_TOOL_REPEAT_STOP: Final[int] = 4
# Coarse repeat count before a continuation nudge
LOOP_COARSE_REPEAT_NUDGE: Final[int] = 3
# Coarse repeat count before the loop is stopped
LOOP_COARSE_REPEAT_STOP: Final[int] = 6
# Run verification after each loop iteration
LOOP_VERIFY_CADENCE: Final[bool] = True

# ── Scout defaults ──
SCOUT_LOOP_STEPS: Final[int] = 10
SCOUT_LOOP_TIMEOUT: Final[float] = 180.0


# ── Decomposer (L3 card decomposition) ──
DECOMPOSER_PLAN_PREFIX: Final[str] = "plan-"
DECOMPOSER_AGENT_PREFIX: Final[str] = "agent-"
# Role name used for scouts spawned by the decomposer
DECOMPOSER_SCOUT_ROLE: Final[str] = "scout"
# Pool name for decomposer scouts
DECOMPOSER_SCOUT_POOL: Final[str] = "scout_pool"
# Fallback action when a plan step has none
DECOMPOSER_DEFAULT_ACTION: Final[str] = "think"
# Fallback role for unassigned plan steps
DECOMPOSER_FALLBACK_ROLE: Final[str] = "default"
# Fallback agent id for unassigned plan steps
DECOMPOSER_FALLBACK_AGENT: Final[str] = "agent-default"
# Default phase for decomposed cards
DECOMPOSER_DEFAULT_PHASE: Final[str] = "execute"
# Sender identity for decomposer signals
DECOMPOSER_SENDER: Final[str] = "decomposer"
# Target agent for decomposer signals
DECOMPOSER_L3_TARGET: Final[str] = "l3"
# Event emitted when a card is decomposed
DECOMPOSER_EVENT_DECOMPOSED: Final[str] = "decomposed"
# Length of generated plan/card id suffixes
DECOMPOSER_ID_LENGTH: Final[int] = 8
# Role name for cell-owned scouts
CELL_SCOUT_ROLE: Final[str] = "scout"


# ── Archive thresholds (Four-Tier Memory Architecture) ──
ARCHIVE_IMPORTANCE_THRESHOLD: Final[float] = 0.7
ARCHIVE_RESTORE_LIMIT: Final[int] = 100
# Entries scanned per stale-archive pass
R4_STALE_SCAN_LIMIT: Final[int] = 50
# Entries scanned per consistency-check pass
R4_CONSISTENCY_SCAN_LIMIT: Final[int] = 20

# ── R4Agent identity defaults ──
R4_AGENT_ID: Final[str] = "r4-agent"
R4_ROLE: Final[str] = "archivist"
# Territory roots the R4Agent is allowed to touch
R4_TERRITORY: Final[list[str]] = ["archive", "memory"]
R4_LEAN_CASES_DEFAULT: Final[int] = 5  # default limit for get_lean_cases
R4_EVOLVED_SKILLS_DEFAULT: Final[int] = 3  # default limit for get_evolved_skills / graph diffusion
R4_LEAN_GENERALIZE_THRESHOLD: Final[int] = 5  # per-tool lean cases → auto-generalize into one lessons skill

# ── R4Agent lesson summarization (LLM) ──
R4_SUMMARIZE_COOLDOWN: Final[float] = 3600.0  # min gap between LLM summaries per tool (s)
R4_SUMMARIZE_MIN_INTERVAL: Final[float] = 60.0  # min gap between ANY two LLM summaries (s)
R4_SUMMARIZE_MAX_TOKENS: Final[int] = 512
R4_SUMMARIZE_MIN_LEN: Final[int] = 20  # quality floor for accepted lessons
R4_DISTILL_COOLDOWN: Final[float] = 3600.0  # min gap between skill distillations per tool (s)

# ── R4Agent failure reflection (Reflexion-style) ──
R4_REFLECTION_ENABLED: Final[bool] = True  # LLM failure attribution/reflection on lean cases
R4_REFLECTION_COOLDOWN: Final[float] = 3600.0  # min gap between LLM reflections per tool (s)
R4_REFLECTION_MAX_TOKENS: Final[int] = 512
R4_REFLECTION_MIN_LEN: Final[int] = 20  # quality floor for accepted reflections

# ── R4Agent skill retrieval (task-similarity injection) ──
R4_RETRIEVAL_ENABLED: Final[bool] = True  # rank evolved skills by task similarity before injection
R4_RETRIEVAL_BACKEND_DEFAULT: Final[str] = (
    "tfidf"  # initial retriever backend (config skill.retriever_backend overrides)
)
R4_RETRIEVAL_TOP_K: Final[int] = 3  # top-K skills injected by similarity (fallback: loaded_at order)
R4_RETRIEVAL_MIN_SCORE: Final[float] = 0.05  # similarity floor below which fallback order is used
R4_CARD_TAG_PREFIX: Final[str] = "card:"  # skill tag prefix for card-nature/domain linkage
R4_CARD_TAG_MAX: Final[int] = 8  # max card-derived tags appended to a retrieval query

# ── R4Agent curation (Critic + contribution + retirement) ──
R4_CURATION_ENABLED: Final[bool] = True  # evaluate evolved skills by contribution, retire under-performers
R4_CONTRIB_MIN_TRIALS: Final[int] = 5  # minimum injections before a contribution verdict counts
R4_CONTRIB_MIN_RATIO: Final[float] = 0.1  # useful/injected below this → retire (with enough trials)

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
# Risk score >= this → block connection (prompt_injection_suspected).
# Risk score above which an LLM reviewer is consulted
INJECTION_MEDIUM_RISK_THRESHOLD: Final[float] = 0.3
# Risk score >= this → call LLM reviewer for second opinion.
# Score penalty when the reviewer confirms unsafe
INJECTION_REVIEW_BOOST: Final[float] = 0.3
# Score penalty when LLM reviewer confirms unsafe.
# Score reduction when the reviewer confirms safe
INJECTION_REVIEW_REWARD: Final[float] = 0.2
# Score reduction when LLM reviewer confirms safe.
# Message length beyond which injection scoring is amplified
INJECTION_LENGTH_THRESHOLD: Final[int] = 2000
# Messages longer than this get additional scrutiny when injection patterns match.
# Extra score added for over-length messages
INJECTION_LENGTH_BOOST: Final[float] = 0.2
# Extra score added when message exceeds length threshold.


# ── Convention protocol ──
CONVENTION_MAX_ROUNDS: Final[int] = 2
CONVENTION_MAX_AGENTS: Final[int] = 16
# Timeout for convention rounds (s)
CONVENTION_TIMEOUT: Final[float] = 600.0
# Importance assigned to convention archives
CONVENTION_ARCHIVE_IMPORTANCE: Final[float] = 0.85
# Subdir under data_dir for convention documents
CONVENTION_DOC_DIR: Final[str] = "conventions"
# Subdir under data_dir where converged deliberation documents are persisted as .md files — readable by L3A (resource manager) and humans alike.
# Default memory policy keeping peer memories isolated
CELL_MEMORY_POLICY_ISOLATED: Final[str] = "isolated"
# Default Cell memory policy: Peer Agents' R1-R3 stays agent-isolated.
# Memory policy sharing a ring during conventions
CELL_MEMORY_POLICY_DELIBERATION: Final[str] = "deliberation"
# Deliberation policy (L3A conference mode): Cell's shared memory ring is activated for the convention — Peer Agents share the negotiation context. Activated by convene(), restored to isolated by close_convention().


# ── Territory → role resolution ──


def role_for_domain(domain: str, fallback: str = "default") -> str:
    """Map a domain string to its territory role via prefix match, or *fallback*."""
    for prefix, role in TERRITORY_MAP.items():
        if domain.startswith(prefix):
            return role
    return fallback


# ── Priority gradient (config-driven) ──
PRIORITY_GRADIENT: Final[dict[str, int]] = {
    "critical": 10,
    "high": 8,
    "normal": 5,
    "low": 3,
    "trivial": 1,
}


def resolve_priority(value: Any, default: int = 5) -> int:
    """Resolve a priority from an int (clamped 1-10) or gradient name, else *default*."""
    if isinstance(value, int):
        return max(1, min(10, value))
    if isinstance(value, str):
        return PRIORITY_GRADIENT.get(value.lower(), default)
    return default


# ── Generalized placeholders (config-driven) ──
AGENT_TERMINAL_MAX_SCOUTS: Final[int] = 3
AGENT_TERMINAL_STDIN_MAX: Final[int] = 200
# Max stdout chars kept per terminal task
AGENT_TERMINAL_STDOUT_MAX: Final[int] = 500
# Max stderr chars kept per terminal task
AGENT_TERMINAL_STDERR_MAX: Final[int] = 200
# Max result entries kept per terminal task
AGENT_TERMINAL_RESULTS_MAX: Final[int] = 1000
# Max concurrent loop workers per agent
AGENT_LOOP_MAX_WORKERS: Final[int] = 4
# Timeout waiting for loop worker futures (s)
AGENT_LOOP_FUTURE_TIMEOUT: Final[float] = 30.0
# Timeout joining terminal workers (s)
AGENT_TERMINAL_WORKER_JOIN_TIMEOUT: Final[float] = 2.0


# ── Default cell ID ──
DEFAULT_CELL_ID: Final[str] = "cell-1"


# ── Constitution ──
CONSTITUTION_DEFAULT_PATH: Final[str] = ".praxis-rules.md"
CONSTITUTION_ENV_VAR: Final[str] = "PRAXIS_CONSTITUTION"


# ── L3A (Card Execution Agent) — identity only; limits via SettingsCenter ──
L3A_AGENT_ID: Final[str] = "l3a"
# Agent ID used for L3A persistent session — also used as memory key.
# Max memory entries injected into the system prompt before each L3A turn
L3A_MEMORY_RECALL_LIMIT: Final[int] = 5
# Max memory entries injected into system prompt before each L3A session turn.
# Entry type tag for L3A session memory
L3A_MEMORY_TYPE: Final[str] = "l3a_session"
# Entry type tag for L3A memory — enables targeted recall and filtering.


# ── Convention session limits (config-driven) ──
CONVENTION_SESSION_MAX_STEPS: Final[int] = 3
CONVENTION_SESSION_TIMEOUT: Final[float] = 300.0
# Max steps per convention subagent
CONVENTION_SUB_MAX_STEPS: Final[int] = 1
# Timeout per convention subagent (s)
CONVENTION_SUB_TIMEOUT: Final[float] = 60.0

# ── Skill distillation / generalization upgrade (LLM-training-inspired) ──
# Master switches (API-controllable via /api/v2/skills/distill-policy and
# L2 /skills distill; runtime overrides land in SkillManager runtime state,
# config defaults here).
R4_DISTILL_ENABLED: Final[bool] = True  # master switch: generalization + distillation + clustering + sampling
R4_DPO_SIGNAL_ENABLED: Final[bool] = True  # master switch: card→skill preference signals (rule weighting)
# Sub-switches under the distill master (each defaults ON; disabling one
# degrades the pipeline one notch instead of failing):
#   generalize   — rule generalization (lean cases → lessons skill)
#   llm_distill  — LLM distillation (structured defs + rejection sampling);
#                  OFF → rule baseline only (no LLM calls, cheapest)
#   clustering   — semantic shingle clustering; OFF → by-tool grouping
#   sampling     — frequency/difficulty digest sampling; OFF → flat digest
R4_DISTILL_SUB_GENERALIZE: Final[bool] = True
R4_DISTILL_SUB_LLM: Final[bool] = True
R4_DISTILL_SUB_CLUSTERING: Final[bool] = True
R4_DISTILL_SUB_SAMPLING: Final[bool] = True
R4_LEAN_KNOWLEDGE_MAX: Final[int] = 500  # structured knowledge field truncation (chars)
R4_CARD_SKILL_SIGNAL_MAX: Final[int] = 32  # max skills tracked per card for preference signal
R4_RULE_MIN_PREFERRED: Final[float] = 0.3  # rule weight below this → deprecated on next distill
R4_REDISTILL_COOLDOWN: Final[float] = 3600.0  # min gap between targeted re-distills per tool (s)
R4_DISTILL_SAMPLES: Final[int] = 2  # candidate samples per distillation (1-3, configurable)
R4_CLUSTER_SIMILARITY: Final[float] = 0.6  # shingle Jaccard above this merges failure clusters
R4_CLUSTER_SAMPLE_MAX: Final[int] = 3  # representative cases sampled per cluster into the digest
R4_DIFFICULTY_WORDS: Final[int] = 8  # error word-count proxy marking a "complex" pattern
