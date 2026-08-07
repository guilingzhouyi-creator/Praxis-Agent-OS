"""L2 Shell: extended commands (buffer, cells, cluster, cross, htn, mcp, security, stats, think)."""

from __future__ import annotations

import logging

from l1.kernel.params.system import STATS_TIMELINE_LIMIT, STATS_TOP_LIMIT
from l3.error_bus import capture

logger = logging.getLogger(__name__)


def _cmd_cluster(args: list[str]) -> dict:
    from l3.cell.peers.l3 import get_coordinator

    coord = get_coordinator()
    if not args:
        return {"success": True, "data": {"state": "single", "cells": []}}
    sub = args[0].lower()
    if sub == "status":
        cells: list[dict] = getattr(coord, "list_cells", lambda: [])()
        return {"success": True, "data": {"cells": cells}}
    return {"success": False, "error": "usage: /cluster [status]"}


def _cmd_cells(args: list[str]) -> dict:
    from l1.kernel.params.agent import DEFAULT_CELL_ID

    return {"success": True, "cell": DEFAULT_CELL_ID}


def _cmd_cross(args: list[str]) -> dict:
    from l3.cell.peers.l3 import get_coordinator

    return {
        "success": True,
        "cross": get_coordinator().cross_cell_active if hasattr(get_coordinator(), "cross_cell_active") else False,
    }


def _cmd_htn(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /htn [a|b|status]"}
    sub = args[0].lower()
    if sub == "a":
        from l3.bus.htn_a import get_htn_a

        planner = get_htn_a()
        return {"success": True, "methods": len(planner._methods) if hasattr(planner, "_methods") else 0}
    if sub == "status":
        return {"success": True}
    return {"success": False, "error": "unknown htn subcommand"}


def _cmd_security(args: list[str]) -> dict:
    from l3.services.central_security import get_center

    center = get_center()
    if args and args[0] == "audit":
        return {"success": True, "audit": center.audit_log() if hasattr(center, "audit_log") else []}
    return {"success": True, "status": "ok"}


def _cmd_mcp(args: list[str]) -> dict:
    try:
        from l4.mcp_bridge import get_bridge

        bridge = get_bridge()
        sub = args[0].lower() if args else "status"
        if sub in ("status", "list"):
            data = {"servers": bridge.get_status()}
            try:
                from l4.api_handlers.api_handlers_mcp import get_export_mode, handle_mcp_tools_list

                data["server_mode"] = get_export_mode()
                data["exported_tools"] = handle_mcp_tools_list().get("count", 0)
            except Exception:
                logger.debug("extra: mcp status enrichment failed", exc_info=True)
            return {"success": True, "data": data}
        if sub == "mode" and len(args) >= 2:
            from l4.api_handlers.api_handlers_mcp import set_export_mode

            set_export_mode(args[1])
            return {"success": True, "data": {"server_mode": args[1]}}
        if sub == "enable" and len(args) >= 2:
            return bridge.set_enabled(args[1])
        if sub == "disable" and len(args) >= 2:
            return bridge.set_disabled(args[1])
        return {"success": False, "error": "usage: /mcp [status|mode <normal|selected|full>|enable|disable]"}
    except Exception as e:
        capture("extra: cmd failed", error_code="E_CMD", component="l2", context={"error": str(e)})
        return {"success": False, "error": str(e)}


def _cmd_buffer(args: list[str]) -> dict:
    from l3.resource_buffer.manager import get_manager

    mgr = get_manager()
    if args and args[0] == "flush":
        return {"success": True, "flushed": len(mgr._buffers) if hasattr(mgr, "_buffers") else 0}
    return {"success": True, "buffer": {}}


def _cmd_stats(args: list[str]) -> dict:
    """Query statistics: StatsCenter metrics, card execution timeline,
    side-execution timing, API request timing, reasoning token spend.

    Sub-commands:
      timeline [limit]            card end-to-end timeline (cell + agent breakdown)
      api                         API request latency/count (stats.api.request)
      side [window]               AgentLoop side-execution timing
      reasoning [window]          deliberation costs (reasoning tokens + card exec)
      top <metric> [window]       cross-Cell ranking for a metric
      <tools|compression|cell|agent|cells> [window]   generic StatsCenter query
    """
    sub = args[0].lower() if args else ""
    window = "5m"
    for a in args[1:]:
        if a in ("1m", "5m", "1h", "all"):
            window = a
            break

    if not sub:
        try:
            from l1.kernel import get_event_bus

            bus_stats = get_event_bus().stats()
        except Exception:
            bus_stats = {}
        from l3.services.stats_center import get_center as _sc

        try:
            summary = _sc().stats()
        except Exception:
            summary = {}
        return {"success": True, "event_bus": bus_stats, "metrics": summary}

    if sub == "timeline":
        from l3.card.card_registry import get_registry

        limit = STATS_TIMELINE_LIMIT
        for a in args[1:]:
            if a.isdigit():
                limit = int(a)
                break
        return {"success": True, **get_registry().execution_stats(limit=limit)}

    if sub == "api":
        from l3.services.stats_center import get_center as _sc

        return {
            "success": True,
            "metrics": _sc().query(metrics=["api.request.latency", "api.request.count"], window=window),
        }

    if sub == "side":
        from l3.services.stats_center import get_center as _sc

        return {
            "success": True,
            "metrics": _sc().query(
                metrics=[
                    "agent.loop.side.compression",
                    "agent.loop.side.parallel_read",
                    "agent.loop.side.continuation",
                    "agent.loop.side.llm_tools",
                ],
                window=window,
            ),
        }

    if sub == "reasoning":
        from l3.services.stats_center import get_center as _sc

        return {
            "success": True,
            "metrics": _sc().query(
                metrics=["l3a.tokens.reasoning", "card.execution.total", "card.execution.cell", "card.execution.agent"],
                window=window,
            ),
        }

    if sub == "graph":
        from l3.memory.memory_graph import get_graph

        g = get_graph()
        return {
            "success": True,
            "graph": {
                "enabled": g.enabled,
                "edge_mode": g.edge_mode,
                "stats": g.stats(),
                "semantic": g.semantic_edges(limit=20),
                "compact": g.compact_report(min_degree=2),
            },
        }

    if sub == "top":
        metric = args[1] if len(args) > 1 else "card.execution.total"
        from l3.services.stats_center import get_center as _sc

        return {"success": True, "metric": metric, "ranking": _sc().top(metric, limit=STATS_TOP_LIMIT, window=window)}

    if sub in ("tools", "compression", "cell", "agent", "cells"):
        from l3.services.stats_center import get_center as _sc

        return {"success": True, "metrics": _sc().query(window=window)}

    return {
        "success": False,
        "error": "usage: /stats [timeline [n]|api|side|reasoning|graph"
        "|top <metric>|tools|compression|cell|agent|cells] [1m|5m|1h|all]",
    }


def _cmd_think(args: list[str]) -> dict:
    """Inspect or configure think quotas."""
    from l3.scheduler.think_registry import get_think_registry

    reg = get_think_registry()
    if not args:
        return {"success": True, "cells": reg.list_cells()}
    if args[0] == "status":
        return {"success": True, "quotas": reg.all()}
    return {"success": False, "error": "usage: /think [status]"}
