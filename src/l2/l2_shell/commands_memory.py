"""Memory/think/stats command handlers — extracted from commands.py."""
from __future__ import annotations

import logging

from l1.kernel.params.system import MEMORY_RECALL_DEFAULT_LIMIT

logger = logging.getLogger(__name__)


def resolve_scope(args: list[str]) -> tuple[str, str, list[str]]:
    """Parse args to determine scope: global, cell <id>, agent <id>."""
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
    if scope == "global":
        from l3.agent_terminal import get_terminals
        return list(get_terminals().keys())
    if scope == "cell":
        from l3.cell import get_cell, get_cells
        cells = get_cells()
        if scope_id and scope_id in cells:
            return list(cells[scope_id]._agents.keys())
        return [f"{cid}-agent" for cid in cells]
    if scope == "agent" and scope_id:
        return [scope_id]
    return []


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
        r = mm._ring(ring_n).status() if hasattr(mm, '_ring') else {"error": "not available"}
        return {"agent": agent_id, "ring": ring_n, "status": r}
    return {"agent": agent_id, "error": f"unknown op: {op}"}


def _cmd_memory(args: list[str]) -> dict:
    scope, scope_id, rest = resolve_scope(args)
    op = rest[0] if rest else "stats"
    op_args = rest[1:]
    if op == "stats" and scope == "global":
        from l3.memory.central_memory import get_center as _mem
        return {"success": True, "stats": _mem().stats(), "scope": "global"}
    if op == "recall" and scope == "global":
        from l3.memory.central_memory import get_center as _mem
        query = " ".join(op_args)
        results = _mem().recall(query=query, limit=MEMORY_RECALL_DEFAULT_LIMIT)
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


def _cmd_tokens(args: list[str]) -> dict:
    from l3.memory.context_pool import all_cell_totals, cell_total, token_usage
    scope, scope_id, rest = resolve_scope(args)
    sub = rest[0] if rest else "global"
    try:
        if scope == "global" and sub == "global":
            return {"success": True, "tokens": all_cell_totals()}
        if scope == "cell" and scope_id:
            return {"success": True, "cell": cell_total(scope_id)}
        if scope == "agent" and scope_id:
            return {"success": True, "agent": token_usage(scope_id)}
        if sub == "cells":
            return {"success": True, "cells": all_cell_totals().get("cells", [])}
        agents = resolve_agents(scope, scope_id)
        results = {a: token_usage(a).get(a, 0) for a in agents}
        return {"success": True, "scope": scope, "scope_id": scope_id,
                "results": results, "agents": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_stats(args: list[str]) -> dict:
    """Query StatsCenter for tool calls, compression savings, and per-Cell/Agent metrics."""
    from l3.services.stats_center import get_center
    from l3.services.counter import get_counter
    sc = get_center()
    scope, scope_id, rest = resolve_scope(args)
    sub = rest[0] if rest else "tools"
    sub_args = rest[1:]
    window = sub_args[0] if sub_args else "5m"

    try:
        if sub == "agent" and scope == "agent" and scope_id:
            counter = get_counter()
            return {"success": True, "scope": "agent", "agent_id": scope_id,
                    "tools": counter.tool_summary(scope_id),
                    "tokens": counter.token_summary(scope_id),
                    "loops": counter.loop_summary(scope_id)}
        if sub == "cells":
            tags = {"scope": "cell"}
            results = sc.query(tags=tags, window=window)
            return {"success": True, "window": window, "scope": "cells",
                    "metrics": results, "count": len(results)}
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
                    "metrics": results, "count": len(results)}
        if sub == "compression":
            results = sc.query(
                metrics=["memory.compact.saved_tokens",
                         "memory.stub_compact.saved_bytes"],
                tags=tags, window=window)
            return {"success": True, "window": window,
                    "scope": scope, "scope_id": scope_id or "*",
                    "metrics": results, "count": len(results)}
        if sub == "cell" and scope == "cell" and scope_id:
            cell_tags = {"cell": scope_id}
            results = sc.query(tags=cell_tags, window=window)
            try:
                from l3.cell import get_cell
                cell = get_cell(scope_id)
                pmu = getattr(cell, "pmu", None)
                pmu_stats = pmu.stats() if pmu else None
            except Exception:
                logger.warning("commands_memory: PMU stats failed for %s", scope_id)
                pmu_stats = None
            return {"success": True, "cell": scope_id, "window": window,
                    "metrics": results, "pmu_live": pmu_stats, "count": len(results)}
        if sub == "top":
            metric = sub_args[0] if sub_args else "tools.executed.ring_1"
            limit = int(sub_args[1]) if len(sub_args) > 1 else 10
            top_window = sub_args[2] if len(sub_args) > 2 else window
            results = sc.top(metric=metric, limit=limit, window=top_window)
            return {"success": True, "metric": metric, "window": top_window,
                    "results": results, "count": len(results)}
        return {"success": False, "error": f"unknown stats subcommand: {sub}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_think(args: list[str]) -> dict:
    """Manage think quota configuration per cell/agent.

    Usage:
      /think [config|cell|stats]
      /think cell <cell_id> [show|set key=value ...|distribution <mode>]
      /think cell <cell_id> agent <agent_id> set key=value ...
      /think stats [global|cell <cell_id>|agent <agent_id>]
    """
    from l3.scheduler.think_registry import get_think_registry
    reg = get_think_registry()

    if not args:
        return {"success": True, "config": reg.config_summary()}

    cell_rest = args
    if args[0] == "config":
        return {"success": True, "config": reg.config_summary()}

    if args[0] == "stats":
        scope, scope_id, _ = resolve_scope(args[1:])
        if scope == "global":
            return {"success": True, "stats": reg.stats()}
        if scope == "cell" and scope_id:
            return {"success": True, "cell": scope_id, "stats": reg.get_cell(scope_id)}
        if scope == "agent" and scope_id:
            return {"success": True, "agent": scope_id, "stats": reg.get_agent(scope_id)}
        return {"success": False, "error": "usage: /think stats [global|cell <id>|agent <id>]"}

    if args[0] == "cell" and len(args) >= 2:
        cell_id = args[1]
        cell_rest = args[2:]
        if not cell_rest or cell_rest[0] == "show":
            return {"success": True, "cell": cell_id, "config": reg.get_cell(cell_id)}
        if cell_rest[0] == "set":
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
                dist = cfg.pop("distribution", None)
                reg.set_cell(cell_id, distribution=dist or "inherit", **cfg)
                from l3.cell import get_cell
                try:
                    cell = get_cell(cell_id)
                    if hasattr(cell, 'set_think_quota'):
                        cell.set_think_quota(distribution=dist, **cfg)
                except Exception:
                    logger.warning("think cell %s set_think_quota failed", cell_id)
            return {"success": True, "cell": cell_id, "config": reg.get_cell(cell_id)}
        if len(cell_rest) >= 3 and cell_rest[0] == "agent" and cell_rest[2] == "set":
            agent_id = cell_rest[1]
            for kv in cell_rest[3:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    reg.set_agent(cell_id, agent_id, **{k: v})
            return {"success": True, "cell": cell_id, "agent": agent_id,
                    "config": reg.get_agent(cell_id, agent_id)}
        return {"success": True, "cell": cell_id, "config": reg.get_cell(cell_id)}

    return {"success": False, "error": "usage: /think [config|cell|stats]"}
