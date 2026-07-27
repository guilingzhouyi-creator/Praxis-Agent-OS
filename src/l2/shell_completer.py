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
    aliases = ["h", "q", "st", "tl", "clr", "hist"]
    return tool_names + builtins + aliases


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
