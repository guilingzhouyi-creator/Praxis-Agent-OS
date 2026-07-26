"""ContextPool — per-agent ContextManager pool with isolated token budgets.

Each agent gets its own ContextManager instance with an independent
register and token budget.  The pool exposes a cell_total() method
for the CellTokenMerger to compute Cell-level token consumption.
"""

from __future__ import annotations

import threading
from typing import Any

from .context import ContextManager

_lock = threading.Lock()
_pools: dict[str, ContextManager] = {}  # agent_id → ContextManager
_agent_to_cell: dict[str, str] = {}     # agent_id → cell_id


def register(agent_id: str, cell_id: str = "", max_tokens: int = 4096) -> ContextManager:
    """Register or retrieve an agent's context pool entry."""
    with _lock:
        if agent_id not in _pools:
            _pools[agent_id] = ContextManager(max_tokens=max_tokens)
        if cell_id:
            _agent_to_cell[agent_id] = cell_id
        return _pools[agent_id]


def unregister(agent_id: str) -> None:
    with _lock:
        _pools.pop(agent_id, None)
        _agent_to_cell.pop(agent_id, None)


def get(agent_id: str) -> ContextManager | None:
    return _pools.get(agent_id)


def token_usage(agent_id: str = "") -> dict:
    """Return token count for agent_id, or all agents if agent_id is empty."""
    with _lock:
        if agent_id:
            cm = _pools.get(agent_id)
            return {agent_id: cm.token_count()} if cm else {}
        return {aid: cm.token_count() for aid, cm in _pools.items()}


def cell_total(cell_id: str) -> dict:
    """Sum token usage for all agents in a given Cell."""
    total = 0
    per_agent = {}
    with _lock:
        for agent_id, cid in _agent_to_cell.items():
            if cid == cell_id:
                cm = _pools.get(agent_id)
                if cm:
                    t = cm.token_count()
                    total += t
                    per_agent[agent_id] = t
    return {"cell_id": cell_id, "total_tokens": total, "per_agent": per_agent}


def all_cell_totals() -> dict:
    """Aggregate token usage across all Cells."""
    cells: dict[str, dict] = {}
    with _lock:
        for agent_id, cid in _agent_to_cell.items():
            cm = _pools.get(agent_id)
            if not cm:
                continue
            t = cm.token_count()
            cell = cells.setdefault(cid, {"cell_id": cid, "total_tokens": 0, "per_agent": {}})
            cell["total_tokens"] += t
            cell["per_agent"][agent_id] = t
    return {"cells": list(cells.values()), "total_tokens": sum(c["total_tokens"] for c in cells.values())}
