"""CardRegistry — central card queue, status tracking, auto-dispatch, persistent.

Cards enter the registry, are queued by priority, dispatched to Cells
by territory match, executed, and tracked through completion.

Persistence: JSON file at CARD_REGISTRY_PATH, auto-saved every 30s.

Flow:
  submit(card) → PENDING → DISPATCHED → RUNNING → DONE | FAILED
                                       ↓ (territory match)
                                   Cell.execute_card()
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Callable

from kernel import EVENT_TASK_ASSIGN, emit_signal
from kernel.params.system import (
    CARD_REGISTRY_PATH,
    CARD_REGISTRY_AUTO_SAVE,
    CARD_DISPATCH_INTERVAL,
    CARD_QUEUE_PENDING_MAX,
)
from services._persistable import PersistableMixin
from .card_unified import CardUnified, CardLifecycle, CardSummary

logger = logging.getLogger(__name__)


def _card_to_dict(r: CardUnified) -> dict:
    """Convert CardUnified to listing dict (unified format)."""
    elapsed = 0.0
    if r.timestamps.completed_at:
        elapsed = round(r.timestamps.completed_at - r.timestamps.dispatched_at, 2)
    elif r.timestamps.dispatched_at:
        elapsed = round(time.time() - r.timestamps.dispatched_at, 1)
    d = r.to_dict(include_hidden=False)
    d["elapsed"] = elapsed
    d["state"] = r.state.value  # CardLifecycle string value directly
    d["has_plan"] = bool(r.summary.columns or r.phases)
    d["plan_summary"] = r.summary.title[:80] if r.summary.title else ""
    return d


class CardRegistry(PersistableMixin):
    """Central card queue — submit, dispatch, track, list, auto-persisted.

    Uses CardUnified as the single card model.
    Background dispatcher thread polls the queue and routes cards to Cells.
    """

    persistence_kind = "card_registry"

    def __init__(self, persist_path: str = ""):
        self._cards: dict[str, CardUnified] = {}
        self._queue: list[str] = []
        self._lock = threading.RLock()
        self._cell_map: dict[str, Any] = {}
        self._cell_resolver: Callable[[str], Any] | None = None
        self._dispatcher_running = False
        self._dispatcher_thread: threading.Thread | None = None
        self._init_persistence(persist_path or CARD_REGISTRY_PATH, CARD_REGISTRY_AUTO_SAVE)
        self._restore()
        if CARD_REGISTRY_AUTO_SAVE > 0:
            self._start_auto_save()

    def set_cell_resolver(self, resolver: Callable[[str], Any]) -> None:
        self._cell_resolver = resolver

    # ── Background dispatcher ──

    def start_dispatcher(self) -> None:
        if self._dispatcher_running:
            return
        self._dispatcher_running = True
        self._dispatcher_thread = threading.Thread(
            target=self._dispatcher_loop, daemon=True, name="card-dispatcher",
        )
        self._dispatcher_thread.start()
        logger.info("card dispatcher started (poll every %.1fs)", CARD_DISPATCH_INTERVAL)

    def stop_dispatcher(self) -> None:
        self._dispatcher_running = False

    def _dispatcher_loop(self) -> None:
        tick = 0
        while self._dispatcher_running:
            self._dispatch_one()
            tick += 1
            if tick % 10 == 0:
                self._recheck_held()
                self._escalate_stale()
            time.sleep(CARD_DISPATCH_INTERVAL)

    def _recheck_held(self) -> None:
        with self._lock:
            held = [(cid, rec) for cid, rec in self._cards.items()
                    if rec.state == CardLifecycle.QUEUED and rec.timestamps.dispatched_at > 0]
        for cid, rec in held:
            try:
                from .card_gate import evaluate as _gate_evaluate
                gate_r = _gate_evaluate(cid, intent=rec.summary.title, domain=rec.nature)
                if gate_r.get("auto_approve", False):
                    logger.info("card %s un-held by card gate, re-queued", cid)
            except Exception:
                pass

    def _escalate_stale(self) -> None:
        now = time.time()
        with self._lock:
            for cid, rec in list(self._cards.items()):
                if rec.state == CardLifecycle.QUEUED and (now - rec.timestamps.created_at) > 3600:
                    logger.warning("card %s stale (>1h), escalating", cid)
                    rec.state = CardLifecycle.CANCELLED
                    if cid in self._queue:
                        self._queue.remove(cid)
                    emit_signal(EVENT_TASK_ASSIGN, sender="registry", target="l3",
                                 data={"card_id": cid, "event": "stale_escalated"})

    # ── Placeholder system ──

    @staticmethod
    def _is_placeholder(entry: str) -> bool:
        return entry.startswith("__HOLD__:")

    @staticmethod
    def _placeholder_of(card_id: str) -> str:
        return f"__HOLD__:{card_id}"

    @staticmethod
    def _card_from_placeholder(entry: str) -> str:
        return entry.split(":", 1)[1] if ":" in entry else ""

    def restore_card(self, card_id: str) -> bool:
        placeholder = self._placeholder_of(card_id)
        with self._lock:
            for i, entry in enumerate(self._queue):
                if entry == placeholder:
                    self._queue[i] = card_id
                    self._queue.sort(key=lambda x: self._cards[x].priority if x in self._cards else 5)
                    logger.info("card %s restored from placeholder", card_id)
                    return True
        return False

    def hold_card(self, card_id: str) -> None:
        with self._lock:
            for i, entry in enumerate(self._queue):
                if entry == card_id:
                    self._queue[i] = self._placeholder_of(card_id)
                    break

    def _find_dependents(self, card_id: str) -> list[str]:
        result = []
        with self._lock:
            for cid, rec in self._cards.items():
                if cid in rec._depends_on and rec.state == CardLifecycle.QUEUED:
                    result.append(cid)
        return result

    # ── Dispatch one card ──

    def _dispatch_one(self) -> None:
        cid = None
        with self._lock:
            for c in self._queue:
                if self._is_placeholder(c):
                    continue
                record = self._cards.get(c)
                if record and record.state == CardLifecycle.QUEUED:
                    cid = c
                    break
        if not cid:
            return

        with self._lock:
            record = self._cards.get(cid)
            if not record:
                return
            intent = record.summary.title
            domain = record.nature
            # Phase 1 bridge: prefer embedded old Card, fall back to to_old_card(),
            # then raw intent string.
            structured_card = None
            if hasattr(record, 'card') and record.card:
                structured_card = record.card
            elif record.phases and any(p.tasks for p in record.phases):
                structured_card = record.to_old_card()

        try:
            from .card_gate import evaluate as _gate_evaluate
            gate_r = _gate_evaluate(cid, intent=intent, domain=domain)
        except Exception:
            gate_r = {"auto_approve": True, "action": "dispatch"}

        if not gate_r.get("auto_approve", True):
            plan = self.generate_plan(intent, domain)
            with self._lock:
                rec = self._cards.get(cid)
                if rec:
                    rec.summary.columns["_plan"] = json.dumps(plan)
            self.hold_card(cid)
            logger.info("card %s held, plan ready (%d steps)", cid, len(plan.get("steps", [])))
            dependents = self._find_dependents(cid)
            for dep_cid in dependents:
                from .pending_queue import get_queue
                dep_rec = self._cards.get(dep_cid)
                if dep_rec:
                    get_queue().enqueue(
                        dep_cid,
                        intent=dep_rec.summary.title,
                        domain=dep_rec.nature,
                        size="dependency",
                        priority=dep_rec.priority,
                    )
                    self.hold_card(dep_cid)
            return

        dispatch_r = self.dispatch(cid)
        if not dispatch_r.get("success"):
            return

        cell_id = dispatch_r["cell_id"]
        resolver = self._cell_resolver
        if not resolver:
            logger.warning("card %s: no cell resolver registered", cid)
            return

        try:
            cell = resolver(cell_id)
            dispatch_target = structured_card if structured_card else intent
            result = cell.execute_card(dispatch_target, domain=domain)
            self.complete(cid, result=result)
        except Exception as e:
            logger.warning("card %s dispatch failed: %s", cid, e)
            self.complete(cid, error=str(e))

    # ── Persistence ──

    def _serialize(self) -> dict:
        return {
            "cards": {cid: card.to_persist() for cid, card in self._cards.items()},
            "queue": list(self._queue),
            "cell_map": dict(self._cell_map),
        }

    def _deserialize(self, data: dict) -> bool:
        self._cards.clear()
        self._queue.clear()
        self._cell_map.clear()
        for cid, pd in data.get("cards", {}).items():
            card = CardUnified.from_persist(pd)
            if card.state not in (CardLifecycle.COMPLETED, CardLifecycle.FAILED, CardLifecycle.CANCELLED):
                pass
            self._cards[cid] = card
        self._queue[:] = data.get("queue", [])
        self._cell_map.update(data.get("cell_map", {}))
        return True

    # ── Plan generation ──

    def generate_plan(self, intent: str, domain: str = "") -> dict:
        try:
            from .llm import get_engine as _ge
            engine = _ge()
            from kernel.prompts import get_prompt as _gp
            prompt = _gp("card_registry.generate_plan", "").format(intent=intent, domain=domain)
            r = engine.generate(prompt,
                                system=_gp("card_registry.generate_plan.system", "You are a planning assistant."),
                                max_tokens=1024)
            content = r.get("content", "")
            plan = json.loads(content.strip().removeprefix("```json").removesuffix("```").strip())
            if not isinstance(plan, dict):
                raise ValueError("plan is not a dict")
            plan.setdefault("steps", [])
            plan.setdefault("estimated_files", 0)
            plan.setdefault("estimated_lines", 0)
            return plan
        except Exception:
            return {
                "summary": intent[:80],
                "steps": [{"action": "think", "target": intent[:40],
                           "description": f"Process: {intent[:60]}"}],
                "estimated_files": 1,
                "estimated_lines": 50,
                "verification": "manual review",
                "risk": "medium",
            }

    def get_card_plan(self, card_id: str) -> dict:
        with self._lock:
            rec = self._cards.get(card_id)
        if not rec:
            return {"success": False, "error": f"unknown card: {card_id}"}
        d = rec.to_dict(include_hidden=False)
        d["approval_status"] = ""
        d["approval_size"] = ""
        return {"success": True, "card_id": card_id, **d}

    # ── Cell registration ──

    def register_cell(self, cell_id: str, territories: list[str]) -> None:
        with self._lock:
            if cell_id not in self._cell_map:
                self._cell_map[cell_id] = {"territories": territories, "active_cards": 0}

    # ── Submit ──

    def submit(self, intent: str, domain: str = "",
               priority: int = 5, card_id: str = "",
               depends_on: list[str] | None = None) -> str:
        cid = card_id or f"card-{uuid.uuid4().hex[:8]}"
        with self._lock:
            if len(self._queue) >= CARD_QUEUE_PENDING_MAX:
                logger.warning("card queue full (%d/%d), rejecting: %s",
                               len(self._queue), CARD_QUEUE_PENDING_MAX, intent[:40])
                return ""
        card = CardUnified(id=cid, priority=priority)
        card.summary = CardSummary(title=intent, description="", columns={"domain": domain})
        card._depends_on = depends_on or []
        card.submit()
        with self._lock:
            self._cards[cid] = card
            self._queue.append(cid)
            self._queue.sort(key=lambda x: self._cards[x].priority if x in self._cards else 5)
        logger.info("card submitted: %s — %s", cid, intent[:60])
        emit_signal(EVENT_TASK_ASSIGN, sender="registry", target="l3",
                     data={"card_id": cid, "intent": intent[:60], "event": "submitted"})
        try:
            from .reference_channel import get_rc as _rc
            _rc().card_lifecycle(cid, intent, "submitted", nature="", size="")
        except Exception:
            pass
        return cid

    # ── Dispatch ──

    def dispatch(self, card_id: str, cell_id: str = "") -> dict:
        with self._lock:
            record = self._cards.get(card_id)
            if not record:
                return {"success": False, "error": f"unknown card: {card_id}"}
            if record.state != CardLifecycle.QUEUED:
                return {"success": False, "error": f"card {card_id} already dispatched"}

            if not cell_id and record.summary.columns.get("domain"):
                cell_id = self._match_cell(record.summary.columns.get("domain", ""))
            if not cell_id:
                cell_id = next(iter(self._cell_map.keys())) if self._cell_map else "cell-1"

            record.summary.columns["cell_id"] = cell_id
            record.dispatch()
            if card_id in self._queue:
                self._queue.remove(card_id)
            if cell_id in self._cell_map:
                self._cell_map[cell_id]["active_cards"] += 1

        logger.info("card dispatched: %s → %s", card_id, cell_id)
        emit_signal(EVENT_TASK_ASSIGN, sender="registry", target=cell_id,
                     data={"card_id": card_id, "event": "dispatched"})
        return {"success": True, "card_id": card_id, "cell_id": cell_id}

    # ── Complete / Cancel ──

    def complete(self, card_id: str, result: dict | None = None,
                 error: str = "") -> bool:
        with self._lock:
            record = self._cards.get(card_id)
            if not record:
                return False
            if error:
                record.fail(error)
            else:
                record.complete(summary="executed", changes=[result] if result else [])
            cell = self._cell_map.get(record.summary.columns.get("cell_id", ""))
            if cell:
                cell["active_cards"] = max(0, cell["active_cards"] - 1)
            if card_id in self._queue:
                self._queue.remove(card_id)
        emit_signal(EVENT_TASK_ASSIGN, sender="registry", target="l3",
                     data={"card_id": card_id, "state": record.state.value, "event": "completed"})
        # ── Task completion bus: fire webhooks ──
        try:
            from .task_bus import get_task_bus
            get_task_bus().dispatch(card_id, record.state.value, {
                "intent": record.summary.columns.get("intent", record.summary.title) if record.summary else "",
                "domain": record.summary.columns.get("domain", "") if record.summary else "",
                "result": result or {},
                "error": error,
                "elapsed": time.time() - record.timestamps.created_at if hasattr(record, 'timestamps') else 0,
            })
        except Exception as e:
            logger.warning("task_bus dispatch failed: %s", e)
        try:
            from .reference_channel import get_rc as _rc
            _rc().card_lifecycle(card_id, record.summary.title if record.summary else "",
                                 record.state.value, error=error)
        except Exception:
            pass
        return True

    def cancel(self, card_id: str) -> bool:
        with self._lock:
            record = self._cards.get(card_id)
            if not record or record.state in (CardLifecycle.COMPLETED, CardLifecycle.FAILED, CardLifecycle.CANCELLED):
                return False
            record.state = CardLifecycle.CANCELLED
            if card_id in self._queue:
                self._queue.remove(card_id)
            cell = self._cell_map.get(record.summary.columns.get("cell_id", ""))
            if cell:
                cell["active_cards"] = max(0, cell["active_cards"] - 1)
        return True

    # ── Query ──

    def get(self, card_id: str) -> CardUnified | None:
        with self._lock:
            return self._cards.get(card_id)

    def list(self, state: CardLifecycle | str | None = None,
             cell_id: str = "", domain: str = "", limit: int = 50) -> list[dict]:
        with self._lock:
            result = []
            for r in sorted(self._cards.values(), key=lambda x: x.timestamps.created_at, reverse=True):
                if state:
                    target = state.value if isinstance(state, CardLifecycle) else state
                    if r.state.value != target:
                        continue
                if cell_id and r.summary.columns.get("cell_id", "") != cell_id:
                    continue
                if domain and r.summary.columns.get("domain", "") != domain:
                    continue
                result.append(_card_to_dict(r))
                if len(result) >= limit:
                    break
            return result

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    def cell_load(self, cell_id: str) -> dict:
        with self._lock:
            cell = self._cell_map.get(cell_id)
            if not cell:
                return {"active_cards": 0, "territories": []}
            return dict(cell)

    def stats(self) -> dict:
        with self._lock:
            states: dict[str, int] = {}
            for r in self._cards.values():
                lc_state = r.state.value
                states[lc_state] = states.get(lc_state, 0) + 1
            return {
                "total": len(self._cards),
                "queue": len(self._queue),
                "cells": len(self._cell_map),
                "by_state": states,
            }

    def _match_cell(self, domain: str) -> str:
        best_cell = ""
        best_score = 0
        for cid, info in self._cell_map.items():
            score = sum(1 for t in info["territories"] if domain.startswith(t))
            if score > best_score:
                best_score, best_cell = score, cid
        return best_cell


_registry: CardRegistry | None = None


def get_registry() -> CardRegistry:
    global _registry
    if _registry is None:
        _registry = CardRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
