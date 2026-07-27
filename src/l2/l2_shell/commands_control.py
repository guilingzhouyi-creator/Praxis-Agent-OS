from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

def _cmd_intents(args: list[str]) -> dict:
    from l3.l3 import get_coordinator
    coord = get_coordinator()
    status = args[0] if args else ""
    return {"success": True, "intents": coord.list_intents(status=status)}

def _cmd_scheduler(args: list[str]) -> dict:
    from l3.scheduler import get_scheduler as _gs
    sched = _gs()
    if hasattr(sched, 'stats'):
        return {"success": True, "stats": sched.stats()}
    return {"success": True, "status": "scheduler active"}

def _cmd_observe(args: list[str]) -> dict:
    from l3.observability_bus import get_obs_bus as _go
    bus = _go()
    kind = args[0] if args else "health"
    return bus.observe(kind, "shell", {})

def _cmd_skills(args: list[str]) -> dict:
    from l3.r4_agent import get_r4_agent
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
    from l3.cell_monitor import get_cell_monitor
    cm = get_cell_monitor()
    sub = args[0] if args else "list"
    if sub == "list":
        return {"success": True, "cells": getattr(cm, 'list_cells', lambda: [])()}
    return cm.get_events(cell_id=sub, limit=20)

def _cmd_cross(args: list[str]) -> dict:
    from l3.l3 import get_coordinator
    coord = get_coordinator()
    return {"success": True, "cross_cell": getattr(coord, 'status', lambda: {})()}

def _cmd_security(args: list[str]) -> dict:
    from l3.central_security import get_center as _sec
    sec = _sec()
    sub = args[0] if args else "stats"
    if sub == "stats":
        return {"success": True, "stats": sec.stats()}
    if sub == "check" and len(args) >= 3:
        return sec.check_all(action=args[1], agent_id=args[2],
                             target=args[3] if len(args) > 3 else "",
                             tool_name=args[4] if len(args) > 4 else "")
    return {"success": False, "error": "usage: /security [stats|check <action> <agent> [target] [tool]]"}


def _execute_memory_op(agent_id: str, op: str, op_args: list[str]) -> dict:
    from l3.memory import get_memory
    from l3.central_memory import get_center as _mem
    mem = _mem()
    mm = get_memory()
    if op == "stats":
        return {"agent": agent_id, "stats": mem.stats()}
    if op == "recall":
        query = " ".join(op_args) if op_args else ""
        results = mem.recall(agent_id=agent_id, query=query, limit=10) if query else []
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
        r = mm._ring(ring_n).status() if hasattr(mm, '_ring') else {"error": "not available"}
        return {"agent": agent_id, "ring": ring_n, "status": r}
    return {"agent": agent_id, "error": f"unknown op: {op}"}

def _cmd_plugins(args: list[str]) -> dict:
    from l3.central_plugin import get_center as _plug
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

def _cmd_memory(args: list[str]) -> dict:
    scope, scope_id, rest = resolve_scope(args)
    op = rest[0] if rest else "stats"
    op_args = rest[1:]
    if op == "stats" and scope == "global":
        from l3.central_memory import get_center as _mem
        return {"success": True, "stats": _mem().stats(), "scope": "global"}
    if op == "recall" and scope == "global":
        from l3.central_memory import get_center as _mem
        query = " ".join(op_args)
        results = _mem().recall(query=query, limit=10)
        return {"success": True, "results": results, "count": len(results), "scope": "global"}
    agents = resolve_agents(scope, scope_id)
    results = {}
    for agent_id in agents:
        try:
            results[agent_id] = _execute_memory_op(agent_id, op, op_args)
        except Exception as e:
            results[agent_id] = {"error": str(e)}
    return {"success": True, "scope": scope, "scope_id": scope_id,
            "agents": len(results), "results": results}

def _cmd_cron(args: list[str]) -> dict:
    from l4.cron_scheduler import get_scheduler as _get_cron
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

def _cmd_think(args: list[str]) -> dict:
    """Manage think quota configuration.

    Usage:
      /think config                          — show current hierarchy
      /think config set <key>=<value>        — set global default
      /think cell <cell_id> set <key>=<value> — override per Cell
      /think cell <cell_id> agent <aid> set   — override per Agent
      /think stats                           — quota usage stats
    """
    from l3.think_registry import get_think_registry
    reg = get_think_registry()
    if not args:
        return reg.stats()

    sub = args[0].lower()
    rest = args[1:]

    # /think config
    if sub == "config":
        if rest and rest[0] == "set":
            for kv in rest[1:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        v = int(v)
                    except ValueError:
                        pass
                    reg.set_global(**{k: v})
            return {"success": True, "global": reg.get_global()}
        return {"success": True, "global": reg.get_global(),
                "cells": {cid: reg.get_cell(cid) for cid in reg.stats().get("cells", {})}}

    # /think stats
    if sub == "stats":
        return reg.stats()

    # /think cell <cell_id> ...
    if sub == "cell" and rest:
        cell_id = rest[0]
        cell_rest = rest[1:]
        if cell_rest and cell_rest[0] == "set":
            cfg = {}
            for kv in cell_rest[1:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        v = int(v)
                    except ValueError:
                        pass
                    cfg[k] = v
            if cfg:
                # Resolve distribution mode if present
                dist = cfg.pop("distribution", None)
                reg.set_cell(cell_id, distribution=dist or "inherit", **cfg)
                # Apply to live Cell instance
                from l3.cell import get_cell
                try:
                    cell = get_cell(cell_id)
                    if hasattr(cell, 'set_think_quota'):
                        cell.set_think_quota(distribution=dist, **cfg)
                except Exception:
                    pass
            return {"success": True, "cell": cell_id,
                    "config": reg.get_cell(cell_id)}

        # /think cell <cell_id> agent <agent_id> set ...
        if len(cell_rest) >= 3 and cell_rest[0] == "agent" and cell_rest[2] == "set":
            agent_id = cell_rest[1]
            for kv in cell_rest[3:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        v = int(v)
                    except ValueError:
                        pass
                    reg.set_agent(cell_id, agent_id, **{k: v})
            return {"success": True, "cell": cell_id, "agent": agent_id,
                    "config": reg.get_agent(cell_id, agent_id)}

        return {"success": True, "cell": cell_id,
                "config": reg.get_cell(cell_id)}

    return {"success": False, "error": "usage: /think [config|cell|stats]"}


def _cmd_htn(args: list[str]) -> dict:
    """/htn [a|b|c] — view HTN instance status"""
    sub = args[0].lower() if args else "a"

    if sub == "a":
        try:
            from l3.htn_a import get_htn_a
            h = get_htn_a()
            return {"success": True, "htn": "A", "methods": len(h._methods)}
        except Exception as e:
            return {"success": False, "error": f"HTN-A not available: {e}"}

    if sub == "b":
        from l3.l3 import get_coordinator
        coord = get_coordinator()
        info = {}
        for comp in coord.b.composites:
            info[comp.composite_id] = {
                "methods": len(comp.htn_b._methods) if hasattr(comp, 'htn_b') and hasattr(comp.htn_b, '_methods') else 0,
            }
        return {"success": True, "htn": "B", "composites": info}

    if sub == "c":
        try:
            from l3.htn_planner import get_service
            h = get_service()
            return {"success": True, "htn": "C", "methods": len(h._methods)}
        except Exception as e:
            return {"success": False, "error": f"HTN-C not available: {e}"}

    return {"success": False, "error": "usage: /htn [a|b|c]"}

