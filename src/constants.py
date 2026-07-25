"""Constants — thin re-export bridge for tools_*.py modules.

Single source of truth: kernel.params
All tools_*.py files import from here via `from constants import ...`.

Do NOT define new constants here — add them to kernel.params instead.
"""

from services.tool_spec import ToolRing

# ToolRing alias (tools files use `from constants import ToolRing as R`)
R = ToolRing

# Re-export from kernel.params (single source of truth)
from kernel.params import (
    AGENT_REPUTATION_DEFAULTS,
    AGENT_CLEARANCE,
    DEFAULT_AGENT_CONFIGS,
    TERRITORY_MAP,
    TERRITORY_PATHS,
    TOOL_DANGER_LEVEL,
    TOOL_GREP_TIMEOUT,
    TOOL_TERMINAL_TIMEOUT,
    DANGER_TO_GATES,
    GateStatus,
    PraxisRing,
    RequestPoolConfig,
    WitnessStatus,
    # Consolidated timeouts
    TOOL_BUILD_TIMEOUT,
    TOOL_DOCKER_TIMEOUT,
    TOOL_PIP_TIMEOUT,
    TOOL_GIT_TIMEOUT,
    TOOL_PING_TIMEOUT,
    TOOL_HTTP_TIMEOUT_SHORT,
    TOOL_HTTP_TIMEOUT_MEDIUM,
    TOOL_HTTP_TIMEOUT_LONG,
    TOOL_PIP_INSTALL_TIMEOUT,
    TOOL_NPM_TIMEOUT,
    TOOL_PYRIGHT_TIMEOUT,
    TOOL_COMPILE_CHECK_TIMEOUT,
    TOOL_SCOUT_RUN_TIMEOUT,
    TOOL_SCOUT_MAX_STEPS,
    DEVICE_RATE_LIMIT_LLM,
    DEVICE_RATE_LIMIT_STORAGE,
    MEMORY_RECALL_LIMIT,
    MEMORY_RECALL_LIMIT_LARGE,
    MEMORY_BUILD_CONTEXT_ENTRIES,
    MEMORY_ALERT_EXPORT_LIMIT,
    MEMORY_LOG_QUERY_LIMIT,
    MEMORY_PAGER_RECALL_LIMIT,
)
from services.tool_spec import RING_GATE_MAP

# Legacy alias: AGENT_TERRITORIES = TERRITORY_PATHS
AGENT_TERRITORIES = TERRITORY_PATHS
