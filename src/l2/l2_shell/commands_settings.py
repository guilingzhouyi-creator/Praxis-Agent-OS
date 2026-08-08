"""Hierarchical settings commands — global/cell/agent/pool scope.

Usage:
  /settings [global]                     — list global settings
  /settings global set <key> <value>     — set global setting
  /settings cell <cell_id>               — list cell settings
  /settings cell <cell_id> set <k> <v>   — set cell setting
  /settings agent <agent_id>             — list agent settings
  /settings agent <agent_id> set <k> <v> — set agent setting
  /settings pool scout <cell_id>         — list scout pool config
  /settings pool subagent <cell_id>      — list subagent pool config
"""

from __future__ import annotations

import logging

from l2.i18n import t as _t

from .commands.common import _coerce

logger = logging.getLogger(__name__)


def _get_center():
    """Get SettingsCenter singleton."""
    from l3.config.settings_center import get_center

    return get_center()


def _cmd_settings(args: list[str]) -> dict:
    """Multi-level settings query and configuration.

    Parser order:
      1. /settings                    → list global settings
      2. /settings global             → list global settings
      3. /settings global set k=v     → set global
      4. /settings cell <id>          → list cell settings
      5. /settings cell <id> set k=v  → set cell (ACB)
      6. /settings agent <id>         → list agent settings
      7. /settings agent <id> set k=v → set agent (ACB)
      8. /settings pool scout <id>    → scout pool config
      9. /settings pool subagent <id> → subagent pool config
    """
    if not args:
        return _settings_global([])

    scope = args[0].lower()
    rest = args[1:]

    if scope == "global":
        return _settings_global(rest)

    if scope == "cell" and len(rest) >= 1:
        return _settings_cell(rest[0], rest[1:])

    if scope == "agent" and len(rest) >= 1:
        return _settings_agent(rest[0], rest[1:])

    if scope == "pool" and len(rest) >= 1:
        return _settings_pool(rest[0], rest[1:])

    return {"success": False, "error": _t("shell.app_error.usage_settings")}


def _settings_global(args: list[str]) -> dict:
    """Global scope — list or set SettingsCenter keys."""
    center = _get_center()
    if args and args[0] == "set" and len(args) >= 3:
        key, value = args[1], _coerce(args[2])
        center.set(key, value)
        return {"success": True, "scope": "global", "key": key, "value": value}
    # List all L3 (runtime) overrides
    raw = center._dump_l3() if hasattr(center, "_dump_l3") else {}
    return {"success": True, "scope": "global", "settings": raw}


def _settings_cell(cell_id: str, args: list[str]) -> dict:
    """Cell scope — manage settings via ACB (Agent Control Block)."""
    from ..scheduler.acb import get_service as get_acb

    acb = get_acb()
    if args and args[0] == "set" and len(args) >= 3:
        key, value = args[1], _coerce(args[2])
        acb.set_slot(cell_id, key, value)
        return {"success": True, "scope": "cell", "cell_id": cell_id, "key": key, "value": value}

    slot = acb.get_slot(cell_id)
    if slot:
        return {"success": True, "scope": "cell", "cell_id": cell_id, "slots": slot}
    return {"success": False, "error": f"cell '{cell_id}' not found in ACB"}


def _settings_agent(agent_id: str, args: list[str]) -> dict:
    """Agent scope — manage settings via ACB."""
    from ..scheduler.acb import get_service as get_acb

    acb = get_acb()
    if args and args[0] == "set" and len(args) >= 3:
        key, value = args[1], _coerce(args[2])
        acb.set_slot(agent_id, key, value)
        return {"success": True, "scope": "agent", "agent_id": agent_id, "key": key, "value": value}

    slot = acb.get_slot(agent_id)
    if slot:
        return {"success": True, "scope": "agent", "agent_id": agent_id, "slots": slot}
    return {"success": False, "error": f"agent '{agent_id}' not found in ACB"}


def _settings_pool(pool_type: str, args: list[str]) -> dict:
    """Pool scope — Scout or SubAgent pool config."""
    if pool_type == "scout":
        return _settings_scout_pool(*args) if args else _settings_scout_pool()
    if pool_type == "subagent":
        return _settings_subagent_pool(*args) if args else _settings_subagent_pool()
    return {"success": False, "error": _t("shell.app_error.usage_settings_pool")}


def _settings_scout_pool(cell_id: str = "") -> dict:
    """Query ScoutPool configuration."""
    try:
        from ..agent.scout import get_pool

        pool = get_pool()
        stats = pool.stats() if hasattr(pool, "stats") else {}
        return {"success": True, "scope": "pool", "pool_type": "scout", "cell_id": cell_id or "default", "stats": stats}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _settings_subagent_pool(cell_id: str = "") -> dict:
    """Query SubAgentPool configuration."""
    try:
        from ..agent.subagent_pool import get_pool

        pool = get_pool()
        stats = pool.stats() if hasattr(pool, "stats") else {}
        return {
            "success": True,
            "scope": "pool",
            "pool_type": "subagent",
            "cell_id": cell_id or "default",
            "stats": stats,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
