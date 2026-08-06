"""Constants: API, network, LLM, IPC, transport."""

import socket as _socket
from typing import Final

# ── PAL Router (cost-optimized LLM routing) ──
PAL_FRUGAL_COST: Final[int] = 1
PAL_STANDARD_COST: Final[int] = 10
PAL_FRONTIER_COST: Final[int] = 30
PAL_FRUGAL_THRESHOLD: Final[float] = 0.4
PAL_STANDARD_THRESHOLD: Final[float] = 0.7
PAL_ESCALATE_AFTER: Final[int] = 2
PAL_DOWNGRADE_AFTER: Final[int] = 5
PAL_DEFAULT_TIER: Final[str] = "frugal"

# ── PAL complexity scoring constants ──
PAL_COMPLEXITY_MAX_TOKENS: Final[int] = 4000
PAL_COMPLEXITY_MAX_TOOLS: Final[int] = 5
PAL_COMPLEXITY_MAX_DEPTH: Final[int] = 5
PAL_COMPLEXITY_WEIGHT_TOKENS: Final[float] = 0.30
PAL_COMPLEXITY_WEIGHT_TOOLS: Final[float] = 0.30
PAL_COMPLEXITY_WEIGHT_DEPTH: Final[float] = 0.40


# ── Device rate limit defaults ──
DEVICE_RATE_LIMIT_LLM: Final[int] = 10
DEVICE_RATE_LIMIT_STORAGE: Final[int] = 100


# ── Network service ──
NETWORK_DEFAULT_TIMEOUT: Final[int] = 30


# ── LLM retry backoff parameters ──
LLM_RATE_LIMIT_WAIT: Final[int] = 60
LLM_TRANSIENT_BACKOFF_BASE: Final[int] = 3
LLM_EMPTY_RESPONSE_WAITS: Final[list[int]] = [1, 1, 2, 2, 3]
LLM_MAX_RATE_LIMIT_RETRIES: Final[int] = 3
LLM_MAX_OVERFLOW_RETRIES: Final[int] = 2
LLM_MAX_TRANSIENT_RETRIES: Final[int] = 2
LLM_MAX_EMPTY_RETRIES: Final[int] = 3

# ─── LLM provider default URLs ──
LLM_PROVIDER_URLS: Final[dict[str, str]] = {
    "openai":    "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "deepseek":  "https://api.deepseek.com/v1",
    "ollama":    "http://localhost:11434",
}
ANTHROPIC_DEFAULT_URL: Final[str] = LLM_PROVIDER_URLS["anthropic"]
ANTHROPIC_API_VERSION: Final[str] = "2023-06-01"

# ── Default model names (single source of truth) ──
DEFAULT_MODEL_OPENAI: Final[str] = "gpt-4o"
DEFAULT_MODEL_OPENAI_MINI: Final[str] = "gpt-4o-mini"
DEFAULT_MODEL_ANTHROPIC_SONNET: Final[str] = "claude-sonnet-4-20250514"
DEFAULT_MODEL_ANTHROPIC_HAIKU: Final[str] = "claude-haiku-3-5"
DEFAULT_MODEL_DEEPSEEK_V4: Final[str] = "deepseek-v4"
DEFAULT_MODEL_DEEPSEEK_CHAT: Final[str] = "deepseek-chat"
DEFAULT_MODEL_OLLAMA: Final[str] = "qwen2.5"
DEFAULT_MODEL_OLLAMA_CODER: Final[str] = "qwen2.5-coder:7b"
"""Default ollama coding model (documented deployment default)."""
DEFAULT_MODEL_MOCK: Final[str] = "mock"


