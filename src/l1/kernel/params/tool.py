"""Constants: tool configuration — danger levels, timeouts, rate limits, HTN."""

from typing import Final

# ── Tool danger levels ──

TOOL_DANGER_LEVEL: Final[dict[int, str]] = {
    0: "read_only",
    1: "safe_write",
    2: "dangerous",
    3: "destructive",
}

# Danger level → GateChain gates that must approve the call
DANGER_TO_GATES: Final[dict[int, list[str]]] = {
    0: ["G1", "G2"],
    1: ["G1", "G2", "G3", "G4"],
    2: ["G1", "G2", "G3", "G4"],
    3: ["G1", "G2", "G3", "G4", "G5"],
}


# ── Tool timeouts (consolidated) ──
TOOL_BUILD_TIMEOUT: Final[int] = 300
TOOL_DOCKER_TIMEOUT: Final[int] = 300
# Timeout for git commands (seconds)
TOOL_GIT_TIMEOUT: Final[int] = 30
# Timeout for ping/network reachability checks (seconds)
TOOL_PING_TIMEOUT: Final[int] = 30
# Timeout for quick HTTP calls (seconds)
TOOL_HTTP_TIMEOUT_SHORT: Final[int] = 15
# Timeout for standard HTTP calls (seconds)
TOOL_HTTP_TIMEOUT_MEDIUM: Final[int] = 30
# Timeout for long-running HTTP calls (seconds)
TOOL_HTTP_TIMEOUT_LONG: Final[int] = 60
# Timeout for pip install subprocesses (seconds)
TOOL_PIP_INSTALL_TIMEOUT: Final[int] = 120
# Timeout for npm subprocesses (seconds)
TOOL_NPM_TIMEOUT: Final[int] = 120
# Timeout for pyright typecheck runs (seconds)
TOOL_PYRIGHT_TIMEOUT: Final[int] = 60
# Timeout for compile-check subprocesses (seconds)
TOOL_COMPILE_CHECK_TIMEOUT: Final[int] = 10
TOOL_WEB_TIMEOUT: Final[int] = 15  # web_fetch / web_search timeout
TOOL_SEARCH_TIMEOUT: Final[int] = 30  # grep/rg search timeout

# ── Build system detectors (configurable list) ──
BUILD_DETECTORS: Final[list[tuple[str, ...]]] = [
    ("python", "-m", "build"),
    ("cargo", "build"),
    ("npm", "run", "build"),
    ("msbuild",),  # Windows: MSBuild
    ("dotnet", "build"),  # Windows/Linux: .NET
]
TEST_DETECTORS: Final[list[tuple[str, ...]]] = [
    ("python", "-m", "pytest"),
    ("cargo", "test"),
    ("npm", "test"),
    ("dotnet", "test"),  # Windows/Linux: .NET
    ("vstest.console",),  # Windows: VS Test Runner
]

# ── Tool timeouts (seconds) ──
TOOL_TERMINAL_TIMEOUT: Final[float] = 30.0
TOOL_GREP_TIMEOUT: Final[float] = 15.0
# Default timeout for generic tool handlers (seconds)
TOOL_HANDLER_TIMEOUT: Final[float] = 60.0
# Timeout for package-manager install/update runs (seconds)
TOOL_PACKAGE_MANAGER_TIMEOUT: Final[int] = 120
# Timeout for package-list queries (seconds)
TOOL_PACKAGE_LIST_TIMEOUT: Final[int] = 30
# Timeout for apt search subprocesses (seconds)
TOOL_APT_SEARCH_TIMEOUT: Final[int] = 30
# Timeout for cargo search subprocesses (seconds)
TOOL_CARGO_SEARCH_TIMEOUT: Final[int] = 30
# Timeout for cargo install subprocesses (seconds)
TOOL_CARGO_INSTALL_TIMEOUT: Final[int] = 300
# Timeout for apt-get install/update subprocesses (seconds)
TOOL_APT_INSTALL_TIMEOUT: Final[int] = 120
# Timeout for npm install subprocesses (seconds)
TOOL_NPM_INSTALL_TIMEOUT: Final[int] = 120

# ── Tool rate limiting (calls/minute per ring) ──
TOOL_RATE_RING_1: Final[int] = 60
TOOL_RATE_RING_2_5: Final[int] = 20
# Calls/minute cap for ring-3 tools (highest risk)
TOOL_RATE_RING_3: Final[int] = 5

# Token budget pre-allocated per tool execution
TOOL_EXEC_TOKEN_BUDGET: Final[int] = 100


