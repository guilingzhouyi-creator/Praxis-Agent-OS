"""L3B — Cross-cell coordination (activates at 2+ cells).

Tiers:
  L3B1: Simple forwarding (2-4 cells)
  L3B2: Priority routing + conflict arbitration (4-8 cells)
  L3B4: Global scheduler + Ring Omega (8+ cells)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel import get_event_bus, Signal, SignalType

logger = logging.getLogger(__name__)


@dataclass
class CellInfo:
    id: str
    territory: list[str] = field(default_factory=list)
    load: float = 0.0
    agents: int = 0
    status: str = "active"


class L3B:
    """Cross-cell coordinator. Tier auto-selects by cell count."""

    def __init__(self):
        self._cells: dict[str, CellInfo] = {}
        self.bus = get_event_bus()

    @property
    def tier(self) -> str:
        n = len(self._cells)
        return "L3B1" if n < 4 else "L3B2" if n < 8 else "L3B4"

    def register(self, cell_id: str, territory: list[str] | None = None) -> None:
        self._cells[cell_id] = CellInfo(id=cell_id, territory=territory or [])
        logger.info("L3B registered: %s (tier=%s, total=%d)", cell_id, self.tier, len(self._cells))

    def route(self, domain: str, exclude: str = "") -> str | None:
        candidates = [
            c for c in self._cells.values()
            if c.id != exclude and c.status == "active"
        ]
        if self.tier == "L3B1":
            for c in candidates:
                if any(domain.startswith(t) for t in c.territory):
                    return c.id
            return candidates[0].id if candidates else None
        # L3B2/L3B4: score-based
        scored = [
            (sum(1 for t in c.territory if domain.startswith(t)) * 3 + (1.0 - c.load) * 2, c.id)
            for c in candidates
        ]
        scored.sort(reverse=True)
        return scored[0][1] if scored else None

    def resolve(self, cell_a: str, cell_b: str, resource: str) -> dict:
        ca, cb = self._cells.get(cell_a), self._cells.get(cell_b)
        if not ca or not cb:
            return {"success": False, "error": "cell not found"}
        if self.tier == "L3B1":
            winner = cell_a if ca.load <= cb.load else cell_b
            return {"success": True, "winner": winner, "tier": "L3B1", "reason": "lower load"}
        score_a = (1.0 - ca.load) * 0.6 + 0.4
        score_b = (1.0 - cb.load) * 0.6 + 0.4
        return {"success": True, "winner": cell_a if score_a >= score_b else cell_b,
                "tier": self.tier, "reason": f"score {score_a:.2f} vs {score_b:.2f}"}

    def status(self) -> dict:
        return {
            "tier": self.tier,
            "cells": {c.id: {"load": c.load, "agents": c.agents, "status": c.status}
                      for c in self._cells.values()},
        }

    # ── Cross-cell L2 cache routing matrix ──

    def cache_search(self, query: str, limit: int = 5) -> list[dict]:
        """Search ALL registered Cells' L2 caches for a query.

        Returns entries with their source cell_id so the caller can
        route to the right Cell for the full value.
        """
        results: list[dict] = []
        for cell_id in list(self._cells.keys()):
            try:
                from .cell import get_cell as _get_cell
                cell = _get_cell(cell_id)
                hits = cell.cache.search(query, limit=limit)
                for entry in hits:
                    results.append({
                        "key": entry.key,
                        "summary": entry.summary,
                        "cell_id": cell_id,
                        "agent_id": entry.agent_id,
                        "entry_type": entry.entry_type,
                        "importance": entry.importance,
                        "location": entry.location,
                    })
            except Exception:
                pass  # best-effort per Cell
        results.sort(key=lambda r: r["importance"], reverse=True)
        return results[:limit]

    def cache_lookup(self, key: str, cell_id: str) -> dict:
        """Look up a full cached value from a specific Cell's L2 cache."""
        try:
            from .cell import get_cell as _get_cell
            cell = _get_cell(cell_id)
            entry = cell.cache.lookup(key)
            if entry:
                return {"success": True, "value": entry.value, "cell_id": cell_id}
            return {"success": False, "error": "not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cache_stats(self) -> dict:
        """Aggregate L2 cache stats across all Cells."""
        total = {"hot": 0, "index": 0, "kv": 0, "hits": 0, "misses": 0}
        per_cell = {}
        for cell_id in list(self._cells.keys()):
            try:
                from .cell import get_cell as _get_cell
                cell = _get_cell(cell_id)
                s = cell.cache.stats()
                per_cell[cell_id] = s
                total["hot"] += s["hot_size"]
                total["index"] += s["index_size"]
                total["kv"] += s["kv_size"]
                total["hits"] += s["hits"]
                total["misses"] += s["misses"]
            except Exception:
                pass
        total["per_cell"] = per_cell
        total["cell_count"] = len(self._cells)
        return total