# ── LLM reasoning / thinking budget ──
REASONING_EFFORT_NONE: Final[str] = "none"
REASONING_EFFORT_LOW: Final[str] = "low"
REASONING_EFFORT_MEDIUM: Final[str] = "medium"
REASONING_EFFORT_HIGH: Final[str] = "high"
REASONING_EFFORT_XHIGH: Final[str] = "xhigh"   # OpenAI GPT-5.x / Claude Opus 5+ / DeepSeek V4
REASONING_EFFORT_MAX: Final[str] = "max"       # OpenAI GPT-5.x / Claude Fable 5 / Opus 5
DEFAULT_REASONING_EFFORT: Final[str] = REASONING_EFFORT_NONE
DEFAULT_THINKING_BUDGET: Final[int] = 0
THINK_MAX_BUDGET: Final[int] = 32768
# Default ceiling: "max" (no restriction); admins lower via think.max_reasoning.
# NOTE: thinking_budget is honored only by providers exposing a user-defined
# budget (legacy Anthropic budget_tokens, Gemini thinkingBudget); modern
# models (GPT-5.x, Claude Opus 5+/Sonnet 5, DeepSeek V4) allocate reasoning
# tokens adaptively server-side and are filtered by capability probing.
THINK_MAX_REASONING: Final[str] = REASONING_EFFORT_MAX

# ── Reasoning effort tiers per provider (normalization table) ──
# Requested tiers outside a provider's set fall back to the highest supported
# tier at or below the request (lowest supported when the request is below
# all); empty = provider has no reasoning_effort support (param dropped).
# Overridable per deployment via praxis.yaml `llm.effort_tiers`.
EFFORT_RANK: Final[dict[str, int]] = {
    REASONING_EFFORT_NONE: 0,
    REASONING_EFFORT_LOW: 1,
    REASONING_EFFORT_MEDIUM: 2,
    REASONING_EFFORT_HIGH: 3,
    REASONING_EFFORT_XHIGH: 4,
    REASONING_EFFORT_MAX: 5,
}
EFFORT_TIERS_BY_PROVIDER: Final[dict[str, tuple[str, ...]]] = {
    "openai": (REASONING_EFFORT_NONE, "minimal", REASONING_EFFORT_LOW,
               REASONING_EFFORT_MEDIUM, REASONING_EFFORT_HIGH,
               REASONING_EFFORT_XHIGH, REASONING_EFFORT_MAX),
    # Claude has no none/minimal: lowest supported is low
    "anthropic": (REASONING_EFFORT_LOW, REASONING_EFFORT_MEDIUM,
                  REASONING_EFFORT_HIGH, REASONING_EFFORT_XHIGH,
                  REASONING_EFFORT_MAX),
    # DeepSeek V4 reasoning_effort values observed: low/medium/high
    "deepseek": (REASONING_EFFORT_LOW, REASONING_EFFORT_MEDIUM,
                 REASONING_EFFORT_HIGH),
    "ollama": (),
    "mock": (),
}

# ── LLMConfig defaults (was hardcoded in ports.py) ──
LLM_DEFAULT_MAX_TOKENS: Final[int] = 2048
"""Default max_tokens in LLMConfig."""
LLM_DEFAULT_TEMPERATURE: Final[float] = 0.3
"""Default temperature in LLMConfig."""
LLM_DEFAULT_CACHE_BREAKPOINTS: Final[int] = 4
"""Default cache_breakpoints in LLMConfig."""
LLM_PROVIDER_MAX_TOKENS: Final[int] = 512
"""Default max_tokens in provider generate() signatures."""
LLM_PROVIDER_CONTEXT_WINDOW: Final[int] = 32768
"""Provider capability context window fallback."""


# ── Kernel network ──
BROADCAST_INTERVAL: Final[float] = 15.0
PEER_TIMEOUT: Final[float] = 60.0
DISCOVERY_PORT_DEFAULT: Final[int] = 42069
PRAXIS_PORT_DEFAULT: Final[int] = 42070
ENV_DISCOVERY_PORT: Final[str] = "PRAXIS_DISCOVERY_PORT"
ENV_PRAXIS_PORT: Final[str] = "PRAXIS_PORT"
ENV_API_TOKEN: Final[str] = "PRAXIS_API_TOKEN"


# ── Transport TLS ──
NET_TLS_ENABLED: Final[bool] = False
NET_TLS_CERT_PATH: Final[str] = ""
NET_TLS_KEY_PATH: Final[str] = ""


