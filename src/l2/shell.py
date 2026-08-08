"""Terminal service — cross-platform process management.

Platform:
  Windows:   subprocess.PIPE (PowerShell, background, no window)
  Linux/mac: subprocess.PIPE (bash/zsh, background)

Session management extracted to shell_session.py
Tab completion extracted to shell_completer.py
"""

from __future__ import annotations

import logging
import subprocess
from collections import deque

from l1.kernel.params.agent import DEFAULT_CELL_ID, SIGNAL_TARGET_L3
from l1.kernel.params.api import SHELL_CMD_TIMEOUT
from l1.kernel.params.system import (
    LOG_TRUNC_50,
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    SCOUT_FINDINGS_DISPLAY_LIMIT,
    SHELL_AUTOCOMPLETE_DISPLAY_LIMIT,
    TERMINAL_OUTPUT_MAX_LINES,
    TOOL_RESULT_DISPLAY_LIMIT,
)
from l1.kernel.platform import run_shell
from l2.i18n import t
from l3.agent.scout import get_pool as _get_scout_pool
from l3.cell import get_cell as _get_cell
from l3.tool_system.tool_spec import execute_tool_spec, get_tool
from l3.tool_system.tool_spec import execute_tool_spec as _execute_l3_tool
from l3.tool_system.tool_spec import list_tools as _list_tools_

from .shell_completer import TerminalCompleter, get_aliases, get_command_help, get_command_names

logger = logging.getLogger(__name__)

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
        readline.set_completer_delims(" \t\n")
    except ImportError:
        logger.debug("shell: readline unavailable, tab completion disabled")
    history: deque[str] = deque(maxlen=TERMINAL_OUTPUT_MAX_LINES)

    print(t("terminal.banner.title"))
    print(t("terminal.banner.l3a"))
    print(t("terminal.banner.route"))
    print(t("terminal.banner.scout"))
    print(t("terminal.banner.system"))
    print(t("terminal.banner.tool"))
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

        if line == "exit" or line == "q":
            break
        if line in ("clear", "clr"):
            print("\033[2J\033[H", end="")  # ANSI clear screen (cross-platform)
            continue
        if line in ("help", "h"):
            _show_help()
            continue
        if line in ("tools", "tl"):
            _list_tools()
            continue
        if line in ("history", "hist"):
            # deque is already capped at TERMINAL_OUTPUT_MAX_LINES.
            for i, h in enumerate(history, 1):
                print(f"  {i:3d}  {h}")
            continue
        if line in ("status", "st"):
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
                print(t("terminal.l3a.routing", target=target_cell, agent=target_agent, intent=intent))
                _handle_direct(intent, target_agent)
            else:
                _handle_direct(rest, agent_id)
        elif line.startswith("$"):
            _handle_system_command(line[1:].strip())
        else:
            _handle_tool_call(line, agent_id)


def _show_help() -> None:
    """Print command list (first 15 commands) and hint for more."""
    print(t("terminal.help.title"))
    for cmd in get_command_names()[:SHELL_AUTOCOMPLETE_DISPLAY_LIMIT]:
        h = get_command_help().get(cmd, "")
        print(f"  {cmd:<20s} {h}")
    print(
        t(
            "terminal.help.more",
            count=len(get_command_names()) - SHELL_AUTOCOMPLETE_DISPLAY_LIMIT,
        )
    )


def _list_tools() -> None:
    """List all registered tools with descriptions.  Falls back to command names on error."""
    try:
        tools = _list_tools_()
        for tool in tools:
            print(f"  {tool.name:<25s} {tool.description[:LOG_TRUNC_50]}")
        print(t("terminal.tools.total", count=len(tools)))
    except Exception as e:
        logger.warning("shell: list_tools failed (%s), falling back to command list", e)
        for c in get_command_names():
            print(f"  {c}")


def _handle_direct(intent: str, agent_id: str) -> None:
    """Handle a direct session intent (! prefix)."""
    print(t("terminal.l3a.parsing", intent=intent))
    try:
        r = _execute_l3_tool("intent_parse", {"text": intent}, agent_id)
        if r.get("success"):
            card = r.get("data", {})
            print(t("terminal.l3a.card", card_id=card.get("card_id", "?")))
            print(t("terminal.l3a.domain", domain=card.get("domain", "?")))
            print(t("terminal.l3a.agent", agent=card.get("agent_id", "?")))
            print(t("terminal.l3a.type", card_type=card.get("card_type", "?")))
        else:
            print(t("terminal.l3a.error", error=r.get("error", "parse failed")))
    except Exception as e:
        print(t("terminal.l3a.error", error=str(e)))


def _handle_scout(task: str, agent_id: str, cell_id: str) -> None:
    """Commission a Scout for investigation."""
    if not task:
        print(t("terminal.scout.usage"))
        return
    print(t("terminal.scout.commissioning", task=task))
    try:
        cell = _get_cell(cell_id)
        # Check delegation permission gate
        if hasattr(cell, "permission") and cell.permission and not cell.permission.is_visible("scout", agent_id):
            print(t("terminal.scout.disabled", agent=agent_id))
            return
        pool = _get_scout_pool()
        r = pool.commission(agent_id, task)
        print(t("terminal.scout.status", status=r.get("status", "?")))
        findings = r.get("findings", [])
        if findings:
            print(t("terminal.scout.findings", count=len(findings)))
            for f in findings[:SCOUT_FINDINGS_DISPLAY_LIMIT]:
                print(f"    - {str(f)[:LOG_TRUNC_200]}")
        if r.get("error"):
            print(t("terminal.scout.error", error=r["error"]))
    except Exception as e:
        print(t("terminal.scout.error", error=str(e)))


def _handle_system_command(cmd: str) -> None:
    """Execute a raw system command via subprocess (Bash/PowerShell)."""
    if not cmd:
        return
    try:
        proc = run_shell(cmd, timeout=SHELL_CMD_TIMEOUT)
        if proc.stdout:
            for line in proc.stdout.splitlines():
                print(f"  {line}")
        if proc.stderr:
            for line in proc.stderr.splitlines():
                print(t("terminal.sys.stderr", line=line))
        print(t("terminal.sys.exit", code=proc.returncode))
    except subprocess.TimeoutExpired:
        print(t("terminal.sys.timeout", timeout=SHELL_CMD_TIMEOUT))
    except FileNotFoundError:
        print(t("terminal.sys.shell_not_found"))
    except Exception as e:
        print(t("terminal.sys.error", error=str(e)))


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

    print(t("terminal.exec.prefix", tool=tool_name, args=args))
    try:
        spec = get_tool(tool_name)
        if not spec:
            print(t("terminal.exec.unknown_tool", tool=tool_name))
            return
        r = execute_tool_spec(tool_name, args, agent_id)
        if r.get("success"):
            result = r.get("data", r.get("result", r))
            if isinstance(result, dict):
                for k, v in list(result.items())[:TOOL_RESULT_DISPLAY_LIMIT]:
                    print(f"  {k}: {str(v)[:LOG_TRUNC_100]}")
            else:
                print(t("terminal.exec.result", result=str(result)[:LOG_TRUNC_200]))
        else:
            print(t("terminal.exec.error", error=r.get("error", "execution failed")))
    except Exception as e:
        print(t("terminal.exec.error", error=str(e)))


def start_repl(agent_id: str = SIGNAL_TARGET_L3, prompt: str = "") -> None:
    """Start the Agent OS REPL terminal."""
    if not prompt:
        prompt = f"agent@{agent_id}> "
    direct_session(prompt, agent_id)
