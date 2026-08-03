"""Constants: tool configuration — danger levels, timeouts, rate limits, HTN."""

from typing import Final

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
TOOL_WEB_TIMEOUT: Final[int] = 15              # web_fetch / web_search timeout
TOOL_SEARCH_TIMEOUT: Final[int] = 30           # grep/rg search timeout

# ── Build system detectors (configurable list) ──
BUILD_DETECTORS: Final[list[tuple[str, ...]]] = [
    ("python", "-m", "build"),
    ("cargo", "build"),
    ("npm", "run", "build"),
    ("msbuild",),                 # Windows: MSBuild
    ("dotnet", "build"),          # Windows/Linux: .NET
]
TEST_DETECTORS: Final[list[tuple[str, ...]]] = [
    ("python", "-m", "pytest"),
    ("cargo", "test"),
    ("npm", "test"),
    ("dotnet", "test"),           # Windows/Linux: .NET
    ("vstest.console",),          # Windows: VS Test Runner
]

# ── Tool timeouts (seconds) ──
TOOL_TERMINAL_TIMEOUT: Final[float] = 30.0
TOOL_GREP_TIMEOUT: Final[float] = 15.0
TOOL_HANDLER_TIMEOUT: Final[float] = 60.0
TOOL_PACKAGE_MANAGER_TIMEOUT: Final[int] = 120
TOOL_PACKAGE_LIST_TIMEOUT: Final[int] = 30
TOOL_APT_SEARCH_TIMEOUT: Final[int] = 30
TOOL_CARGO_SEARCH_TIMEOUT: Final[int] = 30
TOOL_CARGO_INSTALL_TIMEOUT: Final[int] = 300
TOOL_APT_INSTALL_TIMEOUT: Final[int] = 120
TOOL_NPM_INSTALL_TIMEOUT: Final[int] = 120

# ── Tool rate limiting (calls/minute per ring) ──
TOOL_RATE_RING_1: Final[int] = 60
TOOL_RATE_RING_2_5: Final[int] = 20
TOOL_RATE_RING_3: Final[int] = 5

# Token budget pre-allocated per tool execution
TOOL_EXEC_TOKEN_BUDGET: Final[int] = 100


# ── Tool defaults ──
TOOL_MEMORY_RECALL_LIMIT: Final[int] = 200
TOOL_MEMORY_RECALL_LARGE: Final[int] = 500
TOOL_FILE_LOCK_TTL: Final[float] = 300.0
TOOL_AGENT_COORD_TIMEOUT: Final[float] = 60.0
TOOL_L3_LIST_LIMIT: Final[int] = 50


# ── HTN Planner ──
HTN_DOMAIN_PREFIX: Final[str] = "app"
HTN_DEFAULT_TOOLS: Final[dict[str, str]] = {
    "analyze": "analyze_code", "scout": "scout_delegate", "read": "read_file",
    "write": "write_file", "create": "create_file", "replace": "replace_string_in_file",
    "extract": "extract_method", "build": "build_project", "test": "test_project",
    "lint": "lint", "review": "review_code", "doc": "generate_doc",
    "fix": "write_file", "plan": "write_file",
}

# ── Scout ──
# (Constants imported from .system)

