"""API handler mixin — cell, cell-monitor and peer handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations

from l1.kernel.params.agent import DEFAULT_CELL_ID


def cell_liveness(body: dict | None = None) -> dict:
    """Probe a cell's liveness."""
    try:
        from l3.cell import get_cell

        cell_id = (body or {}).get("cell_id", DEFAULT_CELL_ID)
        cell = get_cell(cell_id)
        return cell.liveness()
    except Exception as e:
        return {"error": str(e), "overall": "unreachable"}


def list_peers(body: dict | None = None) -> dict:
    """List network peers."""
    try:
        from l1.kernel.net import get_net

        return {"peers": get_net().list_peers()}
    except Exception as e:
        return {"peers": [], "error": str(e)}


def cell_stop(body: dict) -> dict:
    """Emergency-stop a cell."""
    try:
        from l3.cell import get_cell

        cell_id = body.get("cell_id", DEFAULT_CELL_ID)
        cell = get_cell(cell_id)
        return cell.emergency_stop()
    except Exception as e:
        return {"error": str(e)}


def cellmon_list(body: dict | None = None) -> dict:
    """List monitored cells + stats."""
    from l3.cell.components.cell_monitor import get_cell_monitor

    cm = get_cell_monitor()
    return {"cells": cm.list_cells(), "stats": cm.stats()}


def cellmon_get(body: dict) -> dict:
    """Get one monitored cell."""
    cid = (body or {}).get("_id", "")
    from l3.cell.components.cell_monitor import get_cell_monitor

    cell = get_cell_monitor().get_cell(cid)
    return {"error": f"cell not found: {cid}"} if not cell else {"cell": cell}


def cellmon_events(body: dict | None = None) -> dict:
    """Get monitored-cell events since a timestamp."""
    b = body or {}
    from l3.cell.components.cell_monitor import get_cell_monitor

    events = get_cell_monitor().get_events(
        cell_id=b.get("cell_id", ""), since=b.get("since", 0.0), limit=b.get("limit", 50)
    )
    return {"events": events, "count": len(events)}


def rollback_context(body: dict | None = None) -> dict:
    """Snapshot rollback ring + card snapshot summary for a cell."""
    try:
        from l3.cell import get_cell

        cell_id = (body or {}).get("cell_id", DEFAULT_CELL_ID)
        cell = get_cell(cell_id)
        ring = cell._rollback_ring
        return {
            "ring_size": len(ring),
            "max_size": 20,
            "recent": ring.all()[-5:] if ring.all() else [],
            "snapshot_count": len(cell._card_snapshots),
        }
    except Exception as e:
        return {"error": str(e)}