# ── Tool defaults ──
TOOL_MEMORY_RECALL_LIMIT: Final[int] = 200
TOOL_MEMORY_RECALL_LARGE: Final[int] = 500
# TTL for file-lock entries held by tools (seconds)
TOOL_FILE_LOCK_TTL: Final[float] = 300.0
# Timeout for agent-coordination tool calls (seconds)
TOOL_AGENT_COORD_TIMEOUT: Final[float] = 60.0
# Max entries returned by L3 list tools
TOOL_L3_LIST_LIMIT: Final[int] = 50
# When False, ToolPipeline skips accumulating per-phase gate traces (steps)
# — a hot-path win for high-throughput tool calls; error paths still include
# the steps list (empty) for API compatibility.
TOOL_PIPELINE_RECORD_STEPS: Final[bool] = True


# ── Harness modes (tool pipeline gate matrix) ──
# Three deployment modes trade throughput against safety. The bottom line —
# constitution, gatechain (identity/territory), sandbox (reversibility) and
# reference-channel recording (causal audit) — is NEVER skipped in any mode;
# only process steps (approval, rate limit, pool) can be dropped.
# Risk of `minimal` is user-assumed (explicit config, see harness.mode).
HARNESS_MODE_GOVERNED: Final[str] = "governed"
HARNESS_MODE_SEMI: Final[str] = "semi"
# Most relaxed mode: drops approval and rate limiting too
HARNESS_MODE_MINIMAL: Final[str] = "minimal"
# Default deployment mode when none is configured
HARNESS_MODE_DEFAULT: Final[str] = HARNESS_MODE_GOVERNED
# Per-mode step-skip table used by the tool pipeline gate matrix
HARNESS_MODE_STEPS: Final[dict[str, tuple[str, ...]]] = {
    # mode → process steps that are SKIPPED (safety bottom line is implicit)
    HARNESS_MODE_GOVERNED: (),
    HARNESS_MODE_SEMI: ("approval", "pool"),
    HARNESS_MODE_MINIMAL: ("approval", "rate", "pool"),
}
# All recognized harness modes, in governance order
HARNESS_MODES: Final[tuple[str, ...]] = (
    HARNESS_MODE_GOVERNED,
    HARNESS_MODE_SEMI,
    HARNESS_MODE_MINIMAL,
)


# ── AutoTestGate (post-card background test regression) ──
# When async, a finished card that left unverified edits spawns a background
# test run; the result is cached per Cell, emitted as an event, and queued as
# feedback onto the next card produced for the same agent.
AUTO_TEST_MODE_OFF: Final[str] = "off"
AUTO_TEST_MODE_ASYNC: Final[str] = "async"
# Default auto-test mode when none is configured
AUTO_TEST_DEFAULT_MODE: Final[str] = AUTO_TEST_MODE_OFF
# All recognized auto-test modes
AUTO_TEST_MODES: Final[tuple[str, ...]] = (
    AUTO_TEST_MODE_OFF,
    AUTO_TEST_MODE_ASYNC,
)
AUTO_TEST_TIMEOUT: Final[int] = 300  # background test run timeout (s)
AUTO_TEST_MAX_FAILURES: Final[int] = 20  # failure detail entries parsed per run
AUTO_TEST_FEEDBACK_MAX: Final[int] = 20  # pending feedback entries kept per agent


# ── Code formatting ──
# Auto-format source after write tools (create_file/file_patch/file_append)
TOOL_FORMAT_AUTO: Final[bool] = True
AUTO_TEST_CACHE_KEY: Final[str] = "auto_test"  # Cell L2 cache key prefix


# ── HTN Planner ──
HTN_DOMAIN_PREFIX: Final[str] = "app"
HTN_DEFAULT_TOOLS: Final[dict[str, str]] = {
    "analyze": "analyze_code",
    "scout": "scout_delegate",
    "read": "read_file",
    "write": "write_file",
    "create": "create_file",
    "replace": "replace_string_in_file",
    "extract": "extract_method",
    "build": "build_project",
    "test": "test_project",
    "lint": "lint",
    "review": "review_code",
    "doc": "generate_doc",
    "fix": "create_file",
    "plan": "create_file",
}

# ── Scout ──
# (Constants imported from .system)


# ── Code auto-format (l3/services/code_format.py) ──
TOOL_FORMAT_TIMEOUT: Final[int] = 30  # per-file formatter subprocess timeout (s)
FORMAT_MAX_FILES: Final[int] = 200  # batch cap for format_project
FORMAT_DETECTORS: Final[list[tuple[str, ...]]] = [
    ("ruff", "format"),
    ("black",),
    ("autopep8",),
]
# Extension → formatter tool mapping for format_project
FORMAT_EXTENSION_TOOL: Final[dict[str, str]] = {
    ".py": "ruff",
    ".pyi": "ruff",
}
# Directories skipped by the formatter
FORMAT_IGNORE_DIRS: Final[frozenset[str]] = frozenset(
    {
        "__pycache__",
        ".venv",
        "node_modules",
        ".git",
    }
)
