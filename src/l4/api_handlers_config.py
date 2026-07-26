"""Config API handlers — expose kernel/params.py constants via REST for frontend.

Endpoints:
  GET  /api/config              — List all registered config keys
  GET  /api/config/:key         — Get a specific config value
  PUT  /api/config/:key         — Update a config value at runtime
  GET  /api/config/category/:cat — Filter by category

The config system supports three layers:
  L1: hardcoded Final constants in kernel/params.py (read-only but still listed)
  L2: runtime overrides via PUT (stored in memory, ephemeral)
"""

from __future__ import annotations

import inspect
import sys
from typing import Any

# ── Runtime override storage (ephemeral) ──
_CONFIG_OVERRIDES: dict[str, Any] = {}

# ── Config categories (mapping for frontend grouping) ──
_CATEGORIES: dict[str, str] = {
    "API_GATEWAY_PORT": "network",
    "API_GATEWAY_HOST": "network",
    "API_CORS_ORIGIN": "network",
    "MCP_DEFAULT_URL": "network",
    "MCP_TIMEOUT": "network",
    "BROADCAST_INTERVAL": "network",
    "DEFAULT_CELL_ID": "kernel",
    "KERNEL_VERSION": "kernel",
    "PRAXIS_CODENAME": "kernel",
    "CENTRAL_ROLES": "kernel",
    "CENTRAL_DEFAULT_ROLES": "kernel",
    "DEFAULT_AGENT_CONFIGS": "agents",
    "AGENT_CLEARANCE": "agents",
    "AGENT_LOOP_DEFAULT_STEPS": "agents",
    "AGENT_LOOP_DEFAULT_TIMEOUT": "agents",
    "L3A_MAX_STEPS": "agents",
    "L3A_TIMEOUT": "agents",
    "LLM_PROVIDER_URLS": "llm",
    "LLM_RATE_LIMIT_WAIT": "llm",
    "LLM_TRANSIENT_BACKOFF_BASE": "llm",
    "LLM_EMPTY_RESPONSE_WAITS": "llm",
    "SESSION_TIMEOUT": "session",
    "TOOL_BUILD_TIMEOUT": "tools",
    "TOOL_HTTP_TIMEOUT_SHORT": "tools",
    "TOOL_HTTP_TIMEOUT_MEDIUM": "tools",
    "TOOL_HTTP_TIMEOUT_LONG": "tools",
    "SANDBOX_ROOT_PATH": "sandbox",
    "PRAXIS_DATA_DIR": "paths",
    "PRAXIS_EVENTS_DB": "paths",
    "PRAXIS_CARD_REGISTRY": "paths",
    "PRAXIS_CARD_GATE": "paths",
    "PRAXIS_MUTE_STATE": "paths",
    "PRAXIS_MODE_STATE": "paths",
    "PRAXIS_TODO_STATE": "paths",
    "EVENT_STORE_MAX_QUERY": "kernel",
    "ERROR_BUS_BUFFER": "kernel",
    "AGENT_REPUTATION_DEFAULTS": "agents",
}

_EXCLUDED = {"_DEFAULT_DATA_ROOT", "_SANDBOX_DEFAULT", "_DEFAULT_URL",
             "AllocatorDefaults", "AgentDefaults", "ResourceProfileDefaults",
             "LLM_PROVIDER_URLS", "AGENT_CLEARANCE", "DEFAULT_AGENT_CONFIGS",
             "AGENT_REPUTATION_DEFAULTS", "CENTRAL_ROLES", "CENTRAL_DEFAULT_ROLES",
             "LLM_EMPTY_RESPONSE_WAITS", "PRIORITY_GRADIENT"}
"""Keys excluded from GET /api/config listing (complex types that are exposed via dedicated getter)."""


def _fetch(key: str) -> dict:
    """Fetch a config value: override > params module."""
    if key in _CONFIG_OVERRIDES:
        return {"success": True, "key": key, "value": _CONFIG_OVERRIDES[key],
                "source": "override", "category": _CATEGORIES.get(key, "misc")}
    from l1.kernel import params
    value = getattr(params, key, None)
    if value is None:
        return {"success": False, "error": f"unknown config key: {key}"}
    return {"success": True, "key": key, "value": _serialize(value),
            "source": "default", "category": _CATEGORIES.get(key, "misc")}


def _serialize(value: Any) -> Any:
    """Convert Final types to JSON-safe values."""
    if hasattr(value, "_name"):     # enum
        return value._name_
    if hasattr(value, "__dataclass_fields__"):
        return {f: getattr(value, f) for f in value.__dataclass_fields__}
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, bool):
        return value
    return str(value)


# ── API Handlers ──


def handle_config_list(body: dict | None = None) -> dict:
    """GET /api/config — List all registered config keys with values."""
    from l1.kernel import params
    b = body or {}
    category_filter = b.get("category", "")
    keys = [name for name in dir(params)
            if name.isupper() and not name.startswith("_")
            and name not in _EXCLUDED]

    entries = []
    for key in keys:
        if category_filter and _CATEGORIES.get(key, "misc") != category_filter:
            continue
        r = _fetch(key)
        if r.get("success"):
            entries.append(r)

    entries.sort(key=lambda e: e["key"])
    return {
        "success": True,
        "count": len(entries),
        "category": category_filter or "*",
        "entries": entries,
    }


def handle_config_get(body: dict | None = None) -> dict:
    """POST /api/config/get — Get a specific config value by key."""
    b = body or {}
    key = b.get("key", "").strip()
    if not key:
        return {"success": False, "error": "key is required"}
    return _fetch(key)


def handle_config_set(body: dict | None = None) -> dict:
    """PUT /api/config/set — Override a config value at runtime."""
    b = body or {}
    key = b.get("key", "").strip()
    value = b.get("value")
    if not key:
        return {"success": False, "error": "key and value are required"}
    _CONFIG_OVERRIDES[key] = value
    return {"success": True, "key": key, "value": value, "source": "override"}


def handle_config_categories(body: dict | None = None) -> dict:
    """GET /api/config/categories — List all config categories."""
    cats: dict[str, list[str]] = {}
    for key, cat in sorted(_CATEGORIES.items(), key=lambda x: x[1]):
        cats.setdefault(cat, []).append(key)
    return {"success": True, "categories": cats}


# ── Route registration ──

CONFIG_ROUTES: list[tuple[str, str, Any, str]] = [
    ("POST", "/api/config", handle_config_list, "List all config (optional filter: {category})"),
    ("POST", "/api/config/get", handle_config_get, "Get config value by key"),
    ("PUT", "/api/config/set", handle_config_set, "Set config override at runtime"),
    ("GET", "/api/config/categories", handle_config_categories, "List config categories"),
]
