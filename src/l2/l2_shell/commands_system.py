"""System command handlers — extracted from commands.py."""
from __future__ import annotations
import logging
from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.commands import get_command
from l1.kernel.params.agent import DEFAULT_CELL_ID, SIGNAL_TARGET_L3
from l1.kernel.params.system import LOG_TRUNC_2000, LOG_TRUNC_60, SHELL_HISTORY_DEFAULT_LIMIT, SHELL_HISTORY_MAX_LIMIT, SKILL_LEAN_CASES_LIMIT, SYSCALL_AUDIT_CLI_LIMIT
from l3.error_bus import capture
logger = logging.getLogger(__name__)


def _cmd_help(args: list[str]) -> dict:
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


def _cmd_agents(args: list[str]) -> dict:
    from l2.selector import preselect
    return preselect()


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
    from .state import get_state
    state = get_state()
    tool_mode = state.mode
    result = {"mode": tool_mode, "agent_id": state.agent_id or "-", "cell_id": state.cell_id}
    if args:
        from l3.tool_system.tool_mode import set_mode, get_mode
        if args[0] == "tool":
            sub = args[1] if len(args) > 1 else "toggle"
            sr = set_mode(sub)
            result["tool_mode"] = sr
            result["current_tool_mode"] = get_mode()
        else:
            result["error"] = "usage: /mode [tool [read|write|toggle]]"
    else:
        from l3.tool_system.tool_mode import get_mode
        result["current_tool_mode"] = get_mode()
    return result


def _cmd_status(args: list[str]) -> dict:
    from .state import get_state
    state = get_state()
    result = {"mode": state.mode, "cell_id": state.cell_id}
    if state.is_direct():
        result["agent_id"] = state.agent_id
        result["session_id"] = state.session_id
        try:
            from l3.cell import get_cell
            cell = get_cell(state.cell_id)
            result["liveness"] = cell.liveness()
        except Exception as e:
            result["liveness_error"] = str(e)
    return result


def _cmd_intents(args: list[str]) -> dict:
    from l3.cell.peers.l3 import get_coordinator
    coord = get_coordinator()
    status = args[0] if args else ""
    return {"success": True, "intents": coord.list_intents(status=status)}


def _cmd_scheduler(args: list[str]) -> dict:
    from l3.scheduler.scheduler import get_scheduler as _gs
    sched = _gs()
    if hasattr(sched, 'stats'):
        return {"success": True, "stats": sched.stats()}
    return {"success": True, "status": "scheduler active"}


def _cmd_observe(args: list[str]) -> dict:
    from l3.bus.observability_bus import get_obs_bus as _go
    bus = _go()
    kind = args[0] if args else "health"
    return bus.observe(kind, "shell", {})


def _cmd_skills(args: list[str]) -> dict:
    from l3.memory.r4_agent import get_r4_agent
    r4 = get_r4_agent()
    sub = args[0] if args else "list"
    if sub == "lean":
        cases = getattr(r4, 'get_lean_cases', lambda: [])("", limit=SKILL_LEAN_CASES_LIMIT)
        return {"success": True, "lean_cases": cases}
    elif sub == "evolve":
        intent = " ".join(args[1:]) if len(args) > 1 else ""
        if hasattr(r4, 'evolve_skill'):
            return r4.evolve_skill(intent)
        return {"success": False, "error": "evolve not available"}
    stats = getattr(r4, 'stats', lambda: {})()
    return {"success": True, "skills": stats}