# ── Transport magic numbers (was hardcoded in net_transport.py) ──
TCP_RECV_BUF_SIZE: Final[int] = 65536
TCP_LISTEN_BACKLOG: Final[int] = 5
TRANSPORT_VERSION: Final[str] = "1.0"
TRANSPORT_SOCKET_TIMEOUT: Final[float] = 10.0
TRANSPORT_SOCKET_FAMILY: Final[int] = _socket.AF_INET  # AF_INET6 for dual-stack


# ── Service-level timeouts ──
CI_SHELL_TIMEOUT: Final[int] = 30
GIT_TIMEOUT: Final[int] = 30
LLM_HTTP_TIMEOUT: Final[int] = 60
LLM_LIGHTWEIGHT_TIMEOUT: Final[int] = 30
SHELL_CMD_TIMEOUT: Final[int] = 30
MEMORY_INIT_TIMEOUT: Final[int] = 30
TOOL_WEBHOOK_TIMEOUT: Final[int] = 15


# ── API / network defaults ──
API_GATEWAY_PORT: Final[int] = 8080
API_GATEWAY_HOST: Final[str] = "127.0.0.1"
API_MAX_BODY_BYTES: Final[int] = 1_048_576
API_PAGE_MAX_LIMIT: Final[int] = 100
"""Hard cap for API list/page endpoints (guards against unbounded responses)."""
API_WS_PORT: Final[int] = 8081
"""WebSocket bridge port (bidirectional realtime channel, see l4/ws)."""
RPC_SERVER_PORT: Final[int] = 42110
"""RPC server port (distributed cell/node method invocation, see l4/rpc)."""
AUTH_TOKEN_TTL_SECONDS: Final[int] = 86400
"""Default auth token lifetime in seconds (AuthService.issue_token)."""
MCP_DEFAULT_URL: Final[str] = "http://localhost:3500/mcp/v1"
MCP_TIMEOUT: Final[int] = 5
MCP_OAUTH_REDIRECT_PORT: Final[int] = 19876

# ── CORS ──
API_CORS_ORIGIN: Final[str] = "*"
API_CORS_ALLOW_METHODS: Final[str] = "GET, POST, DELETE, OPTIONS"
API_CORS_ALLOW_HEADERS: Final[str] = "Content-Type"

# ── HTTP User-Agent ──
HTTP_USER_AGENT: Final[str] = "Praxis/1.0"


# ── Notify / webhook ──
NOTIFY_WEBHOOK_TIMEOUT: Final[int] = 15


# ── I18n (ports.I18nPort defaults) ──
I18N_DEFAULT_LOCALE: Final[str] = "en"
I18N_LOCALE_DIR: Final[str] = ""
I18N_FALLBACK_TO_KEY: Final[bool] = True

# ── Ring Buffer Channel (ports.ChannelPort / ring adapter) ──
CHANNEL_RING_CAPACITY: Final[int] = 1024
CHANNEL_RING_OVERWRITE: Final[bool] = False
CHANNEL_RING_GET_TIMEOUT: Final[float] = 5.0
CHANNEL_RING_PUT_TIMEOUT: Final[float] = 5.0

# ── Worker Pool (ports.WorkerPort / thread adapter) ──
WORKER_POOL_MIN: Final[int] = 4
WORKER_POOL_MAX: Final[int] = 32
WORKER_POOL_QUEUE_SIZE: Final[int] = 256
WORKER_POOL_IDLE_TIMEOUT: Final[float] = 60.0
WORKER_POOL_TASK_TIMEOUT: Final[float] = 30.0

# ── SubAgentPool defaults ──
SUBAGENT_POOL_EXPLORE_WORKERS: Final[int] = 4
SUBAGENT_POOL_EXECUTE_WORKERS: Final[int] = 4


# ── SSE bridge ──
SSE_QUEUE_MAXSIZE: Final[int] = 256


