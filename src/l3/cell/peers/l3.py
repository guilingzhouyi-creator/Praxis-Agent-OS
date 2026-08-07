"""CentralController — unified intent lifecycle controller.

Combines L3A (session management) + L3B (cross-cell routing) + Dispatcher (Cell allocation)
+ CardRegistry (card lifecycle) into a single unified controller.

Lifecycle:
  PENDING → PARSED → QUEUED → DISPATCHED → RUNNING → DONE | FAILED
                          ↘ CANCELLED
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from l1.kernel.params.kernel import WitnessStatus
from l1.kernel.params.system import CARD_DEFAULT_PRIORITY, LOG_TRUNC_80
from l3.bus.l3b import L3B
from l3.bus.l3b_bus import get_bus as get_l3b_bus
from l3.cell.peers.l3a import CardType, TaskCard, get_daemon

logger = logging.getLogger(__name__)


class CentralController:
    """Unified controller — L3A session + L3B routing + CardRegistry lifecycle.

    Over L3Coordinator, this adds:
      - Intent lifecycle tracking (PENDING → DONE)
      - CardRegistry integration (submit + dispatch + query)
      - Result callback for completed intents
    """

    def __init__(self):
        self.l3a = get_daemon()
        self.b = L3B()
        self._cells: list[dict] = []
        self._intents: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._routes: dict[str, str] = {}
        self._cards: list[TaskCard] = []
        self._next_id = 0

    def register_cell(self, cell_id: str, territory: list[str],
                      agents: list[str] | None = None) -> None:
        """Register a cell and its territory with the controller."""
        self._routes[territory[0]] = cell_id
        self.b.register(cell_id, territory)
        self._cells.append({"id": cell_id, "territory": territory, "agents": agents or []})

        try:
            from .cell.components.cell_monitor import get_cell_monitor
            get_cell_monitor().register_cell(
                cell_id, territory, {a: "" for a in agents} if agents else {},
            )
        except Exception as e:
            logger.warning("cellmonitor register failed: %s", e)

        try:
            bus = get_l3b_bus()
            for comp in self.b.composites:
                bus.register(comp.composite_id)
        except Exception as e:
            logger.warning("l3b bus register failed: %s", e)

        try:
            from .bus.htn_a import get_htn_a
            get_htn_a()
        except Exception as e:
            logger.warning("HTN-A init failed: %s", e)

        if len(self._cells) >= 2:
            logger.info("Cell-B activated: %d cells", len(self._cells))
            self._cross_cell_active = True
        else:
            self._cross_cell_active = False

    def get_cell_count(self) -> int:
        """Return the number of registered cells."""
        with self._lock:
            return len(self._cells)

    def is_cross_cell_active(self) -> bool:
        """Return True when multi-cell routing is active."""
        return bool(getattr(self, '_cross_cell_active', False))

    def remove_cell(self, cell_id: str) -> dict:
        """Remove a cell from the controller and rebuild the L3B bus."""
        with self._lock:
            self._cells = [c for c in self._cells if c.get("id") != cell_id]
            from l3.bus.l3b import L3B
            new_l3b = L3B()
            for c in self._cells:
                new_l3b.register(c.get("id", ""), c.get("territory", ["."]))
            self.b = new_l3b
            self._cross_cell_active = len(self._cells) >= 2
        return {"success": True, "cell_id": cell_id, "remaining": len(self._cells)}

    def process_intent(self, text: str, use_llm: bool = True) -> dict:
        """Full intent lifecycle: session prompt → card dispatch → result."""
        if use_llm:
            session = self._ensure_session()
            parsed = session.prompt(text)
            if isinstance(parsed, dict):
                return self._process_llm_result(text, parsed)
        else:
            parsed = self._rule_parse(text)
            if isinstance(parsed, dict):
                return self._process_llm_result(text, parsed)
        return self._process_taskcard_result(parsed)

    def _process_llm_result(self, text: str, parsed: dict) -> dict:
        """Handle a dict-shaped result (LLM prompt output or rule parse)."""
        answer = parsed.get("answer", "")
        cid = ""
        for sr in parsed.get("steps", []):
            if "cardwrite" in sr.get("action", ""):
                cid = sr.get("result", {}).get("card_id", "")
        if not cid:
            m = re.search(r"card-[\da-f]{8}", answer or "")
            cid = m.group(0) if m else ""
        status = "queued" if cid else "parsed"
        with self._lock:
            self._intents[cid or text[:8]] = {
                "card": None, "card_id": cid or "", "status": status.upper(),
                "created_at": time.time(), "result": parsed,
            }
        return {"success": bool(cid), "card_id": cid, "intent": text[:LOG_TRUNC_80],
                "status": status, "answer": answer}

    def _process_taskcard_result(self, card: TaskCard) -> dict:
        """Handle a TaskCard result: submit, queue, route cross-cell (HTN-A)."""
        domain = card.domain or ""
        admin_action = getattr(card, "admin_action", "")
        if domain == "cluster" or admin_action:
            return self._process_admin_card(card)

        cid = ""
        try:
            from .card.card_registry import get_registry
            cid = get_registry().submit(
                intent=card.intent, domain=domain,
                priority=getattr(card, "priority", CARD_DEFAULT_PRIORITY),
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
            "card_type": card.card_type.name if hasattr(card, "card_type") else "execution",
            "status": "queued",
        }

        multi_cell = len(self._cells) >= 2
        if multi_cell:
            try:
                from .bus.htn_a import get_htn_a
                from .bus.htn_a import get_shards as _get_shards
                htn_a = get_htn_a()
                htn_task = htn_a.decompose(card.intent, domain)
                shards = _get_shards(htn_task)
                result["htn_a"] = {
                    "task_count": len(htn_task.sub_tasks),
                    "shards": [{"cell_id": s["cell_id"], "task_count": len(s["tasks"])} for s in shards],
                }
                for shard in shards:
                    shard_cell = shard["cell_id"]
                    for composite in self.b.composites:
                        if composite.next_cell == shard_cell:
                            composite.dispatch_to_next({
                                "intent": f"{card.intent} — {shard_cell}",
                                "domain": domain, "task_name": shard_cell, "target_cell": shard_cell,
                            })
                            break
                result["cross_cell"] = {"active": True, "composites": len(self.b.composites), "shards": len(shards)}
            except Exception as e:
                logger.warning("HTN-A decomposition failed: %s", e)
                cross = self.b.route(domain, exclude="")
                if cross:
                    result["cross_cell"] = {"domain": domain, "candidate": cross, "fallback": True}
        elif domain:
            cross = self.b.route(domain, exclude="")
            if cross:
                result["cross_cell"] = {"domain": domain, "candidate": cross}

        return result

    def _ensure_session(self):
        active = self.l3a.manager.list_active()
        if active:
            s = self.l3a.manager.get(active[0]["session_id"])
            if s:
                return s
        return self.l3a.create_session(title="L3A session")

    def _rule_parse(self, text: str) -> TaskCard:
        card_type = CardType.EXECUTION
        domain = ""
        for kw, cell in self._routes.items():
            if kw.lower() in text.lower():
                domain = kw
                break
        if "?" in text:
            card_type = CardType.ISSUE
        card = TaskCard(
            id=f"card-{self._next_id:04d}", intent=text,
            card_type=card_type, domain=domain, priority=CARD_DEFAULT_PRIORITY,
        )
        self._next_id += 1
        self._cards.append(card)
        return card

    def get_intent(self, card_id: str) -> dict | None:
        """Return the intent record for card_id, or None."""
        with self._lock:
            return self._intents.get(card_id)

    def update_intent(self, card_id: str, status: str, result: dict | None = None) -> None:
        """Update the status (and optionally result) of an intent."""
        with self._lock:
            if card_id in self._intents:
                self._intents[card_id]["status"] = status
                if result:
                    self._intents[card_id]["result"] = result

    def list_intents(self, status: str = "") -> list[dict]:
        """List tracked intents, optionally filtered by status."""
        with self._lock:
            return [
                {"card_id": i["card_id"],
                 "intent": i["card"].intent if i.get("card") else "",
                 "status": i["status"], "created_at": i.get("created_at")}
                for i in self._intents.values()
                if not status or i["status"] == status
            ]

    def _process_admin_card(self, card) -> dict:
        admin_action = getattr(card, 'admin_action', getattr(card, 'tools_hint', [''])[0] if hasattr(card, 'tools_hint') and card.tools_hint else 'cluster_status')
        intent = getattr(card, 'intent', '')
        target_agent = getattr(card, 'agent_id', getattr(card, 'target_agent', ''))
        cid = f"admin-{int(time.time())}"
        status = "DONE"

        try:
            if admin_action == "spawn_agent":
                from l1.kernel.params.agent import AGENT_ROLE_MAP

                from .cell import get_cell
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
                cells: list[Any] = getattr(cm, 'list_cells', lambda: [])()
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
                "intent": intent[:LOG_TRUNC_80], "status": status, "result": result}

    def status(self) -> dict:
        """Return controller status (L3A, L3B, intent counts)."""
        return {
            "L3A": {"sessions": self.l3a.manager.count()},
            "L3B": self.b.status(),
            "Intents": {"total": len(self._intents)},
        }


_coordinator: CentralController | None = None


def get_coordinator() -> CentralController:
    """Return the singleton CentralController, creating it lazily."""
    global _coordinator
    if _coordinator is None:
        _coordinator = CentralController()
    return _coordinator


def reset_coordinator() -> None:
    """Reset the CentralController singleton to None."""
    global _coordinator
    _coordinator = None