def _cmd_htn(args: list[str]) -> dict:
    sub = args[0].lower() if args else "a"

    if sub == "a":
        try:
            from l3.bus.htn_a import get_htn_a
            h = get_htn_a()
            return {"success": True, "htn": "A", "methods": len(h._methods)}
        except Exception as e:
            return {"success": False, "error": f"HTN-A not available: {e}"}

    if sub == "b":
        from l3.cell.peers.l3 import get_coordinator
        coord = get_coordinator()
        info = {}
        for comp in coord.b.composites:
            info[comp.composite_id] = {
                "methods": len(comp.htn_b._methods) if hasattr(comp, 'htn_b') and hasattr(comp.htn_b, '_methods') else 0,
            }
        return {"success": True, "htn": "B", "composites": info}

    if sub == "c":
        try:
            from l3.bus.htn_planner import get_service
            h = get_service()
            return {"success": True, "htn": "C", "methods": len(h._methods)}
        except Exception as e:
            return {"success": False, "error": f"HTN-C not available: {e}"}

    return {"success": False, "error": "usage: /htn [a|b|c]"}


def _cmd_security(args: list[str]) -> dict:
    from l3.services.central_security import get_center as _sec
    sec = _sec()
    sub = args[0] if args else "stats"
    if sub == "stats":
        return {"success": True, "stats": sec.stats()}
    if sub == "check" and len(args) >= 3:
        return sec.check_all(action=args[1], agent_id=args[2],
                             target=args[3] if len(args) > 3 else "",
                             tool_name=args[4] if len(args) > 4 else "")
    return {"success": False, "error": "usage: /security [stats|check <action> <agent> [target] [tool]]"}


def _cmd_plugins(args: list[str]) -> dict:
    from l3.services.central_plugin import get_center as _plug
    plug = _plug()
    sub = args[0] if args else "list"
    if sub == "list":
        return {"success": True, "plugins": plug.list_plugins()}
    return {"success": True, "stats": plug.stats()}


def _cmd_mcp(args: list[str]) -> dict:
    from l4.mcp_bridge import get_bridge, McpClient
    bridge = get_bridge()
    sub = args[0].lower() if args else "status"
    if sub in ("status", "list"):
        return {"success": True, "data": bridge.status()}
    if sub == "add" and len(args) >= 3:
        return bridge.import_server(args[1], McpClient(args[2]))
    if sub == "remove" and len(args) >= 2:
        return bridge.remove_server(args[1])
    if sub == "disable" and len(args) >= 2:
        return bridge.set_disabled(args[1])
    if sub == "enable" and len(args) >= 2:
        return bridge.set_enabled(args[1])
    return {"success": False, "error": "usage: /mcp [status|add <name> <endpoint>|remove <name>|disable <name>|enable <name>]"}


