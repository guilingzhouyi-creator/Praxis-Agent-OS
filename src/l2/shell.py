"""Terminal service — cross-platform process management.

Platform:
  Windows:   subprocess.PIPE (PowerShell, background, no window)
  Linux/mac: subprocess.PIPE (bash/zsh, background)

Session management extracted to shell_session.py
Tab completion extracted to shell_completer.py
"""

from __future__ import annotations

import os as _os
import subprocess
import time

from l1.kernel.params.agent import DEFAULT_CELL_ID, SIGNAL_TARGET_L3
from l1.kernel.params.api import SHELL_CMD_TIMEOUT
from l1.kernel.params.system import (
    LOG_TRUNC_50, LOG_TRUNC_100, LOG_TRUNC_200,
    SCOUT_FINDINGS_DISPLAY_LIMIT,
    SHELL_AUTOCOMPLETE_DISPLAY_LIMIT,
    TERMINAL_OUTPUT_MAX_LINES,
    TOOL_RESULT_DISPLAY_LIMIT,
)
from l1.kernel.platform import IS_WINDOWS, run_shell
from l3.agent.scout import get_pool as _get_scout_pool
from l3.cell import get_cell as _get_cell
from l3.tool_system.tool_spec import get_tool, execute_tool_spec, list_tools as _list_tools_
from l3.tools_l3 import execute_l3_tool as _execute_l3_tool
from .shell_session import TerminalSession, TerminalManager, get_manager, reset_manager
from .shell_completer import get_command_names, get_aliases, get_command_help, TerminalCompleter, get_tool_names

# ── Terminal REPL — Tab completion, command parsing, direct session ──


def direct_session(prompt: str = "agent> ", agent_id: str = SIGNAL_TARGET_L3, cell_id: str = DEFAULT_CELL_ID) -> None:
    """Direct session loop — human input → L3A → execute → output.

    Commands:
      !<intent>              → L3A direct session (default)
      !<intent>@<cell>/<agent> → Route to specific Cell/Agent
      !scout <task>          → Scout investigation
      $ <command>            → Raw system command (Bash/PowerShell via subprocess)
      <tool> <args>          → Direct tool execution (aliases supported: rf→read_file)
      help                   → Show help
      exit                   → Exit session
    """
    try:
        import readline
        completer = TerminalCompleter()
        completer.refresh()
        readline.set_completer(completer.complete)
        readline.parse_and_bind("tab: complete")
        readline.set_completer_delims(' \t\n')
    except ImportError:
        pass  # No tab completion (e.g. Windows without pyreadline3)
    history: list[str] = []
    history_pos = 0

    print("Agent OS Terminal — Type 'help' for commands, 'exit' to quit")
    print(f"  !<intent>              → L3A direct session")
    print(f"  !<intent>@<cell>/<agent> → Route to specific Cell/Agent")  
    print(f"  !scout <task>          → Scout investigation")
    print(f"  $ <command>            → Raw system command (Bash/PowerShell)")
    print(f"  <tool> <args>          → Tool execution (aliases: rf→read_file)")
    print()

    while True:
        try:
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        history.append(line)
        history_pos = len(history)

        if line == "exit" or line == "q":
            break
        elif line in ("clear", "clr"):
            print("\033[2J\033[H", end="")  # ANSI clear screen (cross-platform)
            continue
        elif line in ("help", "h"):
            _show_help()
            continue
        elif line in ("tools", "tl"):
            _list_tools()
            continue
        elif line in ("history", "hist"):
            for i, h in enumerate(history[-TERMINAL_OUTPUT_MAX_LINES:], 1):
                print(f"  {i:3d}  {h}")
            continue
        elif line in ("status", "st"):
            _handle_tool_call("agent_status", agent_id)
        elif line.startswith("!"):
            rest = line[1:].strip()
            if rest.startswith("scout"):
                _handle_scout(rest[5:].strip(), agent_id, cell_id)
            elif "@" in rest:
                intent, _, route = rest.partition("@")
                parts = route.split("/")
                target_cell = parts[0] if len(parts) > 0 else cell_id
                target_agent = parts[1] if len(parts) > 1 else agent_id
                print(f"  [L3A] Routing to {target_cell}/{target_agent}: {intent}")
                _handle_direct(intent, target_agent)
            else:
                _handle_direct(rest, agent_id)
        elif line.startswith("$"):
            _handle_system_command(line[1:].strip())
        else:
            _handle_tool_call(line, agent_id)


def _show_help() -> None:
    """Print command list (first 15 commands) and hint for more."""
    print("Commands:")
    for cmd in get_command_names()[:SHELL_AUTOCOMPLETE_DISPLAY_LIMIT]:
        h = get_command_help().get(cmd, "")
        print(f"  {cmd:<20s} {h}")
    print(f"  ... and {len(get_command_names()) - SHELL_AUTOCOMPLETE_DISPLAY_LIMIT} more tools (type 'tools' to list all)")


