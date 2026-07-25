"""Shell (L2) — human interface layer with command dispatch, mode switching,
output guard, and auto-completion.

Commands:
  /help            List available commands
  /agents          List all agents across Cells (preselect)
  /connect <id>    Select agent and start direct session
  /disconnect      End current direct session
  /mode            Show current mode (L3A / Direct)
  /status          Show session status

Flow:
  Human types "/" → auto-complete hints → select agent
    → preconnect check (Cell + Agent + LLM provider)
    → switch to Direct window → dialogue with output guard
"""

from __future__ import annotations

import logging
import shlex
import time
from typing import Any

from kernel import emit_signal
from kernel.commands import (
    register_command as _register_handler,
    get_command, get_handler, list_commands as _list_defs,
    ARG_AGENT, ARG_ROLE,
)
from kernel.params import DEFAULT_CELL_ID, CENTRAL_ROLES

logger = logging.getLogger(__name__)


def autocomplete(line: str) -> list[dict]:
    """Hierarchical auto-completion based on current input line.

    Empty → all commands
    /con  → complete command name
    /connect <part> → complete first arg (agent list)
    /connect id <part> → complete optional flags
    """
    results = []
    stripped = line.lstrip()
    cmds = _list_defs()

    if not stripped or stripped == "/":
        for c in cmds:
            results.append({
                "type": "command", "value": f"/{c['name']}",
                "help": c["help"], "args": len(c.get("args", [])),
            })
        return results[:15]

    if stripped.startswith("/"):
        parts = stripped[1:].split()
    else:
        parts = stripped.split()

    if len(parts) == 0:
        for c in cmds:
            results.append({
                "type": "command", "value": f"/{c['name']}",
                "help": c["help"],
            })
        return results[:15]

    cmd_name = parts[0].lower()
    cmd_info = get_command(cmd_name)

    if not cmd_info:
        for c in cmds:
            if c["name"].startswith(cmd_name):
                results.append({
                    "type": "command", "value": f"/{c['name']}",
                    "help": c["help"],
                })
        return results[:10]

    args_so_far = parts[1:]
    arg_schema = cmd_info.get("args", [])
    completing_new = stripped.endswith(" ")

    if completing_new:
        arg_idx = len(args_so_far)
    else:
        arg_idx = len(args_so_far) - 1 if args_so_far else 0
        current_part = args_so_far[-1].lower() if args_so_far and not completing_new else ""

    if arg_idx >= len(arg_schema):
        return []

    arg = arg_schema[arg_idx]
    completer = arg.get("completer", "")
    arg_name = arg.get("name", "")
    partial = current_part if not completing_new else ""

    if completer == ARG_AGENT:
        results = _complete_agent(partial, cmd_name)
    elif completer == ARG_ROLE:
        results = _complete_role(partial)
    else:
        results.append({
            "type": "arg_hint", "value": arg_name,
            "help": arg.get("description", ""),
        })

    return results[:10]


def _complete_agent(partial: str, cmd_name: str = "") -> list[dict]:
    """Complete agent IDs from preselect."""
    results = []
    try:
        from .selector import preselect
        roster = preselect()
        for agent in roster.get("agents", []):
            aid = agent.get("agent_id", "")
            role = agent.get("role", "?")
            status = agent.get("status", "?")
            if not partial or partial in aid.lower():
                results.append({
                    "type": "agent", "value": f"{aid}",
                    "help": f"{aid} ({role}) [{status}]",
                })
    except Exception:
        pass
    return results


def _complete_role(partial: str) -> list[dict]:
    """Complete from known roles."""
    known = set(CENTRAL_ROLES)
    results = []
    partial = partial.lower()
    for role in known:
        if not partial or role.startswith(partial):
            results.append({"type": "role", "value": role, "help": ""})
    return results


# ── Shell state ──