def _cmd_process(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        procs = reg.processes()
        if args and args[0].isdigit():
            pid = int(args[0])
            procs = [p for p in procs if p.get("pid") == pid]
        return {"success": True, "processes": procs, "count": len(procs)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_vfs(args: list[str]) -> dict:
    try:
        from l1.kernel.vfs import get_vfs
        vfs = get_vfs()
        if args and args[0] == "--mounts":
            return {"success": True, "mounts": vfs.mounts()}
        path = args[0] if args else "/"
        r = vfs.list(path)
        if r.get("success"):
            return {"success": True, "path": path, "entries": r.get("entries", []),
                    "count": len(r.get("entries", []))}
        r2 = vfs.read(path)
        if r2.get("success"):
            return {"success": True, "path": path, "content": r2.get("content", "")[:LOG_TRUNC_2000]}
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
        return {"success": True, "stats": stats}
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
        return {"success": True, "history": lines[-limit:], "count": len(lines[-limit:])}
    except Exception:
        return {"success": True, "history": [], "count": 0}


def _cmd_lang(args: list[str]) -> dict:
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
    try:
        from l1.kernel.errors import set_locale as _ke_set
        _ke_set(target)
    except Exception:
        logger.warning("_cmd_locale: failed to set kernel locale: %s", target)
        capture("set kernel locale failed", error_code="E_LOCALE", component="l2", context={"target": target})
    return {"success": True, "locale": target, "available": available}


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
        from l3.cell import reset_cells
        reset_cells()
        return {"success": True, "message": f"Cell '{cell_id}' destroyed (all cells reset)"}
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
        limit = int(args[0]) if args and args[0].isdigit() else SYSCALL_AUDIT_CLI_LIMIT
        return {"success": True, "audit": reg.audit(limit=limit), "count": limit}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_settings(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        return {"success": True, "settings": reg.settings()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_devices(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        return {"success": True, "devices": reg.devices()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_tools(args: list[str]) -> dict:
    try:
        from l3.tool_system.tool_spec import list_tools
        from l2.i18n import get_locale
        category = args[0] if args else None
        locale = get_locale()
        tools = list_tools(category=category, locale=locale)
        return {"success": True, "tools": [{"name": t.name, "description": t.description[:LOG_TRUNC_60],
                                              "ring": t.ring, "category": t.category} for t in tools],
                "count": len(tools)}
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
    from l4.cron_scheduler import get_scheduler as _get_cron
    s = get_scheduler()
    sub = args[0].lower() if args else "list"
    if sub == "list":
        return {"success": True, "schedules": s.list()}
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
        return s.add(eid, cron_expr, intent, domain=domain, priority=priority)
    if sub == "remove" and len(args) >= 2:
        return s.remove(args[1])
    return {"success": False, "error": "usage: /cron [list|add <id> <cron> <intent>|remove <id>]"}


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
    from l3.resource_buffer.manager import get_manager as _bm
    mgr = _bm()
    sub = args[0] if args else "status"
    try:
        if sub == "status":
            return mgr.status()
        if sub == "commit":
            return mgr.commit(args[1] if len(args) > 1 else "")
        if sub == "diff" and len(args) >= 2:
            return mgr.diff(args[1])
        if sub == "discard" and len(args) >= 2:
            return mgr.discard(args[1])
        return {"success": False, "error": "usage: /buffer [status|commit <path>|diff <path>|discard <path>]"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_card(args: list[str]) -> dict:
    from l3.card_pool import get_pool as _cp
    pool = _cp()
    sub = args[0] if args else "list"
    try:
        if sub == "list":
            cat = args[1] if len(args) > 1 else ""
            return pool.list_pool(category=cat)
        if sub == "install" and len(args) >= 2:
            return pool.install_from_url(args[1])
        if sub == "install-file" and len(args) >= 2:
            return pool.install_from_file(args[1])
        if sub == "export" and len(args) >= 2:
            return pool.export_to_file(args[1], args[2] if len(args) > 2 else "")
        if sub == "search" and len(args) >= 2:
            return pool.search_remote(" ".join(args[1:]))
        if sub == "remove" and len(args) >= 2:
            return pool.remove(args[1])
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
        return cell.restart_agent(agent_id)
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_agent_refresh(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /agent refresh <agent_id>  or  /agent refresh <cell_id>.<agent_id>"}
    cell_id, agent_id = _parse_agent_ref(args[0])
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        return cell.reset_agent_context(agent_id)
    except Exception as e:
        return {"success": False, "error": str(e)}



__all__ = ['_cmd_help', '_cmd_agents', '_cmd_connect', '_cmd_disconnect', '_cmd_mode', '_cmd_status', '_cmd_intents', '_cmd_scheduler', '_cmd_observe', '_cmd_skills', '_cmd_htn', '_cmd_security', '_cmd_plugins', '_cmd_mcp', '_cmd_process', '_cmd_vfs', '_cmd_cache', '_cmd_sysinfo', '_cmd_clear', '_cmd_history', '_cmd_lang', '_cmd_spawn', '_cmd_kill', '_cmd_destroy', '_cmd_emergency', '_cmd_audit', '_cmd_settings', '_cmd_devices', '_cmd_tools', '_cmd_config', '_cmd_cron', '_cmd_cell_create', '_cmd_buffer', '_cmd_card', '_cmd_agent_restart', '_cmd_agent_refresh']