def _list_tools() -> None:
    """List all registered tools with descriptions.  Falls back to command names on error."""
    try:
        tools = _list_tools_()
        for t in tools:
            print(f"  {t.name:<25s} {t.description[:LOG_TRUNC_50]}")
        print(f"\nTotal: {len(tools)} tools")
    except Exception as e:
        logger.warning("shell: list_tools failed (%s), falling back to command list", e)
        for c in get_command_names():
            print(f"  {c}")


def _handle_direct(intent: str, agent_id: str) -> None:
    """Handle a direct session intent (! prefix)."""
    print(f"  [L3A] Parsing: {intent}")
    try:
        r = _execute_l3_tool("intent_parse", {"text": intent}, agent_id)
        if r.get("success"):
            card = r.get("data", {})
            print(f"  [L3A] Card: {card.get('card_id', '?')}")
            print(f"        Domain: {card.get('domain', '?')}")
            print(f"        Agent: {card.get('agent_id', '?')}")
            print(f"        Type: {card.get('card_type', '?')}")
        else:
            print(f"  [L3A] Error: {r.get('error', 'parse failed')}")
    except Exception as e:
        print(f"  [L3A] Error: {e}")


def _handle_scout(task: str, agent_id: str, cell_id: str) -> None:
    """Commission a Scout for investigation."""
    if not task:
        print("  [Scout] Usage: !scout <task>")
        return
    print(f"  [Scout] Commissioning: {task}")
    try:
        cell = _get_cell(cell_id)
        # Check delegation permission gate
        if hasattr(cell, 'permission') and cell.permission:
            if not cell.permission.is_visible("scout", agent_id):
                print(f"  [Scout] Delegation disabled: scout is not available to {agent_id}")
                return
        pool = _get_scout_pool()
        r = pool.commission(agent_id, task)
        print(f"  [Scout] Status: {r.get('status', '?')}")
        findings = r.get("findings", [])
        if findings:
            print(f"  [Scout] Findings ({len(findings)}):")
            for f in findings[:SCOUT_FINDINGS_DISPLAY_LIMIT]:
                print(f"    - {str(f)[:LOG_TRUNC_200]}")
        if r.get("error"):
            print(f"  [Scout] Error: {r['error']}")
    except Exception as e:
        print(f"  [Scout] Error: {e}")


def _handle_system_command(cmd: str) -> None:
    """Execute a raw system command via subprocess (Bash/PowerShell)."""
    if not cmd:
        return
    import subprocess
    import shlex
    try:
        proc = run_shell(cmd, timeout=SHELL_CMD_TIMEOUT)
        if proc.stdout:
            for line in proc.stdout.splitlines():
                print(f"  {line}")
        if proc.stderr:
            for line in proc.stderr.splitlines():
                print(f"  [stderr] {line}")
        print(f"  [Exit] {proc.returncode}")
    except subprocess.TimeoutExpired:
        print(f"  [Error] Command timed out after {SHELL_CMD_TIMEOUT}s")
    except FileNotFoundError:
        print(f"  [Error] Shell not found")
    except Exception as e:
        print(f"  [Error] {e}")


def _handle_tool_call(line: str, agent_id: str) -> None:
    """Handle a direct tool call (tool_name arg1 arg2 ...). Supports aliases."""
    parts = line.split()
    if not parts:
        return
    raw_name = parts[0]
    # Resolve alias
    tool_name = get_aliases().get(raw_name, raw_name)
    args = {}
    for i in range(1, len(parts)):
        if "=" in parts[i]:
            k, v = parts[i].split("=", 1)
            args[k] = v
        elif i < len(parts) - 1:
            args[f"arg{i}"] = parts[i]

    print(f"  [Exec] {tool_name} {args}")
    try:
        spec = get_tool(tool_name)
        if not spec:
            print(f"  [Error] Unknown tool: {tool_name}")
            return
        r = execute_tool_spec(tool_name, args, agent_id)
        if r.get("success"):
            result = r.get("data", r.get("result", r))
            if isinstance(result, dict):
                for k, v in list(result.items())[:TOOL_RESULT_DISPLAY_LIMIT]:
                    print(f"  {k}: {str(v)[:LOG_TRUNC_100]}")
            else:
                print(f"  Result: {str(result)[:LOG_TRUNC_200]}")
        else:
            print(f"  [Error] {r.get('error', 'execution failed')}")
    except Exception as e:
        print(f"  [Error] {e}")


def start_repl(agent_id: str = SIGNAL_TARGET_L3, prompt: str = "") -> None:
    """Start the Agent OS REPL terminal."""
    if not prompt:
        prompt = f"agent@{agent_id}> "
    direct_session(prompt, agent_id)