# ── Service timeouts (scattered in code, centralized here) ──
LSP_MANAGER_TIMEOUT: Final[float] = 5.0
LSP_MANAGER_LONG_TIMEOUT: Final[float] = 30.0
MCP_BRIDGE_TIMEOUT: Final[float] = 10.0
MCP_TOKEN_EXPIRY: Final[int] = 3600
MCP_TOKEN_REFRESH_RATIO: Final[float] = 0.8
MCP_BRIDGE_LONG_TIMEOUT: Final[float] = 30.0
SHELL_SESSION_TIMEOUT: Final[float] = 3.0
SHELL_READ_CHUNK_SIZE: Final[int] = 4096
POOL_QUEUE_TIMEOUT: Final[float] = 1.0
TERM_HANDLER_TIMEOUT: Final[float] = 15.0
TERM_HANDLER_LONG_TIMEOUT: Final[float] = 30.0
API_GATEWAY_QUEUE_TIMEOUT: Final[float] = 30.0
R4_AGENT_JOIN_TIMEOUT: Final[float] = 5.0
SUBAGENT_RUN_TIMEOUT: Final[float] = 120.0
SUBAGENT_JOIN_TIMEOUT: Final[float] = 30.0
MCP_EXPORT_MODE: Final[str] = "full"
"""MCP server export mode: normal (base tools only) | selected (L3A only) | full (both)."""
SEARCH_MAX_WORKERS: Final[int] = 8


# ── API gateway default port ──
API_GATEWAY_DEFAULT_PORT: Final[int] = 8080


# ── IPC / RPC ──
import os as _os

from ..paths import get_paths as _gp
from ..platform import IS_NT as _IS_WIN

IPC_SOCKET_DIR: Final[str] = _gp().socket_dir

if _IS_WIN:
    # Windows: TCP localhost (Unix sockets not available)
    IPC_KERNEL_SOCKET: str = "127.0.0.1:42100"
    IPC_LLM_SOCKET: str = "127.0.0.1:42101"
    IPC_SANDBOX_SOCKET: str = "127.0.0.1:42102"
else:
    IPC_KERNEL_SOCKET: str = _os.path.join(IPC_SOCKET_DIR, "l1.kernel.sock")
    IPC_LLM_SOCKET: str = _os.path.join(IPC_SOCKET_DIR, "llm.sock")
    IPC_SANDBOX_SOCKET: str = _os.path.join(IPC_SOCKET_DIR, "sandbox.sock")
IPC_KEEPALIVE_INTERVAL: Final[float] = 5.0
IPC_MSG_TTL: Final[float] = 30.0
IPC_CHANNEL_MAXLEN: Final[int] = 200


# ── Subprocess / LSP / HTTP timeouts (config-driven) ──
SUBPROCESS_SHORT_TIMEOUT: Final[int] = 5
LSP_DIAG_TIMEOUT: Final[int] = 30
HTTP_CALLBACK_TIMEOUT: Final[int] = 10


# ── Environment variable names (single source of truth) ──
ENV_SANDBOX_ROOT: Final[str] = "PRAXIS_SANDBOX_ROOT"
ENV_DEFAULT_CELL: Final[str] = "PRAXIS_DEFAULT_CELL"
ENV_OPENAI_KEY: Final[str] = "OPENAI_API_KEY"
ENV_DEEPSEEK_KEY: Final[str] = "DEEPSEEK_API_KEY"
ENV_ANTHROPIC_KEY: Final[str] = "ANTHROPIC_API_KEY"
ENV_OLLAMA_URL: Final[str] = "OLLAMA_URL"
ENV_OLLAMA_MODEL: Final[str] = "OLLAMA_MODEL"
ENV_OPENAI_URL: Final[str] = "OPENAI_API_URL"
ENV_OPENAI_MODEL: Final[str] = "OPENAI_MODEL"
ENV_ANTHROPIC_URL: Final[str] = "ANTHROPIC_API_URL"
ENV_ANTHROPIC_MODEL: Final[str] = "ANTHROPIC_MODEL"
ENV_LLM_WS_URL: Final[str] = "LLM_WS_URL"
ENV_LLM_WS_MODEL: Final[str] = "LLM_WS_MODEL"


# ── Fallback model/URL placeholders ──
FALLBACK_MODEL: Final[str] = "<model>"
FALLBACK_LLM_API_URL: Final[str] = "<api-url>"
LLM_RATE_LIMIT_DEFAULT: Final[int] = 10
FILESYSTEM_RATE_LIMIT_DEFAULT: Final[int] = 100