class ShellState:
    """Maintains the current Shell session state."""

    def __init__(self):
        self.mode: str = "L3A"        # L3A | DIRECT
        self.cell_id: str = DEFAULT_CELL_ID
        self.agent_id: str = ""
        self.session_id: str = ""
        self._preconnect_cache: dict = {}

    def is_direct(self) -> bool:
        return self.mode == "DIRECT" and bool(self.agent_id)

    def switch_to_direct(self, cell_id: str, agent_id: str,
                         session_id: str = "") -> None:
        self.mode = "DIRECT"
        self.cell_id = cell_id
        self.agent_id = agent_id
        self.session_id = session_id

    def switch_to_l3a(self) -> None:
        self.mode = "L3A"
        self.agent_id = ""
        self.session_id = ""


_shell_state = ShellState()


def get_state() -> ShellState:
    return _shell_state


def reset_state() -> None:
    """Reset ShellState to defaults (for test isolation)."""
    global _shell_state
    _shell_state = ShellState()


# ── PreConnect enhanced — Cell + Agent + LLM provider ──

def preconnect_enhanced(cell_id: str, agent_id: str,
                        message: str = "") -> dict:
    """Three-layer connectivity check before establishing direct session.

    1. Cell liveness
    2. Agent reachability
    3. LLM provider connectivity (can this agent actually call LLM?)
    """
    from .selector import preconnect as _preconnect
    checks = {}

    # Basic preconnect (cell + agent + injection)
    basic = _preconnect(cell_id, agent_id, message)
    checks["preconnect"] = basic
    if not basic.get("allowed"):
        return {"allowed": False, "checks": checks,
                "reason": basic.get("reason", "preconnect_failed")}

    # LLM provider check
    try:
        from .llm import get_engine
        engine = get_engine()
        provider_status = engine.provider_status() if hasattr(engine, 'provider_status') else {}
        checks["llm_provider"] = provider_status
        if provider_status.get("status") == "error":
            return {"allowed": False, "checks": checks,
                    "reason": f'llm_provider_error: {provider_status.get("error", "")}'}
    except ImportError:
        checks["llm_provider"] = {"status": "error", "error": "llm module not available"}
        return {"allowed": False, "checks": checks, "reason": "llm_module_missing"}
    except AttributeError as e:
        checks["llm_provider"] = {"status": "error", "error": str(e)}
        return {"allowed": False, "checks": checks, "reason": f'llm_api_mismatch: {e}'}
    except Exception as e:
        checks["llm_provider"] = {"status": "error", "error": str(e)}
        return {"allowed": False, "checks": checks, "reason": f'llm_unavailable: {e}'}

    return {"allowed": True, "checks": checks}


# ── Output guard — intercept dangerous responses ──

_output_guard_callback: Any = None


def set_output_guard(callback: Any) -> None:
    """Register an output guard callback.

    Called after every direct session response.
    Receives (agent_id: str, response: str) and should return
    {"safe": bool, "reason": str, "replacement": str}.
    """
    global _output_guard_callback
    _output_guard_callback = callback


def guard_output(agent_id: str, response: str) -> dict:
    """Run output guard on agent response. Returns filtered response."""
    if not _output_guard_callback:
        return {"safe": True, "output": response}

    try:
        review = _output_guard_callback(agent_id, response)
        if review.get("safe", True):
            return {"safe": True, "output": response}
        replacement = review.get("replacement", "")
        logger.warning("output guard blocked response from %s: %s",
                       agent_id, review.get("reason", ""))
        return {"safe": False, "output": replacement or response[:100],
                "reason": review.get("reason", "")}
    except Exception as e:
        logger.warning("output guard failed: %s", e)
        return {"safe": True, "output": response}


# ── Command handlers ──

def list_commands() -> list[dict]:
    """Format command list for display (wrapper around kernel.commands)."""
    try:
        from services.i18n import t as _t
    except Exception:
        _t = lambda k, **kw: k
    return [
        {"command": f"/{c['name']}", "help": _t(f"shell.command.{c['name']}", default=c["help"]),
         "aliases": c.get("aliases", []),
         "args": c.get("args", [])}
        for c in _list_defs()
    ]


