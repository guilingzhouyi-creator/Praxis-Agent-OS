"""Agent config API handlers — query and update agent parameters at runtime.

Endpoints:
  GET  /api/v1/agents/config  — return current agent_role_map, priorities, clearance, defaults
  PUT  /api/v1/agents/config  — update agent_role_map, agent_priority, or clearance selectively
"""

from __future__ import annotations

from typing import Any


def agent_list(body: dict | None = None) -> dict:
    """List all registered agents and their config."""
    from l1.kernel.params.agent import AGENT_ROLE_MAP, AGENT_CLEARANCE, DEFAULT_AGENT_CONFIGS
    agents = {}
    for role, clearance in AGENT_CLEARANCE.items():
        cfg = DEFAULT_AGENT_CONFIGS.get(role)
        agents[role] = {
            "ring": clearance,
            "max_scouts": cfg.max_scouts if cfg else 3,
        }
    return {"success": True, "agents": agents}


def agent_select(body: dict | None = None) -> dict:
    """Select an agent by ID (stub for backward compat)."""
    agent_id = (body or {}).get("agent_id", "")
    if not agent_id:
        from l1.kernel.params.agent import DEFAULT_AGENT_CONFIGS
        roles = list(DEFAULT_AGENT_CONFIGS.keys())
        return {"success": True, "agents": [{"agent_id": r, "role": r} for r in roles]}
    return {"success": True, "agent_id": agent_id}


def agent_select_by(body: dict | None = None) -> dict:
    """Select an agent by role/domain (stub for backward compat)."""
    role = (body or {}).get("role", "")
    if role:
        return {"success": True, "agent_id": role, "role": role}
    return {"success": True, "agents": [], "note": "no role specified"}



def agent_preconnect(body: dict | None = None) -> dict:
    """Pre-connect verification (stub)."""
    agent_id = (body or {}).get("agent_id", "")
    return {"success": True, "agent_id": agent_id, "allowed": True}

def agent_reachable(body: dict | None = None) -> dict:
    """Check if agent is reachable (stub)."""
    agent_id = (body or {}).get("agent_id", "")
    return {"success": True, "agent_id": agent_id, "reachable": True}

def agent_direct(body: dict | None = None) -> dict:
    """Start direct session (stub)."""
    return {"success": True, "session_id": ""}

def agent_direct_close(body: dict | None = None) -> dict:
    """Close direct session (stub)."""
    return {"success": True}

def agent_review_message(body: dict | None = None) -> dict:
    """Review message (stub)."""
    return {"success": True, "approved": True}

def _shell_dispatch(body: dict | None = None) -> dict:
    """Shell command dispatch (stub)."""
    return {"success": False, "error": "shell dispatch not available"}

def _shell_autocomplete(body: dict | None = None) -> dict:
    """Shell autocomplete (stub)."""
    return {"success": True, "suggestions": []}

def _shell_commands(body: dict | None = None) -> dict:
    """Shell commands list (stub)."""
    return {"success": True, "commands": []}

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
