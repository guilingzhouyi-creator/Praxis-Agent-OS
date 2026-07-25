"""Tab completion for Agent OS terminal commands."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_COMMANDS: list[str] = [
    "read_file", "write_file", "create_file", "file_move", "file_copy",
    "file_delete", "file_mkdir", "file_append", "file_search", "list_dir",
    "grep_search", "content_search", "regex_search", "symbol_search",
    "build_project", "test_project", "run_project", "lint",
    "git_commit", "git_push", "git_branch", "git_status",
    "analyze_code", "explain_code", "review_code", "generate_doc",
    "memory_store", "memory_retrieve", "memory_search",
    "agent_heartbeat", "agent_status", "agent_list",
    "backup_create", "backup_list", "backup_restore",
    "workflow_create", "workflow_execute", "workflow_status",
    "deploy_pipeline", "project_audit", "auto_refactor",
    "help", "exit", "clear", "history", "tools", "status",
    "rf", "wf", "ls", "grep", "cat", "build", "test", "h", "q",
]

_ALIASES: dict[str, str] = {
    "rf": "read_file", "wf": "write_file", "ls": "list_dir",
    "cat": "read_file", "grep": "grep_search", "build": "build_project",
    "test": "test_project", "lint": "lint", "doc": "generate_doc",
    "mem": "memory_search", "h": "help", "q": "exit", "st": "status",
    "tl": "tools", "clr": "clear", "hist": "history", "bk": "backup_create",
    "wf": "workflow_create", "sync": "agent_sync", "hb": "agent_heartbeat",
}

_COMMAND_HELP: dict[str, str] = {
    "help": "Show this help. Usage: help [command]",
    "exit": "Exit the terminal", "clear": "Clear screen",
    "history": "Show command history", "tools": "List all available tools",
    "status": "Show agent status",
}


def get_tool_names() -> list[str]:
    """Get all registered tool names from TOOL_REGISTRY."""
    try:
        from .tool_spec import TOOL_REGISTRY
        return list(TOOL_REGISTRY.keys()) + _COMMANDS
    except Exception:
        return _COMMANDS


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
