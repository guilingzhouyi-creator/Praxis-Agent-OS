"""Cell/cluster command handlers — extracted from commands.py."""
from __future__ import annotations

import logging

from l1.kernel.params.system import CELL_EVENTS_LIMIT

logger = logging.getLogger(__name__)


def _cmd_cells(args: list[str]) -> dict:
    from l3.cell.components.cell_monitor import get_cell_monitor
    cm = get_cell_monitor()
    sub = args[0] if args else "list"
    if sub == "list":
        return {"success": True, "cells": getattr(cm, 'list_cells', lambda: [])()}
    return cm.get_events(cell_id=sub, limit=CELL_EVENTS_LIMIT)


def _cmd_cross(args: list[str]) -> dict:
    from l3.cell.peers.l3 import get_coordinator
    coord = get_coordinator()
    return {"success": True, "cross_cell": getattr(coord, 'status', lambda: {})()}


def _cmd_cluster(args: list[str]) -> dict:
    """/cluster [status|list|composites|expand|shrink]"""
    sub = args[0].lower() if args else "status"

    if sub == "list":
        try:
            from l3.cell import get_cell
            from l3.cell.components.cell_monitor import get_cell_monitor
            cm = get_cell_monitor()
            cells = getattr(cm, 'list_cells', lambda: [])()
            agents = {}
            for cid in cells:
                try:
                    cell = get_cell(cid)
                    agents[cid] = list(cell._agents.keys()) if hasattr(cell, '_agents') else []
                except Exception:
                    logger.debug("commands_cell: get_cell %s failed, using empty agent list", cid)
                    agents[cid] = []
            return {"success": True, "cells": cells, "agents": agents, "count": len(cells)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    if sub == "status":
        from l3.cell.peers.l3 import get_coordinator
        coord = get_coordinator()
        state = "SINGLE"
        if len(coord._cells) >= 2 and getattr(coord, '_cross_cell_active', False):
            state = "MULTI"
        elif len(coord._cells) >= 2:
            state = "TRANSITIONING"
        return {
            "success": True,
            "state": state,
            "cells": len(coord._cells),
            "composites": len(coord.b.composites),
            "cross_cell_active": getattr(coord, '_cross_cell_active', False),
        }

    if sub == "composites":
        from l3.cell.peers.l3 import get_coordinator
        coord = get_coordinator()
        return {
            "success": True,
            "composites": [c.status() for c in coord.b.composites],
        }

    if sub == "expand" and len(args) >= 2:
        cell_id = args[1]
        territory = args[2].split(",") if len(args) >= 3 else ["."]
        from l3.cell.peers.l3 import get_coordinator
        coord = get_coordinator()
        coord.register_cell(cell_id, territory)
        return {"success": True, "cell_id": cell_id, "composites": len(coord.b.composites)}

    if sub == "shrink" and len(args) >= 2:
        cell_id = args[1]
        from l3.cell.peers.l3 import get_coordinator
        coord = get_coordinator()
        coord._cells = [c for c in coord._cells if c.get("id") != cell_id]
        from l3.bus.l3b import L3B
        new_l3b = L3B()
        for c in coord._cells:
            new_l3b.register(c.get("id", ""), c.get("territory", ["."]))
        coord.b = new_l3b
        coord._cross_cell_active = len(coord._cells) >= 2
        return {"success": True, "removed": cell_id, "remaining": len(coord._cells)}

    return {"success": False, "error": "usage: /cluster [status|composites|expand <id>|shrink <id>]"}
