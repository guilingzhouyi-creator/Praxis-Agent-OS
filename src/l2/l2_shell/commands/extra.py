from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

def _cmd_cluster(args: list[str]) -> dict:
    from l3.cell.peers.l3 import get_coordinator
    from l1.kernel.params.agent import DEFAULT_CELL_ID
    coord = get_coordinator()
    if not args: return {"success": True, "data": {"state": "single", "cells": []}}
    sub = args[0].lower()
    if sub == "status":
        cells = getattr(coord, 'list_cells', lambda: [])()
        return {"success": True, "data": {"cells": cells}}
    return {"success": False, "error": "usage: /cluster [status]"}

def _cmd_cells(args: list[str]) -> dict:
    from l1.kernel.params.agent import DEFAULT_CELL_ID
    return {"success": True, "cell": DEFAULT_CELL_ID}

def _cmd_cross(args: list[str]) -> dict:
    from l3.cell.peers.l3 import get_coordinator
    return {"success": True, "cross": get_coordinator().cross_cell_active if hasattr(get_coordinator(), 'cross_cell_active') else False}

def _cmd_htn(args: list[str]) -> dict:
    if not args: return {"success": False, "error": "usage: /htn [a|b|status]"}
    sub = args[0].lower()
    if sub == "a":
        from l3.bus.htn_a import get_htn_a; planner = get_htn_a()
        return {"success": True, "methods": len(planner._methods) if hasattr(planner, '_methods') else 0}
    if sub == "status": return {"success": True}
    return {"success": False, "error": "unknown htn subcommand"}

def _cmd_security(args: list[str]) -> dict:
    from l3.services.central_security import get_center
    center = get_center()
    if args and args[0] == "audit": return {"success": True, "audit": center.audit_log() if hasattr(center, 'audit_log') else []}
    return {"success": True, "status": "ok"}

def _cmd_mcp(args: list[str]) -> dict:
    try:
        from l4.mcp_bridge import get_bridge, McpClient
        bridge = get_bridge(); sub = args[0].lower() if args else "status"
        if sub in ("status", "list"): return {"success": True, "data": {"servers": bridge.get_status()}}
        if sub == "enable" and len(args) >= 2: return bridge.set_enabled(args[1])
        if sub == "disable" and len(args) >= 2: return bridge.set_disabled(args[1])
        return {"success": False, "error": "usage: /mcp [status|enable|disable]"}
    except Exception as e:
        capture("extra: cmd failed", error_code="E_CMD", component="l2", context={"error": str(e)})
        return {"success": False, "error": str(e)}

def _cmd_buffer(args: list[str]) -> dict:
    from l3.resource_buffer.manager import get_manager
    mgr = get_manager()
    if args and args[0] == "flush": return {"success": True, "flushed": len(mgr._buffers) if hasattr(mgr, '_buffers') else 0}
    return {"success": True, "buffer": {}}

def _cmd_stats(args: list[str]) -> dict:
    from l1.kernel import get_event_bus
    bus = get_event_bus()
    return {"success": True, "stats": bus.stats()}

def _cmd_think(args: list[str]) -> dict:
    """Inspect or configure think quotas."""
    from l3.scheduler.think_registry import get_think_registry
    reg = get_think_registry()
    if not args:
        return {"success": True, "cells": reg.list_cells()}
    if args[0] == "status":
        return {"success": True, "quotas": reg.all()}
    return {"success": False, "error": "usage: /think [status]"}
