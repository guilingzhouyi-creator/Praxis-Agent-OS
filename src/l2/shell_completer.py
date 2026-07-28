"""Tab completion for Agent OS terminal commands."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_tool_names() -> list[str]:
    """Get all registered tool names from ToolConfig + built-in commands."""
    tool_names = []
    try:
        from .tool_system.tool_config import ToolConfig as _TC
        tool_names = sorted(_TC.completions().keys())
    except Exception:
        pass
    builtins = ["help", "exit", "clear", "history", "tools", "status"]
    return tool_names + builtins


# ── Shell-level constants (consumed by shell.py REPL) ──

def _load_tool_help() -> dict[str, str]:
    help_map: dict[str, str] = {}
    try:
        from .tool_system.tool_config import ToolConfig as _TC
        for name, meta in _TC.completions().items():
            h = meta.get("help", "") if isinstance(meta, dict) else ""
            help_map[name] = str(h)[:60]
    except Exception:
        pass
    return help_map


_ALIASES: dict[str, str] = {
    "rf": "read_file", "wf": "write_file", "ls": "list_directory",
    "g": "grep", "glob": "glob", "cat": "read_file",
    "h": "help", "q": "exit", "st": "status", "tl": "tools",
    "clr": "clear", "hist": "history",
}
_COMMANDS: list[str] = get_tool_names()
_COMMAND_HELP: dict[str, str] = _load_tool_help()

# ── TerminalCompleter ──

class TerminalCompleter:
    """Tab completion for Agent OS terminal commands."""

    def __init__(self):
        self._commands: list[str] = []

    def refresh(self) -> None:
        self._commands = get_tool_names()

    def complete(self, text: str, state: int) -> str | None:
        try:
            import readline
            if state == 0:
                if ' ' in text:
                    cmd, _, partial = text.rpartition(' ')
                    matches = [p for p in ['.', '..', '/'] if p.startswith(partial)]
                    self._matches = matches
                else:
                    self._matches = [c for c in self._commands if c.startswith(text)]
            return self._matches[state] if state < len(self._matches) else None
        except Exception:
            return None
