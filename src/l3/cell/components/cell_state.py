"""Cell state persistence — save/restore Cell to/from JSON.

Extracted from cell/__init__.py for modularity.
"""

from __future__ import annotations

import json as _json
import logging
import os

logger = logging.getLogger(__name__)


def save_state(cell, path: str = "") -> dict:
    """Save Cell state (agents, card_history) to JSON."""
    from l1.kernel.paths import get_paths as _gp
    path = path or _gp().cell_state_template.format(cell.cell_id)
    state = {
        "cell_id": cell.cell_id, "territory": cell.territory,
        "agents": {},
        "card_history": [h for h in cell._card_history],
    }
    with cell._lock:
        for aid, info in cell._agents.items():
            state["agents"][aid] = {
                "role": info.role, "ring": info.ring,
                "territory": info.territory,
                "max_concurrent_scouts": info.max_concurrent_scouts,
                "status": info.status.name,
            }
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(state, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, path)
        return {"success": True, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def restore_state(cell, path: str = "") -> dict:
    """Restore Cell state from JSON."""
    from l1.kernel.paths import get_paths as _gp
    path = path or _gp().cell_state_template.format(cell.cell_id)
    if not os.path.exists(path):
        return {"success": False, "error": "no state file"}
    try:
        with open(path, encoding="utf-8") as f:
            state = _json.load(f)
        cell.cell_id = state.get("cell_id", cell.cell_id)
        with cell._lock:
            for aid, d in state.get("agents", {}).items():
                if aid not in cell._agents:
                    from l1.kernel.params.agent import (
                        DEFAULT_AGENT_CONFIGS,
                        DEFAULT_AGENT_RING,
                        DEFAULT_MAX_CONCURRENT_SCOUTS,
                    )

                    from .cell_types import AgentInfo, AgentStatus
                    cfg = DEFAULT_AGENT_CONFIGS.get(d.get("role", ""))
                    info = AgentInfo(
                        role=d.get("role", ""),
                        ring=d.get("ring", cfg.ring if cfg else DEFAULT_AGENT_RING),
                        territory=d.get("territory", []),
                        max_concurrent_scouts=d.get("max_concurrent_scouts",
                                                     cfg.max_scouts if cfg else DEFAULT_MAX_CONCURRENT_SCOUTS),
                        status=AgentStatus[d.get("status", "IDLE")],
                    )
                    cell._agents[aid] = info
                    cell._mailbox[aid] = []
        return {"success": True, "agents": len(state.get("agents", {}))}
    except Exception as e:
        return {"success": False, "error": str(e)}
