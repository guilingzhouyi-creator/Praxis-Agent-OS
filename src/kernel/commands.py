"""Command registry — centralized shell command definitions with YAML overrides.

Mirrors the pattern from kernel/prompts.py:

  _DEFAULTS  — built-in command definitions (help, aliases, args)
  _overrides — loaded from praxis.yaml → commands: section at boot
  get_command() / list_commands() — public API
  register_command() — code-level handler registration

YAML format:
  commands:
    mode:
      help: "Custom help text"
      aliases: ["m"]
    connect:
      args:
        - name: agent_id
          optional: false
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Argument completion types
ARG_AGENT = "agent"
ARG_ROLE = "role"
ARG_DOMAIN = "domain"

_COMMAND_HANDLERS: dict[str, Callable] = {}

_DEFAULTS: dict[str, dict] = {
    "help": {
        "help": "Show available commands",
        "aliases": [],
        "args": [],
    },
    "agents": {
        "help": "List all agents (preselect)",
        "aliases": ["ls"],
        "args": [],
    },
    "connect": {
        "help": "Connect to an agent (direct mode)",
        "aliases": [],
        "args": [
            {"name": "agent_id", "completer": ARG_AGENT, "optional": False,
             "description": "Target agent ID (tab to list)"},
            {"name": "--role", "completer": ARG_ROLE, "optional": True,
             "description": "Filter by role"},
        ],
    },
    "disconnect": {
        "help": "Disconnect and return to L3A",
        "aliases": ["dc"],
        "args": [],
    },
    "mode": {
        "help": "Show/switch mode (L3A/Direct, tool read/write)",
        "aliases": [],
        "args": [
            {"name": "sub", "completer": "subcommand", "optional": True,
             "description": "'tool' for tool mode"},
            {"name": "tool_mode", "completer": "tool_mode", "optional": True,
             "description": "read|write|toggle"},
        ],
    },
    "status": {
        "help": "Show Cell, agent, and session status",
        "aliases": [],
        "args": [
            {"name": "cell_id", "completer": ARG_AGENT, "optional": True,
             "description": "Cell ID (default: cell-1)"},
        ],
    },
    # ── 9 central control system commands ──
    "intents": {
        "help": "List recent intents (CentralController)",
        "aliases": [],
        "args": [{"name": "status", "completer": "", "optional": True,
                   "description": "Filter by status"}],
    },
    "scheduler": {
        "help": "Show 5D scheduling status (CentralScheduler)",
        "aliases": [],
    },
    "observe": {
        "help": "Observability: alerts/health/metrics (ObservabilityBus)",
        "aliases": [],
        "args": [{"name": "kind", "completer": "", "optional": True,
                   "description": "alert|health|metric|audit"}],
    },
    "skills": {
        "help": "List/view/evolve R4Agent skills",
        "aliases": [],
        "args": [{"name": "sub", "completer": "", "optional": True,
                   "description": "list|lean|evolve <intent>"}],
    },
    "cells": {
        "help": "List cells or show cell health (CellMonitor)",
        "aliases": [],
        "args": [{"name": "cell_id", "completer": ARG_AGENT, "optional": True,
                   "description": "Cell ID or 'list'"}],
    },
    "cross": {
        "help": "Cross-cell coordination status (L3B)",
        "aliases": [],
    },
    "security": {
        "help": "Security stats or run a check (CentralSecurity)",
        "aliases": [],
        "args": [{"name": "sub", "completer": "", "optional": True,
                   "description": "stats|check <action> <agent>"}],
    },
    "memory": {
        "help": "Memory stats or recall (CentralMemory)",
        "aliases": [],
        "args": [{"name": "sub", "completer": "", "optional": True,
                   "description": "stats|recall <query>"}],
    },
    "plugins": {
        "help": "List installed plugins (CentralPlugin)",
        "aliases": [],
        "args": [{"name": "sub", "completer": "", "optional": True,
                   "description": "list|stats"}],
    },
    "mcp": {
        "help": "Manage MCP server connections (MCPBridge)",
        "aliases": [],
        "args": [
            {"name": "sub", "completer": "", "optional": True,
             "description": "status|list|add <name> <endpoint>|remove <name>|disable <name>|enable <name>|prompts <name>|resources <name>"},
        ],
    },
    # ── System commands ──
    "process": {
        "help": "List running processes (ProcessTable)",
        "aliases": ["ps"],
        "args": [{"name": "pid", "completer": "", "optional": True,
                   "description": "Filter by PID"}],
    },
    "vfs": {
        "help": "Virtual filesystem navigation (VFS)",
        "aliases": [],
        "args": [{"name": "path", "completer": "", "optional": True,
                   "description": "Path to list or read (default: /)"},
                 {"name": "--mounts", "completer": "", "optional": True,
                   "description": "List mount points"}],
    },
    "cache": {
        "help": "Show cache statistics (FileCache/LLM)",
        "aliases": [],
        "args": [{"name": "sub", "completer": "", "optional": True,
                   "description": "stats|clear"}],
    },
    "sysinfo": {
        "help": "System information summary (Registry)",
        "aliases": ["info"],
        "args": [],
    },
    "clear": {
        "help": "Clear the terminal screen",
        "aliases": ["clr"],
        "args": [],
    },
    "history": {
        "help": "Show shell command history",
        "aliases": ["hist"],
        "args": [{"name": "limit", "completer": "", "optional": True,
                   "description": "Number of recent entries (default: 20)"}],
    },
    "lang": {
        "help": "Show or switch display language",
        "aliases": [],
        "args": [{"name": "locale", "completer": "", "optional": True,
                   "description": "Target locale code, e.g. en, zh-CN. Omit to show current."}],
    },
    # ── Cluster control commands ──
    "spawn": {
        "help": "Create a new agent in a Cell",
        "aliases": [],
        "args": [
            {"name": "role", "completer": "role", "optional": False,
             "description": "Agent role: writer|reader|security|scout"},
            {"name": "agent_id", "completer": "", "optional": True,
             "description": "Agent ID (auto-generated if omitted)"},
            {"name": "--cell", "completer": "", "optional": True,
             "description": "Target Cell ID (default: cell-1)"},
        ],
    },
    "kill": {
        "help": "Terminate an agent in a Cell",
        "aliases": [],
        "args": [
            {"name": "agent_id", "completer": "agent", "optional": False,
             "description": "Agent ID to terminate"},
        ],
    },
    "destroy": {
        "help": "Remove an entire Cell and all its agents",
        "aliases": [],
        "args": [
            {"name": "cell_id", "completer": "agent", "optional": False,
             "description": "Cell ID to destroy"},
        ],
    },
    "emergency": {
        "help": "Emergency stop — halt all operations in a Cell",
        "aliases": ["halt"],
        "args": [
            {"name": "cell_id", "completer": "agent", "optional": True,
             "description": "Cell ID (default: cell-1)"},
        ],
    },
    "cluster": {
        "help": "Show cluster topology and Cell health overview",
        "aliases": [],
        "args": [],
    },
    # ── System diagnostic commands ──
    "audit": {
        "help": "View syscall audit trail",
        "aliases": [],
        "args": [{"name": "limit", "completer": "", "optional": True,
                   "description": "Number of entries (default: 20)"}],
    },
    "settings": {
        "help": "View runtime system settings",
        "aliases": [],
        "args": [],
    },
    "devices": {
        "help": "List registered kernel devices",
        "aliases": [],
        "args": [],
    },
    "tools": {
        "help": "List all registered tools",
        "aliases": [],
        "args": [{"name": "category", "completer": "", "optional": True,
                   "description": "Filter by category (e.g. generic, mcp)"}],
    },
    "config": {
        "help": "View or reload system configuration",
        "aliases": [],
        "args": [{"name": "sub", "completer": "", "optional": True,
                   "description": "show|reload"}],
    },
    "cron": {
        "help": "Manage cron schedules for repeatable card dispatch",
        "aliases": [],
        "args": [{"name": "sub", "completer": "", "optional": True,
                   "description": "list|add <id> <cron> <intent> [--domain <d>] [--priority <p>]|remove <id>"}],
    },
}

_overrides: dict[str, dict] = {}


def load_command_overrides(cfg: dict) -> None:
    """Load command overrides from praxis.yaml commands: section.

    YAML format:
      commands:
        mode:
          help: "Custom help"
          aliases: ["m"]
        connect:
          args:
            - name: agent_id
              optional: false
    """
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
