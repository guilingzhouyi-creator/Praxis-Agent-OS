"""Cluster API handlers — multi-cell orchestration endpoints.

Exposes:
  GET  /api/cluster/status     → cluster_state + composites
  GET  /api/cluster/composites → list L3B composites
  POST /api/cluster/expand     → register new Cell
  POST /api/cluster/shrink     → remove Cell + cleanup composites

References routes registered in api_routes.py under "# Cluster".
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def cluster_status(body: dict | None = None) -> dict:
    """GET /api/cluster/status — current cluster state + composites overview."""
    from l3.l3 import get_coordinator
    coord = get_coordinator()
    state_name = "SINGLE"
    if len(coord._cells) >= 2 and getattr(coord, '_cross_cell_active', False):
        state_name = "MULTI"
    elif len(coord._cells) >= 2:
        state_name = "TRANSITIONING"
    composites = []
    for comp in coord.b.composites:
        s = comp.status()
        composites.append({
            "composite_id": s["composite_id"],
            "active": s["active"],
            "prev_cell": s["prev_cell"],
            "next_cell": s["next_cell"],
            "pending_cards": s["pending_cards"],
            "completed_cards": s["completed_cards"],
        })
    return {
        "success": True,
        "state": state_name,
        "cell_count": len(coord._cells),
        "composite_count": len(coord.b.composites),
        "composites": composites,
        "cross_cell_active": getattr(coord, '_cross_cell_active', False),
    }


def cluster_composites(body: dict | None = None) -> dict:
    """GET /api/cluster/composites — detailed L3B composite list."""
    from l3.l3 import get_coordinator
    coord = get_coordinator()
    items = []
    for comp in coord.b.composites:
        items.append(comp.status())
    return {"success": True, "composites": items}


def cluster_expand(body: dict) -> dict:
    """POST /api/cluster/expand — register a new Cell into the cluster.

    Body:
      cell_id: str (required)
      territory: list[str] (optional)
      agents: list[str] (optional)
    """
    cell_id = (body or {}).get("cell_id", "")
    if not cell_id:
        return {"success": False, "error": "cell_id required"}
    territory = (body or {}).get("territory", ["."])
    agents = (body or {}).get("agents")

    from l3.l3 import get_coordinator
    coord = get_coordinator()
    coord.register_cell(cell_id, territory, agents)

    return {
        "success": True,
        "cell_id": cell_id,
        "territory": territory,
        "composite_count": len(coord.b.composites),
    }


def cluster_shrink(body: dict) -> dict:
    """POST /api/cluster/shrink — remove a Cell + cleanup composites.

    Body:
      cell_id: str (required)
    """
    cell_id = (body or {}).get("cell_id", "")
    if not cell_id:
        return {"success": False, "error": "cell_id required"}

    from l3.l3 import get_coordinator
    coord = get_coordinator()
    from l3.cell import reset_cells

    # Remove from cell list
    coord._cells = [c for c in coord._cells if c.get("id") != cell_id]
    # Rebuild composites
    from l3.l3b import L3B
    new_l3b = L3B()
    for c in coord._cells:
        new_l3b.register(c.get("id", ""), c.get("territory"))
    coord.b = new_l3b
    # Update cross_cell flag
    coord._cross_cell_active = len(coord._cells) >= 2

    return {
        "success": True,
        "removed": cell_id,
        "remaining_cells": len(coord._cells),
        "composite_count": len(coord.b.composites),
    }
