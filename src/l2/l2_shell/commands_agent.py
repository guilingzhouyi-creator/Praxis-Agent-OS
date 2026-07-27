from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

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
        return {"success": False, "error": "usage: /kill <agent_id>"}
    agent_id = args[0]
    try:
        from l3.cell import get_cell
        cell_id = DEFAULT_CELL_ID
        cell = get_cell(cell_id)
        cell.remove_agent(agent_id)
        return {"success": True, "message": f"Agent '{agent_id}' terminated"}
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
    cell_id = args[0] if args else "cell-1"
    try:
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        r = cell.emergency_stop()
        return {"success": True, "message": f"Emergency stop triggered for {cell_id}", "result": r}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_cluster(args: list[str]) -> dict:
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
                agents[cid] = []
        return {"success": True, "cells": cells, "agents": agents, "count": len(cells)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_cell_create(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /cell create <territory>"}
    territory = args[0].strip("/")
    try:
        from l3.boot.boot import _create_cell as _boot_create_cell
        agent_config = [
            (f"agent-{int(time.time())}-r", "reader", [territory]),
            (f"agent-{int(time.time())}-w", "writer", [territory]),
            (f"agent-{int(time.time())}-g", "governor", [territory]),
        ]
        r = _boot_create_cell(agent_config)
        return {"success": True, "action": "create_cell", "agents": agent_config,
                "cell_id": r.get("cell_id", "default")}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_agent_refresh(args: list[str]) -> dict:
    if not args:
        return {"success": False, "error": "usage: /agent refresh <agent_id>"}
    agent_id = args[0]
    try:
        from l3.cell import get_cell
        cell = get_cell()
        return cell.reset_agent_context(agent_id)
    except Exception as e:
        return {"success": False, "error": str(e)}

