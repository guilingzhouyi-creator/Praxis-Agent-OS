"""CardDispatchMixin — background dispatcher, cell routing, and plan generation.

Extracted from card_registry.py (P2-1 split): the poll loop, per-tick
maintenance (_recheck_held / _escalate_stale), one-card dispatch, domain→cell
matching, cell registration, and LLM plan generation. Composed by
CardRegistry alongside the stats / convention / persistence mixins.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.params.agent import DEFAULT_CELL_ID, PLAN_GENERATION_MAX_TOKENS, SIGNAL_TARGET_L3
from l1.kernel.params.system import (
    CARD_DISPATCH_INTERVAL,
    CARD_STALE_ESCALATE_SECONDS,
    LOG_TRUNC_40,
    LOG_TRUNC_60,
    LOG_TRUNC_80,
)
from l3.services.model_service import get_service as _get_model_service

from .card_unified import CardLifecycle

_MODEL_SPEC = "card_planner"

logger = logging.getLogger(__name__)


class CardDispatchMixin:
    """Background dispatch, cell routing, and plan generation for cards."""

    def set_cell_resolver(self, resolver: Callable[[str], Any]) -> None:
        """Register the callable used to resolve a cell_id to a Cell object."""
        self._cell_resolver = resolver

    # ── Background dispatcher ──

    def start_dispatcher(self) -> None:
        """Start the background dispatcher thread if not already running."""
        if self._dispatcher_running:
            return
        self._dispatcher_running = True
        self._dispatcher_thread = threading.Thread(
            target=self._dispatcher_loop,
            daemon=True,
            name="card-dispatcher",
        )
        self._dispatcher_thread.start()
        logger.info("card dispatcher started (poll every %.1fs)", CARD_DISPATCH_INTERVAL)

    def stop_dispatcher(self) -> None:
        """Stop the background dispatcher thread."""
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
            held = [
                (cid, rec)
                for cid, rec in self._cards.items()
                if rec.state == CardLifecycle.QUEUED and rec.timestamps.dispatched_at > 0
            ]
        for cid, rec in held:
            try:
                from .card_gate import evaluate as _gate_evaluate

                gate_r = _gate_evaluate(cid, intent=rec.summary.title, domain=rec.nature)
                if gate_r.get("auto_approve", False):
                    logger.info("card %s un-held by card gate, re-queued", cid)
            except Exception:
                logger.debug("card_registry: gate auto-approve failed")

    def _escalate_stale(self) -> None:
        now = time.time()
        with self._lock:
            for cid, rec in list(self._cards.items()):
                if (
                    rec.state == CardLifecycle.QUEUED
                    and (now - rec.timestamps.created_at) > CARD_STALE_ESCALATE_SECONDS
                ):
                    logger.warning("card %s stale (>1h), escalating", cid)
                    rec.state = CardLifecycle.CANCELLED
                    if cid in self._queue:
                        self._queue.remove(cid)
                    emit_signal(
                        EVENT_TASK_ASSIGN,
                        sender="registry",
                        target=SIGNAL_TARGET_L3,
                        data={"card_id": cid, "event": "stale_escalated"},
                    )

    # ── Dispatch one card ──

    def _dispatch_one(self) -> None:
        cid = None
        with self._lock:
            for c in self._queue:
                if self._is_placeholder(c):
                    continue
                record = self._cards.get(c)
                if not record or record.state == CardLifecycle.HOLD:
                    continue
                if record.state == CardLifecycle.QUEUED:
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
            # Prefer CardUnified directly (new architecture), fall back to
            # raw intent string for simple dispatch.
            structured_card = None
            if hasattr(record, "phases") and any(p.tasks for p in record.phases):
                structured_card = record  # CardUnified is natively supported

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
                from l3.card.pending_queue import get_queue

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

        # ── Assembly CONFERENCE routing: disputed cards go to Convention ──
        if record.summary.columns.get("_assembly_mode") == "conference":
            self._route_to_convention(cid, intent, domain)
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
            t_cell = time.time()
            result = cell.execute_card(dispatch_target, domain=domain)
            cell_elapsed = round(time.time() - t_cell, 3)
            self._record_card_executions(cid, cell_id, cell_elapsed, result)
            # DPO-style preference signal (batch 2): attribute card outcome
            # to the skills used, adjusting their rules' verified/hit weights.
            try:
                _used = (result or {}).get("card_skills_used") or []
                if _used:
                    from l3.memory.r4_agent import get_r4_agent

                    get_r4_agent().record_card_skill_signal(
                        skills_used=_used,
                        success=bool((result or {}).get("success")),
                    )
            except Exception as e:
                logger.debug("card_registry: skill preference signal skipped: %s", e)
            self.complete(cid, result=result)
            self._expose_card_execution(cid, cell_id, cell_elapsed, result)
        except Exception as e:
            logger.warning("card %s dispatch failed: %s", cid, e)
            self.complete(cid, error=str(e))

    # ── Dispatch ──

    def dispatch(self, card_id: str, cell_id: str = "") -> dict:
        """Dispatch a queued card to a Cell, resolving the target by domain if needed."""
        with self._lock:
            record = self._cards.get(card_id)
            if not record:
                return {"success": False, "error": f"unknown card: {card_id}"}
            if record.state != CardLifecycle.QUEUED:
                return {"success": False, "error": f"card {card_id} already dispatched"}

            if not cell_id and record.summary.columns.get("domain"):
                cell_id = self._match_cell(record.summary.columns.get("domain", ""))
            if not cell_id:
                cell_id = next(iter(self._cell_map.keys())) if self._cell_map else DEFAULT_CELL_ID

            record.summary.columns["cell_id"] = cell_id
            record.dispatch()
            if card_id in self._queue:
                self._queue.remove(card_id)
            if cell_id in self._cell_map:
                self._cell_map[cell_id]["active_cards"] += 1

        logger.info("card dispatched: %s → %s", card_id, cell_id)
        emit_signal(
            EVENT_TASK_ASSIGN, sender="registry", target=cell_id, data={"card_id": card_id, "event": "dispatched"}
        )
        return {"success": True, "card_id": card_id, "cell_id": cell_id}

    def _match_cell(self, domain: str) -> str:
        best_cell = ""
        best_score = 0
        for cid, info in self._cell_map.items():
            score = sum(1 for t in info["territories"] if domain.startswith(t))
            if score > best_score:
                best_score, best_cell = score, cid
        return best_cell

    # ── Cell registration ──

    def register_cell(self, cell_id: str, territories: list[str]) -> None:
        """Register a Cell with its territories for dispatch routing."""
        with self._lock:
            if cell_id not in self._cell_map:
                self._cell_map[cell_id] = {"territories": territories, "active_cards": 0}

    # ── Plan generation ──

    def generate_plan(self, intent: str, domain: str = "") -> dict:
        """Generate an execution plan for a card via the LLM, falling back to a default."""
        try:
            from l4.llm.llm import get_engine as _ge

            engine = _ge()
            from l1.kernel.prompts import get_prompt as _gp

            prompt = _gp("card_registry.generate_plan", "").format(intent=intent, domain=domain)
            r = engine.generate(
                prompt,
                system=_gp("card_registry.generate_plan.system", "You are a planning assistant."),
                max_tokens=PLAN_GENERATION_MAX_TOKENS,
                **_get_model_service().resolve_dict(_MODEL_SPEC),
            )
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
                "summary": intent[:LOG_TRUNC_80],
                "steps": [
                    {
                        "action": "think",
                        "target": intent[:LOG_TRUNC_40],
                        "description": f"Process: {intent[:LOG_TRUNC_60]}",
                    }
                ],
                "estimated_files": 1,
                "estimated_lines": 50,
                "verification": "manual review",
                "risk": "medium",
            }

    def get_card_plan(self, card_id: str) -> dict:
        """Return a card's plan and details dict, or an error dict if unknown."""
        with self._lock:
            rec = self._cards.get(card_id)
        if not rec:
            return {"success": False, "error": f"unknown card: {card_id}"}
        d = rec.to_dict(include_hidden=False)
        d["approval_status"] = ""
        d["approval_size"] = ""
        return {"success": True, "card_id": card_id, **d}
