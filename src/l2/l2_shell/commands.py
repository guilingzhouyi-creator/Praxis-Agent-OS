"""L2 Shell command handlers."""

import functools as _ft
import logging
import re
import shlex
import time
from typing import Any, Callable

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.commands import get_handler as _gh
from l1.kernel.commands import get_registry
from l1.kernel.params.agent import DEFAULT_CELL_ID, SIGNAL_TARGET_L3, AGENT_ROLE_TYPES
from l1.kernel.params.system import (
    CELL_EVENTS_LIMIT,
    CRON_DEFAULT_PRIORITY,
    DEFAULT_CELL_INITIAL_ROLES,
    LOG_TRUNC_60,
    LOG_TRUNC_2000,
    MEMORY_RECALL_DEFAULT_LIMIT,
    SHELL_HISTORY_DEFAULT_LIMIT,
    SHELL_HISTORY_MAX_LIMIT,
    SKILL_LEAN_CASES_LIMIT,
)
from l3.error_bus import capture
from .commands.common import _coerce, _parse_agent_ref, _register_handler, _list_defs, _PIPELINE_SUBST_RE, preconnect_enhanced, list_commands

logger = logging.getLogger(__name__)

_registry = get_registry()


def _cmd_help(args: list[str]) -> dict:
    try:
        if args:
            cmd_name = args[0].lower().lstrip("/")
            cmd = get_command(cmd_name)
            if not cmd:
                return {"success": False, "error": f"unknown command: {cmd_name}"}
            lines = [f"/{cmd_name}  — {cmd.get('help', '')}"]
            if cmd.get("aliases"):
                lines.append(f"  aliases: {', '.join('/' + a for a in cmd['aliases'])}")
            if cmd.get("args"):
                lines.append("  args:")
                for a in cmd["args"]:
                    opt = " (optional)" if a.get("optional") else ""
                    lines.append(f"    {a['name']}{opt} — {a.get('description', '')}")
            if cmd.get("examples"):
                lines.append("  examples:")
                for e in cmd["examples"]:
                    lines.append(f"    {e}")
            lines.append(f"  category: {cmd.get('category', 'other')}")
            return {"success": True, "output": "\n".join(lines), "format": "text"}

        cmds = list_commands()
        groups = {}
        for c in cmds:
            cat = c.get("category", "other")
            groups.setdefault(cat, []).append(c)
        cat_labels = {
            "session": "Session", "control": "Central Control", "memory": "Memory",
            "system": "System", "agent": "Agent / Cell", "audit": "Audit / Config",
            "ext": "Extensions",
        }
        lines = ["Available commands:", ""]
        for cat in ["session", "control", "memory", "system", "agent", "audit", "ext"]:
            items = groups.get(cat, [])
            if not items:
                continue
            label = cat_labels.get(cat, cat)
            lines.append(f"  ── {label} ──")
            for c in items:
                name = c.get("command", "")
                help_text = c.get("help", "")
                alias_str = ""
                if c.get("aliases"):
                    alias_str = f" ({', '.join('/' + a for a in c['aliases'])})"
                lines.append(f"    {name:25s} {help_text}{alias_str}")
            lines.append("")
        lines.append("  Tip: /help <command> for details & examples")
        lines.append("  Tip: cmd1 | cmd2 for pipeline (auto Map/Chain/Passthrough)")
        lines.append("  Tip: --cell or --agent for scoped operations")
        return {"success": True, "output": "\n".join(lines), "format": "text"}
    except Exception as e:
        return {"success": False, "error": str(e)}
