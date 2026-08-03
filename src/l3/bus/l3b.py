"""L3B — Cross-cell coordination with HTN-B composites (chain topology).

In the three-tier HTN architecture:
  HTN-A (central) → shard → L3B[1↔2] → L3B[2↔3] → L3B[3↔4] → ... → Cells

Each L3B composite = HTN-B + AgentLoop capability, inserted between two adjacent Cells:
  - Can only read the preceding Cell's L2 cache summary
  - Can only dispatch to the succeeding Cell
  - Communicates with adjacent composites via the L3B bus
  - Count = max(0, Cell_count - 1), automatically adjusted as Cells register/unregister

Tiers (inheriting the original design, but replacing a single routing table with a composite chain):
  L3B1: Simple forwarding (2-4 cells)     — composite only does route forwarding
  L3B2: Priority routing (4-8 cells)       — composite does conflict arbitration
  L3B4: Global scheduler (8+ cells)        — composite chain + Ring Omega
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel import get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class CellInfo:
    id: str
    territory: list[str] = field(default_factory=list)
    load: float = 0.0
    agents: int = 0
    status: str = "active"


class L3BComposite:
    """A single L3B composite = HTN-B + routing capability, inserted between two adjacent Cells.

    Each composite:
      - cell_id = "l3b-{prev}-{next}"
      - Holds an HTN-B instance
      - Can read the preceding Cell's L2 cache
      - Can dispatch to the succeeding Cell
    """

    def __init__(self, prev_cell_id: str, next_cell_id: str):
        from .htn_b import create_htn_b

        self.prev_cell = prev_cell_id
        self.next_cell = next_cell_id
        self.composite_id = f"l3b-{prev_cell_id}-{next_cell_id}"
        self.htn_b = create_htn_b(prev_cell_id, next_cell_id)
        self._active = False
        self._lock = threading.Lock()
        self._pending_cards: list[dict] = []
        self._completed_cards: list[dict] = []
        logger.info("L3BComposite created: %s", self.composite_id)

    @property
    def active(self) -> bool:
        return self._active

    def boot(self) -> dict:
        """Boot this composite (mark as active, register on the bus)."""
        with self._lock:
            if self._active:
                return {"success": True, "note": "already active"}
            self._active = True
            logger.info("L3BComposite booted: %s", self.composite_id)
            return {"success": True, "composite_id": self.composite_id}

    def shutdown(self) -> dict:
        with self._lock:
            self._active = False
            self._pending_cards.clear()
            logger.info("L3BComposite shutdown: %s", self.composite_id)
            return {"success": True}

    # ── Reading preceding L2 cache ──

    def read_prev_cache(self, query: str, limit: int = 10) -> list[dict]:
        """Read the preceding Cell's L2 cache summary (can only read preceding, not succeeding)."""
        try:
            from l3.cell import get_cell as _get_cell
            cell = _get_cell(self.prev_cell)
            hits = cell.cache.search(query, limit=limit)
            return [{
                "key": h.key,
                "summary": h.summary,
                "agent_id": h.agent_id,
                "entry_type": h.entry_type,
                "importance": h.importance,
            } for h in hits]
        except Exception as e:
            logger.warning("%s read_prev_cache: %s", self.composite_id, e)
            return []

    # ── Dispatch to succeeding Cell ──

    def dispatch_to_next(self, card_data: dict) -> dict:
        """Dispatch a sub-card to the succeeding Cell.

        Can only dispatch to the succeeding Cell (next_cell), not across hops.
        """
        target = card_data.get("target_cell", "")
        if target != self.next_cell:
            return {
                "success": False,
                "error": f"{self.composite_id}: cannot dispatch to {target}, "
                         f"only to adjacent {self.next_cell}",
            }
        try:
            from l3.cell import get_cell as _get_cell
            cell = _get_cell(self.next_cell)
            intent = card_data.get("intent", card_data.get("task_name", ""))
            domain = card_data.get("domain", "")
            # Execute with skip_htn=True since pre-routing is already done
            result = cell.execute_card(intent, domain=domain)
            self._pending_cards = [c for c in self._pending_cards if c.get("card_id") != card_data.get("card_id")]
            self._completed_cards.append({
                "card_id": card_data.get("card_id", ""),
                "result": result,
                "completed_at": time.time(),
            })
            return result
        except Exception as e:
            logger.warning("%s dispatch_to_next: %s", self.composite_id, e)
            return {"success": False, "error": str(e)}

    # ── HTN-B route decomposition ──

    def route_subtask(self, subtask: Any, prev_summary: str) -> list[Any]:
        """Use HTN-B to decompose HTN-A subtasks and produce a row plan.

        TODO(HTN-B): decomposition is not yet implemented — currently returns
        an empty plan; dispatch_to_next() handles routing directly.
        """
        return []

    # ── Status ──

    def status(self) -> dict:
        with self._lock:
            return {
                "composite_id": self.composite_id,
                "active": self._active,
                "prev_cell": self.prev_cell,
                "next_cell": self.next_cell,
                "pending_cards": len(self._pending_cards),
                "completed_cards": len(self._completed_cards),
            }


