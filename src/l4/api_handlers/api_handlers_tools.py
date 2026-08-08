"""API handler mixin — tool stats / policy and cache handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def tool_stats(body: dict | None = None) -> dict:
    """Tool usage summary from the central counter."""
    try:
        from l3.services.counter import get_counter

        return get_counter().tool_summary()
    except Exception as e:
        return {"error": str(e)}


def tool_policy_set(body: dict) -> dict:
    """Add a tool policy rule."""
    try:
        from l3.tool_system.tool_policy import PolicyAction, PolicyRule, PolicyScope, ToolPolicy

        scope_str = body.get("scope", "global")
        scope_parts = scope_str.split(":", 1)
        scope = PolicyScope(scope_parts[0])
        scope_id = scope_parts[1] if len(scope_parts) > 1 else ""
        rule = PolicyRule(
            scope=scope,
            scope_id=scope_id,
            tool=body.get("tool", "*"),
            action=PolicyAction(body.get("action", "disable")),
            reason=body.get("reason", ""),
        )
        ToolPolicy.add(rule)
        return {"success": True, "rule": rule.key()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_policy_list(body: dict | None = None) -> dict:
    """List tool policy rules."""
    try:
        from l3.tool_system.tool_policy import ToolPolicy

        return {"success": True, "policies": ToolPolicy.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_policy_remove(body: dict) -> dict:
    """Remove a tool policy rule."""
    try:
        from l3.tool_system.tool_policy import PolicyScope, ToolPolicy

        scope_str = body.get("scope", "global")
        scope_parts = scope_str.split(":", 1)
        scope = PolicyScope(scope_parts[0])
        scope_id = scope_parts[1] if len(scope_parts) > 1 else ""
        ok = ToolPolicy.remove(tool=body.get("tool", "*"), scope=scope, scope_id=scope_id)
        return {"success": ok}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cache_stats(body: dict | None = None) -> dict:
    """Per-agent terminal file-cache statistics."""
    try:
        from l3.agent_terminal import get_terminals

        seen = {}
        for aid, term in get_terminals().items():
            try:
                seen[aid] = term.file_cache.stats()
            except Exception as e:
                logger.warning("cache_stats: %s", e)
        return {"caches": seen, "count": len(seen)}
    except Exception as e:
        return {"error": str(e)}