def _cmd_agents(args: list[str]) -> dict:
    try:
        from l2.selector import preselect
        return {"success": True, "data": preselect()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_connect(args: list[str]) -> dict:
    from .state import get_state
    if not args:
        return {"success": False, "error": "usage: /connect <agent_id>"}
    agent_id = args[0]
    state = get_state()
    cell_id = state.cell_id
    try:
        from l3.services.central_security import get_center as _get_sec
        sec = _get_sec().check_all(
            action="direct_session", agent_id=agent_id, target=cell_id,
            tool_name="direct_message",
        )
        if not sec.get("allowed"):
            return {"success": False, "error": "connect blocked by security", "security": sec}
    except Exception as e:
        logger.warning("security check unavailable: %s", e)
        return {"success": False, "error": f"security check required but unavailable: {e}"}
    check = preconnect_enhanced(cell_id, agent_id)
    if not check.get("allowed"):
        return {"success": False, "error": f"connect failed: {check.get('reason')}",
                "checks": check.get("checks", {})}
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        r = cell.send_direct_message(agent_id, "Hello")
        if r.get("success"):
            state.switch_to_direct(cell_id, agent_id)
            emit_signal(EVENT_TASK_ASSIGN, sender="shell", target=SIGNAL_TARGET_L3,
                         data={"event": "direct_mode_entered",
                               "cell_id": cell_id, "agent_id": agent_id})
            return {"success": True, "message": f"Connected to {agent_id}",
                    "card_id": r.get("card_id", ""),
                    "checks": check.get("checks", {})}
        return {"success": False, "error": r.get("error", "send_failed")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_disconnect(args: list[str]) -> dict:
    from .state import get_state
    state = get_state()
    if not state.is_direct():
        return {"success": False, "error": "no active direct session"}
    try:
        from l3.cell import get_cell
        cell = get_cell(state.cell_id)
        r = cell.close_direct_session(state.agent_id)
        state.switch_to_l3a()
        emit_signal(EVENT_TASK_ASSIGN, sender="shell", target=SIGNAL_TARGET_L3,
                     data={"event": "l3a_mode_restored"})
        return {"success": True, "message": "Disconnected, returned to L3A mode"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_mode(args: list[str]) -> dict:
    try:
        from .state import get_state
        state = get_state()
        tool_mode = state.mode
        if args:
            from l3.tool_system.tool_mode import set_mode, get_mode
            if args[0] == "tool":
                sub = args[1] if len(args) > 1 else "toggle"
                sr = set_mode(sub)
                return {"success": True, "mode": tool_mode, "agent_id": state.agent_id or "-",
                        "cell_id": state.cell_id, "tool_mode": sr, "current_tool_mode": get_mode()}
            return {"success": False, "error": "usage: /mode [tool [read|write|toggle]]"}
        from l3.tool_system.tool_mode import get_mode
        return {"success": True, "mode": tool_mode, "agent_id": state.agent_id or "-",
                "cell_id": state.cell_id, "current_tool_mode": get_mode()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_status(args: list[str]) -> dict:
    try:
        from .state import get_state
        state = get_state()
        result = {"success": True, "mode": state.mode, "cell_id": state.cell_id}
        if state.is_direct():
            result["agent_id"] = state.agent_id
            result["session_id"] = state.session_id
            from l3.cell import get_cell
            cell = get_cell(state.cell_id)
            result["liveness"] = cell.liveness()
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_intents(args: list[str]) -> dict:
    try:
        from l3.cell.peers.l3 import get_coordinator
        coord = get_coordinator()
        status = args[0] if args else ""
        return {"success": True, "data": coord.list_intents(status=status)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_scheduler(args: list[str]) -> dict:
    try:
        from l3.scheduler.scheduler import get_scheduler as _gs
        sched = _gs()
        if hasattr(sched, 'stats'):
            return {"success": True, "data": sched.stats()}
        return {"success": True, "data": {"status": "scheduler active"}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_observe(args: list[str]) -> dict:
    try:
        from l3.bus.observability_bus import get_obs_bus as _go
        bus = _go()
        kind = args[0] if args else "health"
        return {"success": True, "data": bus.observe(kind, "shell", {})}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_skills(args: list[str]) -> dict:
    try:
        from l3.memory.r4_agent import get_r4_agent
        r4 = get_r4_agent()
        sub = args[0] if args else "list"
        if sub == "lean":
            cases = getattr(r4, 'get_lean_cases', lambda: [])("", limit=SKILL_LEAN_CASES_LIMIT)
            return {"success": True, "data": cases, "count": len(cases)}
        elif sub == "evolve":
            intent = " ".join(args[1:]) if len(args) > 1 else ""
            if hasattr(r4, 'evolve_skill'):
                return {"success": True, "data": r4.evolve_skill(intent)}
            return {"success": False, "error": "evolve not available"}
        stats = getattr(r4, 'stats', lambda: {})()
        return {"success": True, "data": stats}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_cells(args: list[str]) -> dict:
    try:
        from l3.cell.components.cell_monitor import get_cell_monitor
        cm = get_cell_monitor()
        sub = args[0] if args else "list"
        if sub == "list":
            data = getattr(cm, 'list_cells', lambda: [])()
            return {"success": True, "data": data, "count": len(data)}
        return {"success": True, "data": cm.get_events(cell_id=sub, limit=CELL_EVENTS_LIMIT)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_cross(args: list[str]) -> dict:
    try:
        from l3.cell.peers.l3 import get_coordinator
        coord = get_coordinator()
        return {"success": True, "data": getattr(coord, 'status', lambda: {})()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_cluster(args: list[str]) -> dict:
    """/cluster [status|list|composites|expand|shrink]"""
    try:
        sub = args[0].lower() if args else "status"

        if sub == "list":
            from l3.cell import get_cell
            from l3.cell.components.cell_monitor import get_cell_monitor
            cm = get_cell_monitor()
            cells = getattr(cm, 'list_cells', lambda: [])()
            agents = {}
            for cid in cells:
                try:
                    cell = get_cell(cid)
                    agents[cid] = cell.get_agent_ids()
                except Exception as e:
                    logger.warning("_cmd_cluster: cell %s agents failed: %s", cid, e)
                    agents[cid] = []
            return {"success": True, "data": {"cells": cells, "agents": agents}, "count": len(cells)}

        if sub == "status":
            from l3.cell.peers.l3 import get_coordinator
            coord = get_coordinator()
            state = "SINGLE"
            if coord.get_cell_count() >= 2 and coord.is_cross_cell_active():
                state = "MULTI"
            elif coord.get_cell_count() >= 2:
                state = "TRANSITIONING"
            return {"success": True, "data": {"state": state, "cells": coord.get_cell_count(), "composites": len(coord.b.composites), "cross_cell_active": coord.is_cross_cell_active()}}

        if sub == "composites":
            from l3.cell.peers.l3 import get_coordinator
            coord = get_coordinator()
            return {"success": True, "data": [c.status() for c in coord.b.composites]}

        if sub == "expand" and len(args) >= 2:
            cell_id = args[1]
            territory = args[2].split(",") if len(args) >= 3 else ["."]
            from l3.cell.peers.l3 import get_coordinator
            coord = get_coordinator()
            coord.register_cell(cell_id, territory)
            return {"success": True, "data": {"cell_id": cell_id, "composites": len(coord.b.composites)}}

        if sub == "shrink" and len(args) >= 2:
            cell_id = args[1]
            from l3.cell.peers.l3 import get_coordinator
            coord = get_coordinator()
            r = coord.remove_cell(cell_id)
            return {"success": True, "data": r}

        return {"success": False, "error": "usage: /cluster [status|composites|expand <id>|shrink <id>]"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_htn(args: list[str]) -> dict:
    """/htn [a|b|c] — view HTN instance status"""
    try:
        sub = args[0].lower() if args else "a"

        if sub == "a":
            from l3.bus.htn_a import get_htn_a
            h = get_htn_a()
            return {"success": True, "data": {"htn": "A", "methods": len(getattr(h, "_methods", []))}}

        if sub == "b":
            from l3.cell.peers.l3 import get_coordinator
            coord = get_coordinator()
            info = {}
            for comp in coord.b.composites:
                info[comp.composite_id] = {
                    "methods": len(comp.htn_b._methods) if hasattr(comp, 'htn_b') and hasattr(comp.htn_b, '_methods') else 0,
                }
            return {"success": True, "data": {"htn": "B", "composites": info}}

        if sub == "c":
            from l3.bus.htn_planner import get_service
            h = get_service()
            return {"success": True, "data": {"htn": "C", "methods": len(getattr(h, "_methods", []))}}

        return {"success": False, "error": "usage: /htn [a|b|c]"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_security(args: list[str]) -> dict:
    try:
        from l3.services.central_security import get_center as _sec
        sec = _sec()
        sub = args[0] if args else "stats"
        if sub == "stats":
            return {"success": True, "data": sec.stats()}
        if sub == "check" and len(args) >= 3:
            return {"success": True, "data": sec.check_all(action=args[1], agent_id=args[2],
                                 target=args[3] if len(args) > 3 else "",
                                 tool_name=args[4] if len(args) > 4 else "")}
        return {"success": False, "error": "usage: /security [stats|check <action> <agent> [target] [tool]]"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _execute_memory_op(agent_id: str, op: str, op_args: list[str]) -> dict:
    from l3.memory.memory import get_memory
    from l3.memory.central_memory import get_center as _mem
    mem = _mem()
    mm = get_memory()
    if op == "stats":
        return {"agent": agent_id, "stats": mem.stats()}
    if op == "recall":
        query = " ".join(op_args) if op_args else ""
        results = mem.recall(agent_id=agent_id, query=query, limit=MEMORY_RECALL_DEFAULT_LIMIT) if query else []
        return {"agent": agent_id, "results": results, "count": len(results)}
    if op == "store":
        ring = int(op_args[0]) if op_args else 1
        content = " ".join(op_args[1:]) if len(op_args) > 1 else ""
        r = mem.remember(agent_id=agent_id, content=content, ring=ring)
        return {"agent": agent_id, "result": r}
    if op == "compact":
        r = mem.compact(agent_id=agent_id)
        return {"agent": agent_id, "result": r}
    if op == "stub_compact":
        r = mm.stub_compact(agent_id=agent_id)
        return {"agent": agent_id, "result": r}
    if op == "archive":
        r = mem.archive_ring3()
        return {"agent": agent_id, "result": r}
    if op == "forget":
        r = mm.forget_agent(agent_id)
        return {"agent": agent_id, "result": r}
    if op == "ring":
        ring_n = int(op_args[0]) if op_args else 1
        ring_fn = getattr(mm, "_ring", None)
        if ring_fn:
            ring = ring_fn(ring_n)
            status = ring.status() if hasattr(ring, "status") else str(ring)
        else:
            status = {"error": "not available"}
        return {"agent": agent_id, "ring": ring_n, "status": status}
    return {"agent": agent_id, "error": f"unknown op: {op}"}


def resolve_scope(args: list[str]) -> tuple[str, str, list[str]]:
    """Parse args to determine scope: global, cell <id>, agent <id>.
    Returns (scope_type, scope_id, remaining_args).
    """
    if not args:
        return ("global", "", [])
    head = args[0]
    if head == "global" or head.startswith("--"):
        return ("global", "", args)
    if head == "cell" and len(args) >= 2:
        return ("cell", args[1], args[2:])
    if head == "agent" and len(args) >= 2:
        return ("agent", args[1], args[2:])
    return ("agent", head, args[1:])


def resolve_agents(scope: str, scope_id: str) -> list[str]:
    """Resolve scope to a list of agent_ids."""
    if scope == "global":
        from l3.agent_terminal import get_terminals
        return list(get_terminals().keys())
    if scope == "cell":
        from l3.cell import get_cell, get_cells
        cells = get_cells()
        if scope_id and scope_id in cells:
            return cells[scope_id].get_agent_ids()
        return [f"{cid}-agent" for cid in cells]
    if scope == "agent" and scope_id:
        return [scope_id]
    return []


def _cmd_memory(args: list[str]) -> dict:
    try:
        scope, scope_id, rest = resolve_scope(args)
        op = rest[0] if rest else "stats"
        op_args = rest[1:]
        if op == "stats" and scope == "global":
            from l3.memory.central_memory import get_center as _mem
            return {"success": True, "data": _mem().stats(), "scope": "global"}
        if op == "recall" and scope == "global":
            from l3.memory.central_memory import get_center as _mem
            query = " ".join(op_args)
            results = _mem().recall(query=query, limit=MEMORY_RECALL_DEFAULT_LIMIT)
            return {"success": True, "data": results, "count": len(results), "scope": "global"}
        agents = resolve_agents(scope, scope_id)
        data = {}
        for agent_id in agents:
            try:
                data[agent_id] = _execute_memory_op(agent_id, op, op_args)
            except Exception as e:
                data[agent_id] = {"error": str(e)}
        return {"success": True, "scope": scope, "scope_id": scope_id,
                "agents": len(data), "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_plugins(args: list[str]) -> dict:
    try:
        from l3.services.central_plugin import get_center as _plug
        plug = _plug()
        sub = args[0] if args else "list"
        if sub == "list":
            data = plug.list_plugins()
            return {"success": True, "data": data, "count": len(data)}
        return {"success": True, "data": plug.stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_mcp(args: list[str]) -> dict:
    try:
        from l3.services.adapter_bridge import get_mcp_bridge
        bridge, McpClient = get_mcp_bridge()
        sub = args[0].lower() if args else "status"
        if sub in ("status", "list"):
            return {"success": True, "data": bridge.status()}
        if sub == "add" and len(args) >= 3:
            return {"success": True, "data": bridge.import_server(args[1], McpClient(args[2]))}
        if sub == "remove" and len(args) >= 2:
            return {"success": True, "data": bridge.remove_server(args[1])}
        if sub == "disable" and len(args) >= 2:
            return {"success": True, "data": bridge.set_disabled(args[1])}
        if sub == "enable" and len(args) >= 2:
            return {"success": True, "data": bridge.set_enabled(args[1])}
        return {"success": False, "error": "usage: /mcp [status|add <name> <endpoint>|remove <name>|disable <name>|enable <name>]"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_process(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        procs = reg.processes()
        if args and args[0].isdigit():
            pid = int(args[0])
            procs = [p for p in procs if p.get("pid") == pid]
        return {"success": True, "data": procs, "count": len(procs)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_vfs(args: list[str]) -> dict:
    try:
        from l1.kernel.vfs import get_vfs
        vfs = get_vfs()
        if args and args[0] == "--mounts":
            return {"success": True, "data": vfs.mounts()}
        path = args[0] if args else "/"
        r = vfs.list(path)
        if r.get("success"):
            entries = r.get("entries", [])
            return {"success": True, "path": path, "data": entries,
                    "count": len(entries)}
        r2 = vfs.read(path)
        if r2.get("success"):
            return {"success": True, "path": path, "data": r2.get("content", "")[:LOG_TRUNC_2000]}
        return {"success": False, "error": r.get("error", f"cannot list {path}")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_cache(args: list[str]) -> dict:
    try:
        from l3.memory.cache import get_llm_cache_stats, reset_caches
        sub = args[0].lower() if args else "stats"
        if sub == "clear":
            reset_caches()
            return {"success": True, "message": "all caches cleared"}
        stats = get_llm_cache_stats()
        return {"success": True, "data": stats}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_sysinfo(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        return {"success": True, "summary": reg.summary()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_clear(args: list[str]) -> dict:
    return {"success": True, "clear": True}


def _cmd_history(args: list[str]) -> dict:
    limit = SHELL_HISTORY_DEFAULT_LIMIT
    if args and args[0].isdigit():
        limit = min(int(args[0]), SHELL_HISTORY_MAX_LIMIT)
    try:
        from l2.shell_session import get_manager
        mgr = get_manager()
        lines = mgr.list()
        data = lines[-limit:]
        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        logger.warning("_cmd_history: get_manager failed: %s", e)
        return {"success": True, "data": [], "count": 0}


def _cmd_lang(args: list[str]) -> dict:
    try:
        from l2.i18n import get_locale, set_locale, get_available_locales, t as _t
        if not args:
            current = get_locale()
            available = get_available_locales()
            return {"success": True, "locale": current, "available": available}
        target = args[0]
        available = get_available_locales()
        if target not in available:
            return {"success": False, "error": _t("shell.error.lang_usage", locales=", ".join(available))}
        set_locale(target)
        from l1.kernel.errors import set_locale as _ke_set
        _ke_set(target)
        return {"success": True, "locale": target, "available": available}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_spawn(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /spawn <role> [agent_id] [--cell <cell_id>]"}
    role = args[0]
    agent_id = ""
    cell_id = DEFAULT_CELL_ID
    i = 1
    while i < len(args):
        if args[i] == "--cell" and i + 1 < len(args):
            cell_id = args[i + 1]
            i += 2
        else:
            agent_id = args[i]
            i += 1
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        aid = agent_id or f"auto-{int(time.time())}"
        cell.add_agent(aid, role=role, territory=["."], auto_boot=True)
        return {"success": True, "message": f"Agent '{aid}' ({role}) spawned in {cell_id}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_kill(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /kill <agent_id>  or  /kill <cell_id>.<agent_id>"}
    cell_id, agent_id = _parse_agent_ref(args[0])
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        cell.remove_agent(agent_id)
        return {"success": True, "message": f"Agent '{agent_id}' terminated in {cell_id}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_destroy(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /destroy <cell_id>"}
    cell_id = args[0]
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        cell.destroy()
        return {"success": True, "message": f"Cell '{cell_id}' destroyed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_emergency(args: list[str]) -> dict:
    cell_id = args[0] if args else DEFAULT_CELL_ID
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        r = cell.emergency_stop()
        return {"success": True, "message": f"Emergency stop triggered for {cell_id}", "result": r}
    except Exception as e:
        return {"success": False, "error": str(e)}



def _cmd_audit(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        from l1.kernel.params.kernel import REGISTRY_QUERY_LIMIT
        limit = int(args[0]) if args and args[0].isdigit() else REGISTRY_QUERY_LIMIT
        return {"success": True, "data": reg.audit(limit=limit), "count": limit}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_settings(args: list[str]) -> dict:
    """Multi-level settings — global/cell/agent/pool. Delegates to commands_settings."""
    from .commands_settings import _cmd_settings as _cs
    return _cs(args)


def _cmd_devices(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        data = reg.devices()
        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_tools(args: list[str]) -> dict:
    try:
        from l3.tool_system.tool_spec import list_tools
        from l2.i18n import get_locale
        category = args[0] if args else None
        locale = get_locale()
        tools = list_tools(category=category, locale=locale)
        data = [{"name": t.name, "description": t.description[:LOG_TRUNC_60],
                 "ring": t.ring, "category": t.category} for t in tools]
        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_config(args: list[str]) -> dict:
    sub = args[0].lower() if args else "show"
    if sub == "reload":
        try:
            from l3.config.config_loader import load as load_config
            cfg = load_config()
            from l1.kernel.commands import load_command_overrides
            load_command_overrides(cfg.get("commands", {}))
            from l1.kernel.prompts import load_prompt_overrides
            load_prompt_overrides(cfg.get("prompts", {}))
            return {"success": True, "message": "configuration reloaded"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    try:
        from l3.config.config_loader import load as load_config
        cfg = load_config()
        return {"success": True, "config": {k: v for k, v in cfg.items() if k in ("kernel", "cell", "llm", "language")}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_cron(args: list[str]) -> dict:
    try:
        from l3.services.adapter_bridge import get_cron_scheduler
        s = get_scheduler()
        sub = args[0].lower() if args else "list"
        if sub == "list":
            data = s.list()
            return {"success": True, "data": data, "count": len(data)}
        if sub == "add" and len(args) >= 4:
            eid = args[1]; cron_expr = args[2]; intent = " ".join(args[3:])
            domain = ""; priority = CRON_DEFAULT_PRIORITY
            if "--domain" in args:
                di = args.index("--domain")
                if di + 1 < len(args): domain = args[di + 1]
            if "--priority" in args:
                pi = args.index("--priority")
                if pi + 1 < len(args):
                    try: priority = int(args[pi + 1])
                    except (ValueError, IndexError): pass
            return {"success": True, "data": s.add(eid, cron_expr, intent, domain=domain, priority=priority)}
        if sub == "remove" and len(args) >= 2:
            return {"success": True, "data": s.remove(args[1])}
        return {"success": False, "error": "usage: /cron [list|add <id> <cron> <intent>|remove <id>]"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_cell_create(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /cell create <territory>"}
    territory = args[0].strip("/")
    try:
        from l1.kernel.params.agent import CENTRAL_DEFAULT_ROLES, AGENT_ROLE_MAP
        from l3.boot.boot import _create_cell as _boot_create_cell
        # Use config-driven default roles; fallback role from AGENT_ROLE_MAP[3]
        default_role = AGENT_ROLE_MAP.get(3, "default")
        now = int(time.time())
        agent_config = [
            (f"agent-{now}-{i}", role, [territory])
            for i, role in enumerate(CENTRAL_DEFAULT_ROLES[:DEFAULT_CELL_INITIAL_ROLES] or [default_role])
        ]
        r = _boot_create_cell(agent_config)
        return {"success": True, "action": "create_cell", "agents": agent_config,
                "cell_id": r.get("cell_id", "default")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_buffer(args: list[str]) -> dict:
    try:
        from l3.resource_buffer.manager import get_manager as _bm
        mgr = _bm()
        sub = args[0] if args else "status"
        if sub == "status":
            return {"success": True, "data": mgr.status()}
        if sub == "commit":
            return {"success": True, "data": mgr.commit(args[1] if len(args) > 1 else "")}
        if sub == "diff" and len(args) >= 2:
            return {"success": True, "data": mgr.diff(args[1])}
        if sub == "discard" and len(args) >= 2:
            return {"success": True, "data": mgr.discard(args[1])}
        return {"success": False, "error": "usage: /buffer [status|commit <path>|diff <path>|discard <path>]"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_card(args: list[str]) -> dict:
    try:
        from l3.card_pool import get_pool as _cp
        pool = _cp()
        sub = args[0] if args else "list"
        if sub == "list":
            cat = args[1] if len(args) > 1 else ""
            return {"success": True, "data": pool.list_pool(category=cat)}
        if sub == "install" and len(args) >= 2:
            return {"success": True, "data": pool.install_from_url(args[1])}
        if sub == "install-file" and len(args) >= 2:
            return {"success": True, "data": pool.install_from_file(args[1])}
        if sub == "export" and len(args) >= 2:
            return {"success": True, "data": pool.export_to_file(args[1], args[2] if len(args) > 2 else "")}
        if sub == "search" and len(args) >= 2:
            return {"success": True, "data": pool.search_remote(" ".join(args[1:]))}
        if sub == "remove" and len(args) >= 2:
            return {"success": True, "data": pool.remove(args[1])}
        return {"success": False, "error": "usage: /card [list|install <url>|install-file <path>|search <q>|export <name>|remove <name>]"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_agent_restart(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /restart <agent_id>  or  /restart <cell_id>.<agent_id>"}
    cell_id, agent_id = _parse_agent_ref(args[0])
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        return {"success": True, "data": cell.restart_agent(agent_id)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_agent_refresh(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /agent refresh <agent_id>  or  /agent refresh <cell_id>.<agent_id>"}
    cell_id, agent_id = _parse_agent_ref(args[0])
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        return {"success": True, "data": cell.reset_agent_context(agent_id)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_tokens(args: list[str]) -> dict:
    try:
        from l3.memory.context_pool import all_cell_totals, cell_total, token_usage
        scope, scope_id, rest = resolve_scope(args)
        sub = rest[0] if rest else "global"
        if scope == "global" and sub == "global":
            return {"success": True, "data": all_cell_totals()}
        if scope == "cell" and scope_id:
            return {"success": True, "data": cell_total(scope_id)}
        if scope == "agent" and scope_id:
            return {"success": True, "data": token_usage(scope_id)}
        if sub == "cells":
            data = all_cell_totals().get("cells", [])
            return {"success": True, "data": data, "count": len(data)}
        agents = resolve_agents(scope, scope_id)
        results = {a: token_usage(a).get(a, 0) for a in agents}
        return {"success": True, "scope": scope, "scope_id": scope_id,
                "data": results, "agents": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_stats(args: list[str]) -> dict:
    try:
        from l3.services.stats_center import get_center
        from l3.services.counter import get_counter
        sc = get_center()
        scope, scope_id, rest = resolve_scope(args)
        sub = rest[0] if rest else "tools"
        sub_args = rest[1:]
        window = sub_args[0] if sub_args else "5m"

        if sub == "agent" and scope == "agent" and scope_id:
            counter = get_counter()
            return {"success": True, "scope": "agent", "agent_id": scope_id,
                    "data": {"tools": counter.tool_summary(scope_id),
                             "tokens": counter.token_summary(scope_id),
                             "loops": counter.loop_summary(scope_id)}}
        if sub == "cells":
            tags = {"scope": "cell"}
            results = sc.query(tags=tags, window=window)
            return {"success": True, "window": window, "scope": "cells",
                    "data": results, "count": len(results)}
        tags = None
        if scope == "cell" and scope_id:
            tags = {"cell": scope_id}
        elif scope == "global":
            tags = None
        if sub == "tools":
            metrics = ["tools.executed.ring_1", "tools.executed.ring_2_5",
                       "tools.executed.ring_3", "tools.rejected"]
            results = sc.query(metrics=metrics, tags=tags, window=window)
            return {"success": True, "window": window,
                    "scope": scope, "scope_id": scope_id or "*",
                    "data": results, "count": len(results)}
        if sub == "compression":
            results = sc.query(
                metrics=["memory.compact.saved_tokens",
                         "memory.stub_compact.saved_bytes"],
                tags=tags, window=window)
            return {"success": True, "window": window,
                    "scope": scope, "scope_id": scope_id or "*",
                    "data": results, "count": len(results)}
        if sub == "cell" and scope == "cell" and scope_id:
            cell_tags = {"cell": scope_id}
            results = sc.query(tags=cell_tags, window=window)
            pmu_stats = None
            try:
                from l3.cell import get_cell
                cell = get_cell(scope_id)
                pmu = getattr(cell, "pmu", None)
                pmu_stats = pmu.stats() if pmu else None
            except Exception as e:
                logger.warning("commands: PMU stats unavailable for %s: %s", scope_id, e)
            return {"success": True, "cell": scope_id, "window": window,
                    "data": {"metrics": results, "pmu_live": pmu_stats},
                    "count": len(results)}
        if sub == "top":
            metric = sub_args[0] if sub_args else "tools.executed.ring_1"
            from l1.kernel.params.system import TOOL_SEARCH_MAX_RESULTS
            limit = int(sub_args[1]) if len(sub_args) > 1 else TOOL_SEARCH_MAX_RESULTS
            top_window = sub_args[2] if len(sub_args) > 2 else window
            results = sc.top(metric=metric, limit=limit, window=top_window)
            return {"success": True, "metric": metric, "window": top_window,
                    "data": results, "count": len(results)}
        if sub == "l3a":
            """Show L3A assembly status: held cards, convergence queue."""
            from l3.cell.peers.l3a import get_convergence_queue
            from l3.card.card_registry import get_registry
            reg = get_registry()
            stats = reg.stats()
            conv = get_convergence_queue(scope_id or "") if scope == "cell" else []
            return {"success": True, "scope": scope, "scope_id": scope_id or "*",
                    "data": {"registry": stats, "convergence_queue": conv}}
        return {"success": False, "error": f"unknown stats subcommand: {sub}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _pipeline(segments: list[str]) -> dict:
    parts = [shlex.split(s.strip()) for s in segments]

    def _subst(args: list[str], ctx: dict) -> list[str]:
        """Variable substitution: {.key} → ctx[key], {key} → format()."""
        def _replace(m: re.Match) -> str:
            return str(ctx.get(m.group(1), m.group(0)))
        out = []
        for a in args:
            if not isinstance(a, str) or "{" not in a:
                out.append(a)
                continue
            a = _PIPELINE_SUBST_RE.sub(_replace, a)
            a = a.format(**ctx)
            out.append(a)
        return out

    def _build_ctx(result: dict) -> dict:
        ctx = {"scope": result.get("scope", ""), "scope_id": result.get("scope_id", ""),
               "count": str(result.get("agents", result.get("count", 0)))}
        ctx.update({k: str(v) for k, v in result.items()
                   if isinstance(v, (str, int, float, bool))})
        return ctx

    ctx = {}
    last_result = None
    for seg_idx, seg_parts in enumerate(parts):
        if not seg_parts:
            continue
        cmd = seg_parts[0][1:] if seg_parts[0].startswith("/") else seg_parts[0]
        cmd_args = seg_parts[1:]
        handler = _gh(cmd)
        if not handler:
            return {"success": False, "error": f"pipeline: unknown '{cmd}'", "segment": seg_idx}
        if last_result and isinstance(last_result, dict):
            results_dict = last_result.get("results")
            if isinstance(results_dict, dict) and seg_idx > 0:
                aggregated = {}
                for item_key, item_val in results_dict.items():
                    ictx = dict(ctx, key=str(item_key), value=str(item_val)
                                if not isinstance(item_val, (dict, list)) else str(item_key))
                    nargs = _subst(cmd_args, ictx)
                    r = handler(nargs)
                    aggregated[item_key] = r
                return {"success": True, "pipeline": True,
                        "segments": len(parts), "results": aggregated}
            results_list = last_result.get("results")
            if isinstance(results_list, (list, tuple)) and seg_idx > 0:
                aggregated = {}
                for i, item in enumerate(results_list):
                    item_str = str(item) if not isinstance(item, (dict, list)) else str(i)
                    ictx = dict(ctx, key=item_str, value=item_str, index=str(i))
                    nargs = _subst(cmd_args, ictx)
                    r = handler(nargs)
                    aggregated[str(i) if not isinstance(item, str) else item] = r
                return {"success": True, "pipeline": True,
                        "segments": len(parts), "results": aggregated}
        cmd_args = _subst(cmd_args, ctx)
        result = handler(cmd_args)
        if not result.get("success", True):
            return result
        last_result = result
        ctx.update(_build_ctx(result))
    return last_result or {"success": True, "result": ""}


def _cmd_think(args: list[str]) -> dict:
    """Manage think quota configuration per cell/agent.

    Usage:
      /think config                          — show current hierarchy
      /think config set <key>=<value>        — set global default
      /think cell <cell_id> [show|set key=value ...|distribution <mode>]
      /think cell <cell_id> agent <aid> set  — override per Agent
      /think stats [global|cell <id>|agent <id>]
    """
    try:
        from l3.scheduler.think_registry import get_think_registry
        reg = get_think_registry()

        if not args:
            return {"success": True, "data": reg.stats()}

        sub = args[0].lower()
        rest = args[1:]

        # /think config
        if sub == "config":
            if rest and rest[0] == "set":
                for kv in rest[1:]:
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        v = _coerce(v)
                        reg.set_global(**{k: v})
                return {"success": True, "data": reg.get_global()}
            return {"success": True, "data": {"global": reg.get_global(),
                    "cells": {cid: reg.get_cell(cid) for cid in reg.stats().get("cells", {})}}}

        # /think stats [global|cell <id>|agent <id>]
        if sub == "stats":
            if rest and rest[0] == "cell" and len(rest) >= 2:
                return {"success": True, "data": reg.get_cell(rest[1])}
            if rest and rest[0] == "agent" and len(rest) >= 2:
                return {"success": True, "data": reg.get_agent(rest[1])}
            return {"success": True, "data": reg.stats()}

        # /think cell <cell_id> ...
        if sub == "cell" and rest:
            cell_id = rest[0]
            cell_rest = rest[1:]
            if cell_rest and cell_rest[0] == "set":
                cfg = {}
                for kv in cell_rest[1:]:
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        v = _coerce(v)
                        cfg[k] = v
                if cfg:
                    dist = cfg.pop("distribution", None)
                    reg.set_cell(cell_id, distribution=dist or "inherit", **cfg)
                    from l3.cell import get_cell
                    try:
                        cell = get_cell(cell_id)
                        if hasattr(cell, 'set_think_quota'):
                            cell.set_think_quota(distribution=dist, **cfg)
                    except Exception:
                        logger.warning("think cell %s set_think_quota failed", cell_id)
                        capture("set_think_quota failed", error_code="E_THINK", component="l2", context={"cell_id": cell_id})
                return {"success": True, "data": {"cell": cell_id, "config": reg.get_cell(cell_id)}}

            if len(cell_rest) >= 3 and cell_rest[0] == "agent" and cell_rest[2] == "set":
                agent_id = cell_rest[1]
                for kv in cell_rest[3:]:
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        v = _coerce(v)
                        reg.set_agent(cell_id, agent_id, **{k: v})
                return {"success": True, "data": {"cell": cell_id, "agent": agent_id, "config": reg.get_agent(cell_id, agent_id)}}

            return {"success": True, "data": {"cell": cell_id, "config": reg.get_cell(cell_id)}}

        return {"success": False, "error": "usage: /think [config|cell|stats]"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_model(args: list[str]) -> dict:
    """Manage LLM model providers and model specs.

    Usage:
      /model list                          — list registered providers
      /model status                        — show current model specs for all roles
      /model switch <role> <provider> [model] — switch model for a role
      /model health [provider]             — test provider connectivity
      /model set <role> <key> <value>      — set a model spec parameter

    Roles: peer_agent, subagent, scout, r4_agent, convention, card_planner, l3a
    """
    if not args:
        return {"success": False, "error": "usage: /model [list|status|switch|health|set]"}

    sub = args[0]
    try:
        if sub == "list":
            return _model_list()
        elif sub == "status":
            return _model_status()
        elif sub == "switch" and len(args) >= 3:
            return _model_switch(args[1], args[2], args[3] if len(args) > 3 else "")
        elif sub == "health":
            return _model_health(args[1] if len(args) > 1 else "")
        elif sub == "set" and len(args) >= 4:
            return _model_set(args[1], args[2], args[3])
        else:
            return {"success": False, "error": f"unknown /model subcommand: {sub}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _model_list() -> dict:
    """List all registered LLM providers."""
    try:
        from l1.kernel.model_registry import get_registry
        reg = get_registry()
        providers = reg.list_providers() if hasattr(reg, "list_providers") else []
    except Exception as e:
        return {"success": False, "error": str(e)}

    from l3.services.adapter_bridge import export_vault_status
    vault = export_vault_status()

    lines = [f"Providers ({len(providers)} registered):"]
    for p in providers:
        if isinstance(p, str):
            lines.append(f"  {p}")
        else:
            lines.append(f"  {str(p)}")
    lines.append(f"")
    lines.append(f"Vault: {vault.get('providers', 0)} providers, {vault.get('total_keys', 0)} keys")
    return {"success": True, "output": "\n".join(lines)}


def _model_status() -> dict:
    """Show current model specs for all roles."""
    from l3.services.model_service import get_service
    from l3.config.settings_center import get_center

    sc = get_center()
    all_ = sc.all() if hasattr(sc, "all") else {}
    model_specs = {k: v for k, v in all_.items() if k.startswith("model_spec.")}
    ms = get_service()

    lines = ["Active Model Specs:"]
    for key, value in sorted(model_specs.items()):
        spec_name = key.removeprefix("model_spec.")
        lines.append(f"  {spec_name:45s} = {value}")

    lines.append("")
    lines.append("Resolved Configs:")
    for role in AGENT_ROLE_TYPES:
        try:
            cfg = ms.resolve(role)
            lines.append(f"  {role:25s} → provider={cfg.provider:15s} model={cfg.model}")
        except Exception:
            lines.append(f"  {role:25s} → (error)")

    return {"success": True, "output": "\n".join(lines)}


def _model_switch(role: str, provider: str, model: str = "") -> dict:
    """Switch model for a role at runtime."""
    from l3.services.model_service import get_service
    ms = get_service()
    role_key = role.replace("-", "_")
    if role_key in ("peer_agent", "scout", "r4_agent", "convention", "card_planner", "l3a"):
        key_prefix = f"model_spec.{role_key}"
    elif role_key.startswith("subagent."):
        key_prefix = f"model_spec.subagent.specs.{role_key.removeprefix('subagent.')}"
    else:
        return {"success": False, "error": f"unknown role: {role}"}

    from l3.config.settings_center import get_center
    sc = get_center()
    sc.set(f"{key_prefix}.provider", provider)
    if model:
        sc.set(f"{key_prefix}.model", model)

    # Notify via EventBus for SSE broadcast
    try:
        from l1.kernel import get_event_bus
        get_event_bus().emit_event("settings.updated", data={"key": key_prefix, "provider": provider, "model": model})
    except Exception:
        logger.warning("_cmd_model: failed to emit settings.updated event")
        capture("emit settings.updated failed (model)", error_code="E_EMIT", component="l2", context={"role": role})

    return {"success": True, "output": f"Switched {role} to provider={provider} model={model or '(unchanged)'}"}


def _model_health(provider: str = "") -> dict:
    """Test provider connectivity."""
    from l3.services.model_service import get_service
    ms = get_service()
    if provider:
        result = ms.health_check(provider)
        return {"success": result.get("status") == "ok", "output": f"Provider {provider}: {result}"}

    from l1.kernel.model_registry import get_registry
    reg = get_registry()
    providers = reg.list_providers() if hasattr(reg, "list_providers") else []
    lines = []
    for name in providers:
        try:
            h = ms.health_check(name)
            status = "✅" if h.get("status") == "ok" else "❌"
            lines.append(f"  {status} {name:20s} {h.get('message', '')}")
        except Exception as e:
            lines.append(f"  ❌ {name:20s} {e}")
    return {"success": True, "output": "\n".join(lines)}


def _model_set(role: str, key: str, value: str) -> dict:
    """Set a model spec parameter for a role."""
    role_key = role.replace("-", "_")
    if role_key in ("peer_agent", "scout", "r4_agent", "convention", "card_planner", "l3a"):
        prefix = f"model_spec.{role_key}"
    elif role_key.startswith("subagent."):
        prefix = f"model_spec.subagent.specs.{role_key.removeprefix('subagent.')}"
    else:
        return {"success": False, "error": f"unknown role: {role}"}

    from l3.config.settings_center import get_center
    sc = get_center()
    sc.set(f"{prefix}.{key}", value)

    try:
        from l1.kernel import get_event_bus
        get_event_bus().emit_event("settings.updated", data={"prefix": prefix, "key": key, "value": value})
    except Exception:
        logger.warning("_cmd_config: failed to emit settings.updated event")
        capture("emit settings.updated failed (config)", error_code="E_EMIT", component="l2", context={"prefix": prefix, "key": key})

    return {"success": True, "output": f"Set {role}.{key} = {value}"}


# ── System command registration ──────────────────────────────────
# Decorator: @system_command marks a function as a system shell command.

_SYSTEM_COMMANDS: list[tuple[str, Callable]] = []


def system_command(name: str, metadata: dict | None = None):
    """Decorator that marks a function as a system shell command.
    Usage:
      @system_command("mycmd", metadata={"help": "..."})
      def _cmd_mycmd(args): ...
    """
    def _wrapper(fn):
        _SYSTEM_COMMANDS.append((name, fn, metadata or {}))
        @_ft.wraps(fn)
        def _inner(*a, **kw): return fn(*a, **kw)
        return _inner
    return _wrapper


# Load command definitions from commands.yaml
try:
    from l1.kernel.commands import get_registry
    _reg = get_registry()
    _reg.load_defaults()
except Exception:
    logger.warning("failed to load default commands from commands.yaml")
    capture("load default commands failed", error_code="E_CMD_INIT", component="l2")

# Apply @system_command decorators to all _cmd_* functions.
# This must run AFTER all _cmd_* functions are defined.
# Filter: only register module-level callable functions, skip inner/nested ones.
for _cmd_name in dir():
    if _cmd_name.startswith("_cmd_"):
        _fn = locals().get(_cmd_name)
        if not callable(_fn):
            continue
        # Skip inner/nested functions whose __name__ differs from the module name
        if getattr(_fn, "__name__", "") != _cmd_name:
            continue
        # Only auto-register if NOT already registered via @system_command
        _already = any(n == _cmd_name[5:] for n, _, _ in _SYSTEM_COMMANDS)
        if not _already:
            _SYSTEM_COMMANDS.append((_cmd_name[5:], _fn, {}))

for _name, _fn, _meta in _SYSTEM_COMMANDS:
    try:
        _reg.register_system(_name, _fn, metadata=_meta or None)
    except Exception as _e:
        logging.getLogger(__name__).warning("cmd register %s: %s", _name, _e)
