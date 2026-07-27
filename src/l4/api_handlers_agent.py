"""Agent config API handlers — query and update agent parameters at runtime.

Endpoints:
  GET  /api/v1/agents/config  — return current agent_role_map, priorities, clearance, defaults
  PUT  /api/v1/agents/config  — update agent_role_map, agent_priority, or clearance selectively
"""

from __future__ import annotations

from typing import Any


def handle_agent_config_get(body: dict | None = None) -> dict:
    """GET /api/v1/agents/config — return current agent config."""
    from l1.kernel.params.agent import (
        AGENT_ROLE_MAP, AGENT_PRIORITY, AGENT_CLEARANCE,
        CENTRAL_ROLES, CENTRAL_DEFAULT_ROLES,
        DEFAULT_AGENT_CONFIGS,
    )
    return {
        "success": True,
        "central_roles": list(CENTRAL_ROLES),
        "default_roles": list(CENTRAL_DEFAULT_ROLES),
        "agent_role_map": {str(k): v for k, v in AGENT_ROLE_MAP.items()},
        "agent_priority": dict(AGENT_PRIORITY),
        "clearance": dict(AGENT_CLEARANCE),
        "agent_defaults": {
            role: {
                "ring": cfg.ring,
                "max_scouts": cfg.max_scouts,
                "max_tokens": cfg.max_tokens,
                "priority": cfg.priority,
            }
            for role, cfg in DEFAULT_AGENT_CONFIGS.items()
        },
    }


def handle_agent_config_set(body: dict | None = None) -> dict:
    """PUT /api/v1/agents/config — update agent config at runtime.

    Accepts any of:
      {"agent_role_map": {"1": "reader", "2": "writer", "3": "reviewer"}}
      {"agent_priority": {"reader": 5, "writer": 5, "reviewer": 5}}
      {"clearance": {"reader": 3, "writer": 3, "reviewer": 3}}
      {"default_roles": ["reader", "writer", "reviewer"]}
    """
    b = body or {}
    results = {}

    if "agent_role_map" in b:
        from l1.kernel.params.agent import AGENT_ROLE_MAP
        AGENT_ROLE_MAP.clear()
        for k, v in b["agent_role_map"].items():
            AGENT_ROLE_MAP[int(k)] = str(v)
        results["agent_role_map"] = len(AGENT_ROLE_MAP)

    if "agent_priority" in b:
        from l1.kernel.params.agent import AGENT_PRIORITY
        AGENT_PRIORITY.clear()
        AGENT_PRIORITY.update(b["agent_priority"])
        results["agent_priority"] = len(AGENT_PRIORITY)

    if "clearance" in b:
        from l1.kernel.params.agent import AGENT_CLEARANCE
        AGENT_CLEARANCE.clear()
        AGENT_CLEARANCE.update(b["clearance"])
        results["clearance"] = len(AGENT_CLEARANCE)

    if "default_roles" in b:
        from l1.kernel.params.agent import CENTRAL_DEFAULT_ROLES
        CENTRAL_DEFAULT_ROLES.clear()
        CENTRAL_DEFAULT_ROLES.extend(str(r) for r in b["default_roles"])
        results["default_roles"] = len(CENTRAL_DEFAULT_ROLES)

    if not results:
        return {"success": False, "error": "no supported fields in body; try agent_role_map, agent_priority, clearance, or default_roles"}

    return {"success": True, "updated": results}
