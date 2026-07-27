"""CentralController — unified intent lifecycle controller.

Combines L3A (intent parsing) + L3B (cross-cell routing) + Dispatcher (Cell allocation)
+ CardRegistry (card lifecycle) into a single unified controller.

Lifecycle:
  PENDING → PARSED → QUEUED → DISPATCHED → RUNNING → DONE | FAILED
                         ↘ CANCELLED
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .cell.peers.l3a import L3A, TaskCard
from .bus.l3b import L3B
from .bus.l3b_bus import get_bus as get_l3b_bus
from l1.kernel.params.kernel import WitnessStatus

logger = logging.getLogger(__name__)


class CentralController:
    """Unified controller — L3A + L3B + Dispatcher + CardRegistry lifecycle.

    Over L3Coordinator, this adds:
      - Intent lifecycle tracking (PENDING → DONE)
      - CardRegistry integration (submit + dispatch + query)
      - Result callback for completed intents
    """

    def __init__(self):
        self.a = L3A()
        self.b = L3B()
        self._cells: list[dict] = []
        self._intents: dict[str, dict] = {}
        self._lock = threading.Lock()

    def register_cell(self, cell_id: str, territory: list[str],
                      agents: list[str] | None = None) -> None:
        self.a.register_route(territory[0], cell_id)
        self.b.register(cell_id, territory)
        self._cells.append({"id": cell_id, "territory": territory, "agents": agents or []})

        # ── CellMonitor integration ──
        try:
            from .cell.components.cell_monitor import get_cell_monitor
            get_cell_monitor().register_cell(
                cell_id, territory, {a: "" for a in agents} if agents else {},
            )
        except Exception as e:
            logger.warning("cellmonitor register failed: %s", e)

        # ── Register L3B composites with bus ──
        try:
            bus = get_l3b_bus()
            for comp in self.b.composites:
                bus.register(comp.composite_id)
        except Exception as e:
            logger.warning("l3b bus register failed: %s", e)

        # ── HTN-A: warm-up on first Cell registration ──
        try:
            from .bus.htn_a import get_htn_a
            htn_a = get_htn_a()
            logger.debug("HTN-A ready: %d methods", len(htn_a._methods))
        except Exception as e:
            logger.warning("HTN-A init failed: %s", e)

        # ── Cell-B: auto-enable cross-territory rules when 2+ Cells ──
        if len(self._cells) >= 2:
            logger.info("Cell-B activated: %d cells, cross-territory rules enabled", len(self._cells))
            self._cross_cell_active = True
        else:
            self._cross_cell_active = False

    def process_intent(self, text: str, use_llm: bool = True) -> dict:
        """Full intent lifecycle: parse → queue → dispatch → result."""
        parsed = self.a.parse(text, use_llm=use_llm)

        # AgentLoop result (cardwrite was already called — card is in registry)
        if isinstance(parsed, dict):
            answer = parsed.get("answer", "")
            cid = ""
            for sr in parsed.get("steps", []):
                if "cardwrite" in sr.get("action", ""):
                    cid = sr.get("result", {}).get("card_id", "")
            if not cid:
                # Try to find card_id in the answer
                import re as _re
                m = _re.search(r'card-[\da-f]{8}', answer or "")
                cid = m.group(0) if m else ""
            status = "queued" if cid else "parsed"
            with self._lock:
                self._intents[cid or text[:8]] = {
                    "card": None, "card_id": cid or "", "status": status.upper(),
                    "created_at": time.time(), "result": parsed,
                }
            return {"success": bool(cid), "card_id": cid, "intent": text[:80],
                    "status": status, "answer": answer}

        # TaskCard result (rule engine fallback)
        card = parsed
        domain = card.domain or ""

        # ── ADMIN card: execute cluster management inline ──
        admin_action = getattr(card, 'admin_action', '')
        if domain == "cluster" or admin_action:
            return self._process_admin_card(card)

        cid = ""
        try:
            from .card.card_registry import get_registry
            cid = get_registry().submit(
                intent=card.intent, domain=domain,
                priority=getattr(card, 'priority', 5),
            )
        except Exception as e:
            logger.warning("card registry submit failed: %s", e)
            cid = card.id

        with self._lock:
            self._intents[cid] = {
                "card": card, "card_id": cid, "status": WitnessStatus.PENDING,
                "created_at": time.time(), "result": None,
            }

        result = {
            "card_id": cid, "intent": card.intent, "domain": domain,
            "card_type": card.card_type.name if hasattr(card, 'card_type') else "execution",
            "status": "queued",
        }

        # 3. Cross-cell routing (2+ cells) — HTN-A decomposition
        multi_cell = len(self._cells) >= 2
        if multi_cell:
            try:
                from .bus.htn_a import get_htn_a, get_shards
                htn_a = get_htn_a()
                htn_task = htn_a.decompose(card.intent, domain)
                shards = get_shards(htn_task)
                result["htn_a"] = {
                    "task_count": len(htn_task.sub_tasks),
                    "shards": [
                        {"cell_id": s["cell_id"], "task_count": len(s["tasks"])}
                        for s in shards
                    ],
                }
                # Dispatch shards to L3B composites
                for shard in shards:
                    shard_cell = shard["cell_id"]
                    tasks = shard["tasks"]
                    # Find composite that routes to this Cell
                    for composite in self.b.composites:
                        if composite.next_cell == shard_cell:
                            summary = "\n".join(f"[{t.name}] {t.description[:100]}" for t in tasks)
                            composite.dispatch_to_next({
                                "intent": f"{card.intent} — {shard_cell}",
                                "domain": domain,
                                "task_name": shard_cell,
                                "target_cell": shard_cell,
                            })
                            break
                result["cross_cell"] = {
                    "active": True,
                    "composites": len(self.b.composites),
                    "shards": len(shards),
                }
            except Exception as e:
                logger.warning("HTN-A decomposition failed: %s", e)
                # Fallback to legacy routing
                cross = self.b.route(domain, exclude="")
                if cross:
                    result["cross_cell"] = {"domain": domain, "candidate": cross, "fallback": True}
        elif domain:
            cross = self.b.route(domain, exclude="")
            if cross:
                result["cross_cell"] = {"domain": domain, "candidate": cross}

        return result

    def get_intent(self, card_id: str) -> dict | None:
        with self._lock:
            return self._intents.get(card_id)

    def update_intent(self, card_id: str, status: str, result: dict | None = None) -> None:
        with self._lock:
            if card_id in self._intents:
                self._intents[card_id]["status"] = status
                if result:
                    self._intents[card_id]["result"] = result

    def list_intents(self, status: str = "") -> list[dict]:
        with self._lock:
            return [
                {"card_id": i["card_id"],
                 "intent": i["card"].intent if i.get("card") else "",
                 "status": i["status"], "created_at": i.get("created_at")}
                for i in self._intents.values()
                if not status or i["status"] == status
            ]

    def _process_admin_card(self, card) -> dict:
        """Execute cluster management actions (spawn/kill/destroy/emergency)."""
        admin_action = getattr(card, 'admin_action', getattr(card, 'tools_hint', [''])[0] if hasattr(card, 'tools_hint') and card.tools_hint else 'cluster_status')
        intent = getattr(card, 'intent', '')
        target_agent = getattr(card, 'agent_id', getattr(card, 'target_agent', ''))
        cid = f"admin-{int(time.time())}"
        status = "DONE"

        try:
            if admin_action == "spawn_agent":
                from .cell import get_cell
                from l1.kernel.params.agent import AGENT_ROLE_MAP
                role = AGENT_ROLE_MAP.get(3, "default")
                cell = get_cell()
                cell.add_agent(target_agent or f"auto-{int(time.time())}", role=role, territory=["."], auto_boot=True)
                result = {"success": True, "action": "spawn_agent", "agent": target_agent, "role": role}

            elif admin_action == "kill_agent":
                from .cell import get_cell
                cell = get_cell()
                cell.remove_agent(target_agent)
                result = {"success": True, "action": "kill_agent", "agent": target_agent}

            elif admin_action == "emergency_stop":
                from .cell import get_cell
                cell = get_cell()
                result = cell.emergency_stop()

            elif admin_action == "cluster_status":
                from .cell.components.cell_monitor import get_cell_monitor
                cm = get_cell_monitor()
                cells = getattr(cm, 'list_cells', lambda: [])()
                result = {"success": True, "action": "cluster_status", "cells": cells}

            else:
                result = {"success": False, "error": f"unknown admin_action: {admin_action}"}
        except Exception as e:
            result = {"success": False, "error": str(e)}
            status = "FAILED"

        with self._lock:
            self._intents[cid] = {
                "card": card, "card_id": cid, "status": status,
                "created_at": time.time(), "result": result,
            }
        return {"success": result.get("success", False), "card_id": cid,
                "intent": intent[:80], "status": status, "result": result}

    def status(self) -> dict:
        return {
            "L3A": {"cards": len(self.a._cards)},
            "L3B": self.b.status(),
            "Intents": {"total": len(self._intents)},
        }


_coordinator: CentralController | None = None


def get_coordinator() -> CentralController:
    global _coordinator
    if _coordinator is None:
        _coordinator = CentralController()
    return _coordinator


def reset_coordinator() -> None:
    global _coordinator
    _coordinator = None
