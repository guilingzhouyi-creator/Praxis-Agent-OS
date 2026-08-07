"""Tab completion for Agent OS terminal commands."""

from __future__ import annotations

import logging

from l1.kernel.params.system import LOG_TRUNC_60

logger = logging.getLogger(__name__)


def get_tool_names() -> list[str]:
    """Get all registered tool names from ToolConfig + built-in commands."""
    tool_names = []
    try:
        from l3.tool_system.tool_config import ToolConfig as ToolConfigCls

        tool_names = sorted(ToolConfigCls.completions().keys())
    except Exception:
        logger.warning("shell_completer: get_tool_names failed")
    builtins = ["help", "exit", "clear", "history", "tools", "status"]
    return tool_names + builtins


# ── Shell-level constants (consumed by shell.py REPL) ──


def _load_tool_help() -> dict[str, str]:
    """Load help text for all registered tools. Returns {tool_name: help_text}."""
    help_map: dict[str, str] = {}
    try:
        from l3.tool_system.tool_config import ToolConfig as ToolConfigCls

        for name, meta in ToolConfigCls.completions().items():
            h = meta.get("help", "") if isinstance(meta, dict) else ""
            help_map[name] = str(h)[:LOG_TRUNC_60]
    except Exception:
        logger.warning("shell_completer: get_help_map failed")
    return help_map


def _load_aliases() -> dict[str, str]:
    """Load shell aliases from config, fall back to built-in."""
    try:
        from l1.kernel.discovery import get_config

        cfg = get_config("shell_aliases")
        if cfg and isinstance(cfg, dict):
            return cfg
    except Exception:
        logger.debug("shell_completer: shell_aliases config lookup failed, using defaults", exc_info=True)
    return {
        "rf": "read_file",
        "wf": "write_file",
        "ls": "list_directory",
        "g": "grep",
        "glob": "glob",
        "cat": "read_file",
        "h": "help",
        "q": "exit",
        "st": "status",
        "tl": "tools",
        "clr": "clear",
        "hist": "history",
    }


# ── Lazy-loaded module-level data (loaded on first access, not at import) ──

_ALIASES: dict[str, str] | None = None
_COMMANDS: list[str] | None = None
_COMMAND_HELP: dict[str, str] | None = None


def get_aliases() -> dict[str, str]:
    """Get shell aliases (lazy-loaded + cached)."""
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = _load_aliases()
    return _ALIASES


def get_command_names() -> list[str]:
    """Get tool names (lazy-loaded + cached)."""
    global _COMMANDS
    if _COMMANDS is None:
        _COMMANDS = get_tool_names()
    return _COMMANDS


def get_command_help() -> dict[str, str]:
    """Get tool help texts (lazy-loaded + cached)."""
    global _COMMAND_HELP
    if _COMMAND_HELP is None:
        _COMMAND_HELP = _load_tool_help()
    return _COMMAND_HELP


# ── TerminalCompleter ──


class TerminalCompleter:
    """Tab completion for Agent OS terminal commands."""

    def __init__(self):
        self._commands: list[str] = []
        self._matches: list[str] = []

    def refresh(self) -> None:
        """Reload the command list from the tool registry."""
        self._commands = get_tool_names()

    def complete(self, text: str, state: int) -> str | None:
        """readline tab completer — matches commands or filesystem paths.

        Called by ``readline.set_completer`` on each tab press.
        ``state == 0`` builds the candidate list; subsequent calls
        return candidates one by one until ``None`` signals end.
        """
        try:
            if state == 0:
                if " " in text:
                    cmd, _, partial = text.rpartition(" ")
                    matches = [p for p in [".", "..", "/"] if p.startswith(partial)]
                    self._matches = matches
                else:
                    self._matches = [c for c in self._commands if c.startswith(text)]
            return self._matches[state] if state < len(self._matches) else None
        except Exception:
            logger.warning("shell_completer: complete() failed")
            return None