def _cmd_help(args: list[str]) -> dict:
    try:
        from services.i18n import t as _t
    except Exception:
        _t = lambda k, **kw: k
    return {"success": True, "output": list_commands(), "format": "table"}


def _cmd_agents(args: list[str]) -> dict:
    from .selector import preselect
    return preselect()


def _cmd_connect(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /connect <agent_id>"}

    agent_id = args[0]
    state = get_state()
    cell_id = state.cell_id

    # Security gate: run through CentralSecurity
    try:
        from .central_security import get_center as _get_sec
        sec = _get_sec().check_all(
            action="direct_session",
            agent_id=agent_id,
            target=cell_id,
            tool_name="direct_message",
        )
        if not sec.get("allowed"):
            return {"success": False, "error": "connect blocked by security",
                    "security": sec}
    except Exception as e:
        logger.warning("security check unavailable: %s", e)

    # PreConnect enhanced check
    check = preconnect_enhanced(cell_id, agent_id)
    if not check.get("allowed"):
        return {"success": False, "error": f"connect failed: {check.get('reason')}",
                "checks": check.get("checks", {})}

    # Send first direct message via stdin queue
    try:
        from .cell import get_cell
        cell = get_cell(cell_id)
        r = cell.send_direct_message(agent_id, "Hello")
        if r.get("success"):
            state.switch_to_direct(cell_id, agent_id)
            emit_signal("task_assign", sender="shell", target="l3",
                         data={"event": "direct_mode_entered",
                               "cell_id": cell_id, "agent_id": agent_id})
            return {"success": True, "message": f"Connected to {agent_id}",
                    "card_id": r.get("card_id", ""),
                    "checks": check.get("checks", {})}
        return {"success": False, "error": r.get("error", "send_failed")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_disconnect(args: list[str]) -> dict:
    state = get_state()
    if not state.is_direct():
        return {"success": False, "error": "no active direct session"}
    try:
        from .cell import get_cell
        cell = get_cell(state.cell_id)
        r = cell.close_direct_session(state.agent_id)
        state.switch_to_l3a()
        emit_signal("task_assign", sender="shell", target="l3",
                     data={"event": "l3a_mode_restored"})
        return {"success": True, "message": "Disconnected, returned to L3A mode"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_mode(args: list[str]) -> dict:
    state = get_state()
    tool_mode = state.mode  # L3A/Direct
    result = {"mode": tool_mode, "agent_id": state.agent_id or "-",
              "cell_id": state.cell_id}
    if args:
        from .tool_mode import set_mode, get_mode
        if args[0] == "tool":
            sub = args[1] if len(args) > 1 else "toggle"
            sr = set_mode(sub)
            result["tool_mode"] = sr
            result["current_tool_mode"] = get_mode()
        else:
            result["error"] = "usage: /mode [tool [read|write|toggle]]"
    else:
        from .tool_mode import get_mode
        result["current_tool_mode"] = get_mode()
    return result


def _cmd_status(args: list[str]) -> dict:
    state = get_state()
    result = {"mode": state.mode, "cell_id": state.cell_id}
    if state.is_direct():
        result["agent_id"] = state.agent_id
        result["session_id"] = state.session_id
        try:
            from .cell import get_cell
            cell = get_cell(state.cell_id)
            result["liveness"] = cell.liveness()
        except Exception as e:
            result["liveness_error"] = str(e)
    return result


# ── 9 central control system commands ──

def _cmd_intents(args: list[str]) -> dict:
    """CentralController: list/recent intents."""
    from .l3 import get_coordinator
    coord = get_coordinator()
    status = args[0] if args else ""
    return {"success": True, "intents": coord.list_intents(status=status)}


def _cmd_scheduler(args: list[str]) -> dict:
    """CentralScheduler: show 5D scheduling status."""
    from .scheduler import get_scheduler as _gs
    sched = _gs()
    if hasattr(sched, 'stats'):
        return {"success": True, "stats": sched.stats()}
    return {"success": True, "status": "scheduler active"}


def _cmd_observe(args: list[str]) -> dict:
    """ObservabilityBus: alerts/health/metrics."""
    from .observability_bus import get_obs_bus as _go
    bus = _go()
    kind = args[0] if args else "health"
    return bus.observe(kind, "shell", {})


def _cmd_skills(args: list[str]) -> dict:
    """R4Agent: list evolved skills or lean cases."""
    from .r4_agent import get_r4_agent
    r4 = get_r4_agent()
    sub = args[0] if args else "list"
    if sub == "lean":
        cases = getattr(r4, 'get_lean_cases', lambda: [])("", limit=20)
        return {"success": True, "lean_cases": cases}
    elif sub == "evolve":
        intent = " ".join(args[1:]) if len(args) > 1 else ""
        if hasattr(r4, 'evolve_skill'):
            return r4.evolve_skill(intent)
        return {"success": False, "error": "evolve not available"}
    stats = getattr(r4, 'stats', lambda: {})()
    return {"success": True, "skills": stats}


def _cmd_cells(args: list[str]) -> dict:
    """CellMonitor: list cells or show cell health."""
    from .cell_monitor import get_cell_monitor
    cm = get_cell_monitor()
    sub = args[0] if args else "list"
    if sub == "list":
        return {"success": True, "cells": getattr(cm, 'list_cells', lambda: [])()}
    return cm.get_events(cell_id=sub, limit=20)


def _cmd_cross(args: list[str]) -> dict:
    """L3B: cross-cell coordination status."""
    from .l3 import get_coordinator
    coord = get_coordinator()
    return {"success": True, "cross_cell": getattr(coord, 'status', lambda: {})()}


def _cmd_security(args: list[str]) -> dict:
    """CentralSecurity: stats or run a check."""
    from .central_security import get_center as _sec
    sec = _sec()
    sub = args[0] if args else "stats"
    if sub == "stats":
        return {"success": True, "stats": sec.stats()}
    if sub == "check" and len(args) >= 3:
        return sec.check_all(action=args[1], agent_id=args[2],
                             target=args[3] if len(args) > 3 else "",
                             tool_name=args[4] if len(args) > 4 else "")
    return {"success": False, "error": "usage: /security [stats|check <action> <agent> [target] [tool]]"}


def _cmd_memory(args: list[str]) -> dict:
    """CentralMemory: stats or recall."""
    from .central_memory import get_center as _mem
    mem = _mem()
    sub = args[0] if args else "stats"
    if sub == "stats":
        return {"success": True, "stats": mem.stats()}
    if sub == "recall" and len(args) >= 2:
        results = mem.recall(query=" ".join(args[1:]), limit=10)
        return {"success": True, "results": results, "count": len(results)}
    return {"success": False, "error": "usage: /memory [stats|recall <query>]"}


def _cmd_plugins(args: list[str]) -> dict:
    """CentralPlugin: list plugins."""
    from .central_plugin import get_center as _plug
    plug = _plug()
    sub = args[0] if args else "list"
    if sub == "list":
        return {"success": True, "plugins": plug.list_plugins()}
    return {"success": True, "stats": plug.stats()}


def _cmd_mcp(args: list[str]) -> dict:
    """MCPBridge: manage MCP server connections.

    Subcommands:
      status                  — list all servers with state
      add <name> <endpoint>   — import an MCP server
      remove <name>           — remove an MCP server
      disable <name>          — disable a server
      enable <name>           — re-enable a disabled server
      prompts <name>          — list prompts from an MCP server
      resources <name>        — list resources from an MCP server
    """
    from .mcp_bridge import get_bridge, McpClient
    bridge = get_bridge()
    sub = args[0].lower() if args else "status"

    if sub == "status" or sub == "list":
        return {"success": True, "data": bridge.status()}

    if sub == "add" and len(args) >= 3:
        name = args[1]
        endpoint = args[2]
        client = McpClient(endpoint)
        return bridge.import_server(name, client)

    if sub == "remove" and len(args) >= 2:
        return bridge.remove_server(args[1])

    if sub == "disable" and len(args) >= 2:
        return bridge.set_disabled(args[1])

    if sub == "enable" and len(args) >= 2:
        return bridge.set_enabled(args[1])

    return {"success": False, "error": "usage: /mcp [status|add <name> <endpoint>|remove <name>|disable <name>|enable <name>]"}


def _cmd_process(args: list[str]) -> dict:
    """ProcessTable: list running processes."""
    try:
        from kernel.registry import get_registry
        reg = get_registry()
        procs = reg.processes()
        if args and args[0].isdigit():
            pid = int(args[0])
            procs = [p for p in procs if p.get("pid") == pid]
        return {"success": True, "processes": procs, "count": len(procs)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_vfs(args: list[str]) -> dict:
    """VFS: list directory or mount points."""
    try:
        from kernel.vfs import get_vfs
        vfs = get_vfs()
        if args and args[0] == "--mounts":
            return {"success": True, "mounts": vfs.mounts()}
        path = args[0] if args else "/"
        r = vfs.list(path)
        if r.get("success"):
            return {"success": True, "path": path, "entries": r.get("entries", []),
                    "count": len(r.get("entries", []))}
        # Fallback: try reading as file
        r2 = vfs.read(path)
        if r2.get("success"):
            return {"success": True, "path": path, "content": r2.get("content", "")[:2000]}
        return {"success": False, "error": r.get("error", f"cannot list {path}")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_cache(args: list[str]) -> dict:
    """Cache: show cache stats or clear."""
    try:
        from services.cache import get_llm_cache_stats, reset_caches
        sub = args[0].lower() if args else "stats"
        if sub == "clear":
            reset_caches()
            return {"success": True, "message": "all caches cleared"}
        stats = get_llm_cache_stats()
        return {"success": True, "stats": stats}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_sysinfo(args: list[str]) -> dict:
    """System information summary."""
    try:
        from kernel.registry import get_registry
        reg = get_registry()
        return {"success": True, "summary": reg.summary()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_clear(args: list[str]) -> dict:
    """Clear the terminal screen."""
    return {"success": True, "clear": True}


def _cmd_history(args: list[str]) -> dict:
    """Show shell command history."""
    limit = 20
    if args and args[0].isdigit():
        limit = min(int(args[0]), 200)
    try:
        from services.shell_session import get_manager
        mgr = get_manager()
        lines = mgr.list()
        return {"success": True, "history": lines[-limit:], "count": len(lines[-limit:])}
    except Exception:
        return {"success": True, "history": [], "count": 0}


def _cmd_lang(args: list[str]) -> dict:
    """Show or switch display language."""
    from services.i18n import get_locale, set_locale, get_available_locales, t as _t
    if not args:
        current = get_locale()
        available = get_available_locales()
        return {"success": True, "locale": current, "available": available}
    target = args[0]
    available = get_available_locales()
    if target not in available:
        return {"success": False, "error": _t("shell.error.lang_usage", locales=", ".join(available))}
    set_locale(target)
    # Also update kernel.errors locale
    try:
        from kernel.errors import set_locale as _ke_set
        _ke_set(target)
    except Exception:
        pass
    return {"success": True, "locale": target, "available": available}


def _cmd_spawn(args: list[str]) -> dict:
    """Create a new agent in a Cell."""
    if not args:
        return {"success": False, "error": "usage: /spawn <role> [agent_id] [--cell <cell_id>]"}
    role = args[0]
    agent_id = ""
    cell_id = "cell-1"
    i = 1
    while i < len(args):
        if args[i] == "--cell" and i + 1 < len(args):
            cell_id = args[i + 1]
            i += 2
        else:
            agent_id = args[i]
            i += 1
    try:
        from .cell import get_cell, reset_cells
        cell = get_cell(cell_id)
        aid = agent_id or f"auto-{int(time.time())}"
        cell.add_agent(aid, role=role, territory=["."], auto_boot=True)
        return {"success": True, "message": f"Agent '{aid}' ({role}) spawned in {cell_id}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_kill(args: list[str]) -> dict:
    """Terminate an agent."""
    if not args:
        return {"success": False, "error": "usage: /kill <agent_id>"}
    agent_id = args[0]
    try:
        from .cell import get_cell
        from .cell_types import is_peer
        cell_id = "cell-1"  # could be enhanced to search all cells
        cell = get_cell(cell_id)
        cell.remove_agent(agent_id)
        return {"success": True, "message": f"Agent '{agent_id}' terminated"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_destroy(args: list[str]) -> dict:
    """Remove an entire Cell."""
    if not args:
        return {"success": False, "error": "usage: /destroy <cell_id>"}
    cell_id = args[0]
    try:
        from .cell import reset_cells
        reset_cells()
        return {"success": True, "message": f"Cell '{cell_id}' destroyed (all cells reset)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_emergency(args: list[str]) -> dict:
    """Emergency stop a Cell."""
    cell_id = args[0] if args else "cell-1"
    try:
        from .cell import get_cell
        cell = get_cell(cell_id)
        r = cell.emergency_stop()
        return {"success": True, "message": f"Emergency stop triggered for {cell_id}", "result": r}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_cluster(args: list[str]) -> dict:
    """Show cluster topology and Cell health."""
    try:
        from .cell import get_cell
        from .cell_monitor import get_cell_monitor
        cm = get_cell_monitor()
        cells = getattr(cm, 'list_cells', lambda: [])()
        agents = {}
        for cid in cells:
            try:
                cell = get_cell(cid)
                agents[cid] = list(cell._agents.keys()) if hasattr(cell, '_agents') else []
            except Exception:
                agents[cid] = []
        return {"success": True, "cells": cells, "agents": agents, "count": len(cells)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_audit(args: list[str]) -> dict:
    """View syscall audit trail."""
    try:
        from kernel.registry import get_registry
        reg = get_registry()
        limit = int(args[0]) if args and args[0].isdigit() else 20
        return {"success": True, "audit": reg.audit(limit=limit), "count": limit}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_settings(args: list[str]) -> dict:
    """View runtime system settings."""
    try:
        from kernel.registry import get_registry
        reg = get_registry()
        return {"success": True, "settings": reg.settings()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_devices(args: list[str]) -> dict:
    """List registered kernel devices."""
    try:
        from kernel.registry import get_registry
        reg = get_registry()
        return {"success": True, "devices": reg.devices()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_tools(args: list[str]) -> dict:
    """List all registered tools."""
    try:
        from .tool_spec import list_tools
        from services.i18n import get_locale
        category = args[0] if args else None
        locale = get_locale()
        tools = list_tools(category=category, locale=locale)
        return {"success": True, "tools": [{"name": t.name, "description": t.description[:60],
                                              "ring": t.ring, "category": t.category} for t in tools],
                "count": len(tools)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_config(args: list[str]) -> dict:
    """View or reload system configuration."""
    sub = args[0].lower() if args else "show"
    if sub == "reload":
        try:
            from .config_loader import load as load_config
            cfg = load_config()
            from kernel.commands import load_command_overrides
            load_command_overrides(cfg.get("commands", {}))
            from kernel.prompts import load_prompt_overrides
            load_prompt_overrides(cfg.get("prompts", {}))
            return {"success": True, "message": "configuration reloaded"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    # show
    try:
        from .config_loader import load as load_config
        cfg = load_config()
        return {"success": True, "config": {k: v for k, v in cfg.items() if k in ("kernel", "cell", "llm", "language")}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_cron(args: list[str]) -> dict:
    """Manage cron schedules."""
    from .cron_scheduler import get_scheduler
    s = get_scheduler()
    sub = args[0].lower() if args else "list"
    if sub == "list":
        return {"success": True, "schedules": s.list()}
    if sub == "add" and len(args) >= 4:
        eid = args[1]; cron_expr = args[2]; intent = " ".join(args[3:])
        domain = ""; priority = 5
        if "--domain" in args:
            di = args.index("--domain")
            if di + 1 < len(args): domain = args[di + 1]
        if "--priority" in args:
            pi = args.index("--priority")
            if pi + 1 < len(args):
                try: priority = int(args[pi + 1])
                except: pass
        return s.add(eid, cron_expr, intent, domain=domain, priority=priority)
    if sub == "remove" and len(args) >= 2:
        return s.remove(args[1])
    return {"success": False, "error": "usage: /cron [list|add <id> <cron> <intent>|remove <id>]"}


# Register command handlers with centralized registry
for _name in ("help", "agents", "connect", "disconnect", "mode", "status",
              "intents", "scheduler", "observe", "skills", "cells",
              "cross", "security", "memory", "plugins", "mcp",
              "process", "vfs", "cache", "sysinfo", "clear", "history",
              "lang", "spawn", "kill", "destroy", "emergency", "cluster",
              "audit", "settings", "devices", "tools", "config", "cron"):
    _handler = locals().get(f"_cmd_{_name}")
    if _handler:
        _register_handler(_name, _handler)


# ── Message dispatch ──

def dispatch(text: str) -> dict:
    """Main entry: route user input through Shell.

    /command → execute command
    else     → L3A mode (parse intent) or Direct mode (message agent)
    """
    state = get_state()

    if text.startswith("/"):
        parts = shlex.split(text)
        cmd = parts[0][1:]
        args = parts[1:]
        # Match command or alias
        info = get_command(cmd)
        if info:
            handler = get_handler(cmd)
            if handler:
                return handler(args)
        # Check aliases
        for c in _list_defs():
            if cmd in c.get("aliases", []):
                handler = get_handler(c["name"])
                if handler:
                    return handler(args)
                break
        try:
            from services.i18n import t as _t
            err = _t("shell.error.unknown_command", cmd=cmd)
        except Exception:
            err = f"unknown command: /{cmd}"
        return {"success": False, "error": err,
                "suggestions": [c["name"] for c in _list_defs()]}

    if state.is_direct():
        return _direct_message(state, text)

    return _l3a_intent(text)


def _direct_message(state: ShellState, text: str) -> dict:
    """Send a message in Direct mode via stdin queue.

    On persistent failure (cell/agent unreachable), auto-fallback to L3A
    so the user doesn't get stuck in a broken Direct session.
    """
    try:
        from .cell import get_cell
        cell = get_cell(state.cell_id)
        r = cell.send_direct_message(state.agent_id, text)

        if not r.get("success"):
            _auto_disconnect(state, r.get("error", "send_failed"))
            return r

        response = r.get("output", r.get("answer", ""))
        guarded = guard_output(state.agent_id, response)
        r["raw_answer"] = response
        r["answer"] = guarded["output"]
        r["output_guarded"] = not guarded["safe"]
        return r
    except Exception as e:
        _auto_disconnect(state, str(e))
        return {"success": False, "error": str(e)}


def _auto_disconnect(state: ShellState, reason: str) -> None:
    """Auto-fallback from Direct to L3A when connection is broken."""
    if not state.is_direct():
        return
    logger.warning("auto-disconnect from %s: %s", state.agent_id, reason)
    try:
        from .cell import get_cell
        cell = get_cell(state.cell_id)
        cell.close_direct_session(state.agent_id)
    except Exception:
        pass
    state.switch_to_l3a()
    emit_signal("task_assign", sender="shell", target="l3",
                 data={"event": "l3a_mode_restored_auto",
                       "reason": reason})


def _l3a_intent(text: str) -> dict:
    """Parse intent and submit to CardRegistry in L3A mode."""
    try:
        from .l3 import get_coordinator
        coord = get_coordinator()
        return coord.process_intent(text)
    except Exception as e:
        return {"success": False, "error": str(e)}
