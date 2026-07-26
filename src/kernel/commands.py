"""Command registry — YAML-driven shell command definitions.

Commands defined in commands.yaml (single source of truth).
Praxis.yaml commands: section overrides help/aliases at boot.
Handler functions registered by name from services/l2_shell.py.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

# Argument completion types
ARG_AGENT = "agent"
ARG_ROLE = "role"
ARG_DOMAIN = "domain"

_COMMAND_HANDLERS: dict[str, Callable] = {}
_DEFAULTS: dict[str, dict] = {}
_overrides: dict[str, dict] = {}
_loaded = False

_COMMANDS_YAML_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "commands.yaml")


def load_command_defs(yaml_path: str = "") -> int:
    """Load command definitions from commands.yaml into _DEFAULTS."""
    global _DEFAULTS, _loaded
    path = yaml_path or _COMMANDS_YAML_PATH
    if not os.path.exists(path):
        logger.warning("commands.yaml not found at %s", path)
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            _DEFAULTS.update(data)
            _loaded = True
            logger.info("command_defs: loaded %d commands from %s", len(data), path)
            return len(data)
    except Exception as e:
        logger.warning("command_defs load failed: %s", e)
    return 0


def load_command_overrides(cfg: dict) -> None:
    """Load command overrides from praxis.yaml commands: section."""
    global _overrides
    if not cfg:
        return
    _overrides.update(cfg)
    logger.info("command overrides loaded: %d keys", len(cfg))


def register_command(name: str, handler: Callable) -> None:
    """Register a command handler function.

    Command metadata (help, aliases, args) lives in _DEFAULTS or YAML overrides.
    This only registers the executable handler.
    """
    _COMMAND_HANDLERS[name] = handler


def get_command(name: str) -> dict | None:
    """Get merged command definition (override layered on default)."""
    base = dict(_DEFAULTS.get(name, {}))
    ov = _overrides.get(name, {})
    merged = {**base, **ov}
    if ov.get("aliases"):
        merged["aliases"] = ov["aliases"]
    if ov.get("args"):
        merged["args"] = ov["args"]
    merged["name"] = name
    merged["has_handler"] = name in _COMMAND_HANDLERS
    return merged if merged.get("help") else None


def get_handler(name: str) -> Callable | None:
    return _COMMAND_HANDLERS.get(name)


# ── Scope resolution (shared across all commands with --cell / --agent) ──

def resolve_scope(args: list[str]) -> tuple[str, str, list[str]]:
    """Parse --cell <id> / --agent <id> flags from args.

    Returns:
        (scope, scope_id, remaining_args)
        scope: "global" | "cell" | "agent"
    """
    rest = list(args)
    scope = "global"
    scope_id = ""
    if "--cell" in rest:
        idx = rest.index("--cell")
        if idx + 1 < len(rest):
            scope, scope_id = "cell", rest[idx + 1]
            rest = rest[:idx] + rest[idx + 2:]
    if "--agent" in rest:
        idx = rest.index("--agent")
        if idx + 1 < len(rest):
            scope, scope_id = "agent", rest[idx + 1]
            rest = rest[:idx] + rest[idx + 2:]
    return scope, scope_id, rest


def resolve_agents(scope: str = "global", scope_id: str = "") -> list[str]:
    """Resolve scope → list of agent_ids."""
    if scope == "agent" and scope_id:
        return [scope_id]
    if scope == "cell" and scope_id:
        try:
            from services.cell import get_cell
            cell = get_cell(scope_id)
            agents = cell.list_agents() if hasattr(cell, "list_agents") else []
            return [a.get("agent_id", a) if isinstance(a, dict) else a for a in agents]
        except Exception:
            return []
    try:
        from services.cell import get_cell
        cell = get_cell()
        agents = cell.list_agents() if hasattr(cell, "list_agents") else []
        return [a.get("agent_id", a) if isinstance(a, dict) else a for a in agents]
    except Exception:
        return ["agent-1"]


def list_commands() -> list[dict]:
    """List all known commands (defaults + overrides merged)."""
    all_keys = set(_DEFAULTS.keys()) | set(_overrides.keys())
    result = []
    for k in sorted(all_keys):
        cmd = get_command(k)
        if cmd and cmd.get("has_handler"):
            result.append({
                "name": k,
                "help": cmd["help"],
                "aliases": cmd.get("aliases", []),
                "args": [
                    {"name": a["name"], "optional": a.get("optional", False)}
                    for a in cmd.get("args", [])
                ],
            })
    return result


def list_all_definitions() -> dict:
    """List all command definitions with sources (for debugging)."""
    all_keys = set(_DEFAULTS.keys()) | set(_overrides.keys())
    return {
        k: {
            "source": "override" if k in _overrides else "default",
            "help": (get_command(k) or {}).get("help", ""),
            "aliases": (get_command(k) or {}).get("aliases", []),
            "has_handler": k in _COMMAND_HANDLERS,
        }
        for k in sorted(all_keys)
    }