class L3B:
    """Cross-cell coordinator. Manages N-1 composites in a chain topology.

    When a Cell registers:
      - If total Cells ≥ 2, L3B auto-creates a composite between the new Cell
        and the previously registered Cell.
      - Composites form an ordered chain: Cell-1 ↔ [L3B_1_2] ↔ Cell-2 ↔ [L3B_2_3] ↔ Cell-3
    """

    def __init__(self):
        self._cells: dict[str, CellInfo] = {}
        self._composites: dict[str, L3BComposite] = {}  # composite_id → L3BComposite
        self._cell_order: list[str] = []  # ordered list of cell_ids
        self.bus = get_event_bus()

    @property
    def tier(self) -> str:
        n = len(self._cells)
        return "L3B1" if n < 4 else "L3B2" if n < 8 else "L3B4"

    @property
    def composites(self) -> list[L3BComposite]:
        return list(self._composites.values())

    def register(self, cell_id: str, territory: list[str] | None = None) -> None:
        """Register a Cell. Auto-creates L3B composites with adjacent Cells."""
        if cell_id in self._cells:
            return
        self._cells[cell_id] = CellInfo(id=cell_id, territory=territory or [])
        self._cell_order.append(cell_id)

        # Create composite with previous Cell in the chain
        if len(self._cell_order) >= 2:
            prev_cell = self._cell_order[-2]
            composite = L3BComposite(prev_cell, cell_id)
            self._composites[composite.composite_id] = composite
            composite.boot()
            logger.info(
                "L3B: created composite %s (tier=%s, total cells=%d)",
                composite.composite_id, self.tier, len(self._cells),
            )

        logger.info("L3B registered: %s (tier=%s, total=%d)",
                     cell_id, self.tier, len(self._cells))

    def get_composite(self, prev_cell: str, next_cell: str) -> L3BComposite | None:
        """Get the composite between two adjacent Cells."""
        cid = f"l3b-{prev_cell}-{next_cell}"
        return self._composites.get(cid)

    def route(self, domain: str, exclude: str = "") -> str | None:
        """Legacy route: find best Cell for a domain (used by CentralController)."""
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
        """Resolve a conflict between two Cells (legacy)."""
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
            "composites": {cid: comp.status() for cid, comp in self._composites.items()},
        }

    # ── Cross-cell L2 cache routing matrix ──

    def cache_search(self, query: str, limit: int = 5) -> list[dict]:
        """Search ALL registered Cells' L2 caches."""
        results: list[dict] = []
        for cell_id in list(self._cells.keys()):
            try:
                from l3.cell import get_cell as _get_cell
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
                logger.debug("l3b: memory aggregate failed")
        results.sort(key=lambda r: r["importance"], reverse=True)
        return results[:limit]

    def cache_lookup(self, key: str, cell_id: str) -> dict:
        try:
            from l3.cell import get_cell as _get_cell
            cell = _get_cell(cell_id)
            entry = cell.cache.lookup(key)
            if entry:
                return {"success": True, "value": entry.value, "cell_id": cell_id}
            return {"success": False, "error": "not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cache_stats(self) -> dict:
        total = {"hot": 0, "index": 0, "kv": 0, "hits": 0, "misses": 0}
        per_cell = {}
        for cell_id in list(self._cells.keys()):
            try:
                from l3.cell import get_cell as _get_cell
                cell = _get_cell(cell_id)
                s = cell.cache.stats()
                per_cell[cell_id] = s
                total["hot"] += s["hot_size"]
                total["index"] += s["index_size"]
                total["kv"] += s["kv_size"]
                total["hits"] += s["hits"]
                total["misses"] += s["misses"]
            except Exception:
                logger.debug("l3b: stats aggregate failed")
        total["per_cell"] = per_cell
        total["cell_count"] = len(self._cells)
        return total
