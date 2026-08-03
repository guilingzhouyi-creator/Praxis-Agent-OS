"""Constitution API handlers — query, update, and reload constitution rules.

Endpoints:
  GET    /api/v2/constitution          — list all rules (builtin + custom)
  PUT    /api/v2/constitution/rules    — add/update custom rules
  DELETE /api/v2/constitution/rules    — clear all custom rules
  POST   /api/v2/constitution/reload   — reload from file
  GET    /api/v2/constitution/summary  — LLM-readable summary text
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def handle_constitution_get(body: dict | None = None) -> dict:
    """GET /api/v2/constitution — return full constitution state."""
    try:
        from l1.kernel.constitution import get_constitution
        c = get_constitution()
        return {"success": True, "constitution": c.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_constitution_rules_update(body: dict | None = None) -> dict:
    """PUT /api/v2/constitution/rules — add/update custom rules.

    Body:
      rules: list[{"id": "...", "severity": "MUST|SHOULD|MAY",
                   "description": "...", "section": "§custom"}]
    """
    b = body or {}
    rules = b.get("rules", [])
    if not rules:
        return {"success": False, "error": "rules list required"}
    try:
        from l1.kernel.constitution import get_constitution
        c = get_constitution()
        return c.update_rules(rules)
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_constitution_rules_clear(body: dict | None = None) -> dict:
    """DELETE /api/v2/constitution/rules — remove all custom rules."""
    try:
        from l1.kernel.constitution import get_constitution
        return get_constitution().clear_custom_rules()
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_constitution_reload(body: dict | None = None) -> dict:
    """POST /api/v2/constitution/reload — reload from file."""
    try:
        from l1.kernel.constitution import get_constitution
        return get_constitution().reload()
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_constitution_summary(body: dict | None = None) -> dict:
    """GET /api/v2/constitution/summary — LLM-readable summary."""
    try:
        from l1.kernel.constitution import get_constitution
        agent_id = (body or {}).get("agent_id", "") if body else ""
        return {"success": True, "summary": get_constitution().summary(for_agent=agent_id)}
    except Exception as e:
        return {"success": False, "error": str(e)}
