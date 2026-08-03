"""CardRegistry — central card queue, status tracking, auto-dispatch, persistent.

Cards enter the registry, are queued by priority, dispatched to Cells
by territory match, executed, and tracked through completion.

Persistence: JSON file at get_paths().card_registry, auto-saved every 30s.

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
from collections.abc import Callable
from typing import Any

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.params.agent import DEFAULT_CELL_ID, SIGNAL_TARGET_L3
from l1.kernel.params.system import (
    CARD_DISPATCH_INTERVAL,
    CARD_QUEUE_PENDING_MAX,
    CARD_REGISTRY_AUTO_SAVE,
    CARD_STALE_ESCALATE_SECONDS,
    HASH_TRUNC_SHORT,
    LOG_TRUNC_40,
    LOG_TRUNC_60,
    LOG_TRUNC_80,
    LOG_TRUNC_500,
)
from l1.kernel.paths import get_paths as _gp
from l3._persistable import PersistableMixin
from l3.services.model_service import get_service as _get_model_service

from .card_unified import CardExecution as _CardExecution
from .card_unified import CardLifecycle, CardSummary, CardUnified

_MODEL_SPEC = "card_planner"

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
    d["plan_summary"] = r.summary.title[:LOG_TRUNC_80] if r.summary.title else ""
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
        self._subscribers: dict[str, list[Callable[[str, str, dict], None]]] = {}
        self._init_persistence(persist_path or _gp().card_registry, CARD_REGISTRY_AUTO_SAVE)
        self._restore()
        if CARD_REGISTRY_AUTO_SAVE > 0:
            self._start_auto_save()

    # ── Completion subscription (external closed-loop callbacks) ──

    def subscribe(self, card_id: str,
                  callback: Callable[[str, str, dict], None]) -> None:
        """Register a completion callback for a card.

        Callback signature: (card_id, state, result) — fired on COMPLETED,
        FAILED, or CANCELLED. Used by L3A sessions to receive card results.
        """
        with self._lock:
            self._subscribers.setdefault(card_id, []).append(callback)

    def unsubscribe(self, card_id: str, callback: Callable | None = None) -> None:
        """Remove a callback for a card (all if callback omitted)."""
        with self._lock:
            if card_id not in self._subscribers:
                return
            if callback is None:
                del self._subscribers[card_id]
            else:
                self._subscribers[card_id] = [
                    cb for cb in self._subscribers[card_id] if cb != callback
                ]

    def _notify_subscribers(self, card_id: str, state: str,
                            result: dict | None = None) -> None:
        with self._lock:
            callbacks = list(self._subscribers.get(card_id, []))
        for cb in callbacks:
            try:
                cb(card_id, state, result or {})
            except Exception as e:
                logger.warning("card %s subscriber callback failed: %s", card_id, e)
            finally:
                self.unsubscribe(card_id, cb)

    # ── Approval (explicit approve/reject for HOLD cards) ──

    def approve(self, card_id: str) -> dict:
        """Approve a held card: restore from placeholder and re-queue.

        Fires dispatch on the next dispatcher tick.
        """
        with self._lock:
            record = self._cards.get(card_id)
            if not record:
                return {"success": False, "error": f"unknown card: {card_id}"}
            if record.state != CardLifecycle.HOLD:
                return {"success": False, "error": f"card {card_id} not in HOLD state"}
            restored = self.restore_card(card_id)
            record.state = CardLifecycle.QUEUED
            if not restored:
                if card_id not in self._queue:
                    self._queue.append(card_id)
                    self._queue.sort(key=lambda x: self._cards[x].priority
                                     if x in self._cards else 5)
        logger.info("card approved: %s", card_id)
        emit_signal(EVENT_TASK_ASSIGN, sender="registry", target=SIGNAL_TARGET_L3,
                     data={"card_id": card_id, "event": "approved"})
        return {"success": True, "card_id": card_id, "state": "QUEUED"}

    def reject(self, card_id: str, reason: str = "") -> dict:
        """Reject a held card: cancel it and notify dependents."""
        with self._lock:
            record = self._cards.get(card_id)
            if not record:
                return {"success": False, "error": f"unknown card: {card_id}"}
            if record.state not in (CardLifecycle.HOLD, CardLifecycle.QUEUED):
                return {"success": False, "error": f"card {card_id} not in HOLD/QUEUED state"}
            record.state = CardLifecycle.CANCELLED
            if card_id in self._queue:
                self._queue.remove(card_id)
            if reason:
                record.error = reason[:LOG_TRUNC_80]
        dependents = self._find_dependents(card_id)
        for dep_cid in dependents:
            with self._lock:
                dep = self._cards.get(dep_cid)
                if dep:
                    dep.state = CardLifecycle.CANCELLED
                    if dep_cid in self._queue:
                        self._queue.remove(dep_cid)
        logger.info("card rejected: %s (reason=%s, dependents=%d)",
                    card_id, reason[:LOG_TRUNC_40] or "none", len(dependents))
        emit_signal(EVENT_TASK_ASSIGN, sender="registry", target=SIGNAL_TARGET_L3,
                     data={"card_id": card_id, "event": "rejected", "reason": reason[:LOG_TRUNC_80]})
        self._notify_subscribers(card_id, CardLifecycle.CANCELLED.value, {"reason": reason})
        return {"success": True, "card_id": card_id, "state": "CANCELLED",
                "dependents_cancelled": len(dependents)}

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
                logger.debug("card_registry: gate auto-approve failed")

    def _escalate_stale(self) -> None:
        now = time.time()
        with self._lock:
            for cid, rec in list(self._cards.items()):
                if rec.state == CardLifecycle.QUEUED and (now - rec.timestamps.created_at) > CARD_STALE_ESCALATE_SECONDS:
                    logger.warning("card %s stale (>1h), escalating", cid)
                    rec.state = CardLifecycle.CANCELLED
                    if cid in self._queue:
                        self._queue.remove(cid)
                    emit_signal(EVENT_TASK_ASSIGN, sender="registry", target=SIGNAL_TARGET_L3,
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
            record = self._cards.get(card_id)
            if record:
                record.state = CardLifecycle.HOLD

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
            if hasattr(record, 'phases') and any(p.tasks for p in record.phases):
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
            self.complete(cid, result=result)
            self._expose_card_execution(cid, cell_id, cell_elapsed, result)
        except Exception as e:
            logger.warning("card %s dispatch failed: %s", cid, e)
            self.complete(cid, error=str(e))

    def _record_card_executions(self, card_id: str, cell_id: str,
                                cell_elapsed: float, result: dict) -> None:
        """Attach per-executor wall-time to the card record.

        Granularity:
          one cell-level entry (executor == cell_id)
          one entry per Peer Agent step (from ExecutionPlan step results)
        """
        with self._lock:
            rec = self._cards.get(card_id)
            if not rec:
                return
            now = time.time()
            rec.executions.append(_CardExecution(
                executor=cell_id, cell_id=cell_id, phase="cell",
                started_at=now - cell_elapsed, finished_at=now,
                elapsed=cell_elapsed,
                success=bool(result and result.get("success")),
            ))
            seen: dict[str, float] = {}
            steps = (result or {}).get("steps", []) or []
            if not steps and result:
                steps = result.get("results", []) or []
            for st in steps:
                if not isinstance(st, dict):
                    continue
                aid = st.get("agent_id", "")
                if not aid:
                    continue
                el = float(st.get("elapsed", 0) or 0)
                if aid in seen:
                    seen[aid] += el
                    continue
                seen[aid] = el
            rec.executions.append(_CardExecution(
                    executor=aid, cell_id=cell_id,
                    phase=st.get("phase", "step"),
                    started_at=now - cell_elapsed, finished_at=now,
                    elapsed=el, success=bool(st.get("success")),
                ))

    def _expose_card_execution(self, card_id: str, cell_id: str,
                               cell_elapsed: float, result: dict) -> None:
        """Publish card end-to-end timing to monitoring + statistics centers."""
        try:
            rec = self._cards.get(card_id)
            total = 0.0
            if rec and rec.timestamps.completed_at and rec.timestamps.created_at:
                total = round(rec.timestamps.completed_at - rec.timestamps.created_at, 3)
        except Exception:
            total = 0.0
        agents = {}
        for e in getattr(rec, "executions", []) or []:
            if e.executor and e.executor != cell_id:
                agents[e.executor] = agents.get(e.executor, 0.0) + e.elapsed
        try:
            from l3.bus.monitor_bus import MonitorEvent as _ME5
            from l3.bus.monitor_bus import get_bus as _MB5
            _MB5().emit(_ME5(
                type="stats.card.execution", source="card_registry",
                severity="info",
                message=f"{card_id} cell={cell_id} {cell_elapsed}s agents={len(agents)}",
                card_id=card_id, cell_id=cell_id,
                data={"card_id": card_id, "cell_id": cell_id,
                      "cell_elapsed": cell_elapsed,
                      "total_elapsed": total,
                      "agents": agents,
                      "success": bool(result and result.get("success"))}))
        except Exception:
            logger.debug("card_registry: monitor emit failed")
        try:
            from l3.services.stats_center import MetricPoint as _MP5
            from l3.services.stats_center import get_center as _SC5
            _ts = time.time()
            _tags = {"card": card_id, "cell": cell_id}
            _SC5().ingest(_MP5(name="card.execution.total", value=total,
                               tags=_tags, timestamp=_ts, metric_type="gauge"))
            _SC5().ingest(_MP5(name="card.execution.cell", value=cell_elapsed,
                               tags=_tags, timestamp=_ts, metric_type="gauge"))
            for aid, el in agents.items():
                _SC5().ingest(_MP5(name="card.execution.agent", value=round(el, 3),
                                   tags={"card": card_id, "cell": cell_id, "agent": aid},
                                   timestamp=_ts, metric_type="gauge"))
        except Exception:
            logger.debug("card_registry: stats emit failed")

    # ── Assembly CONFERENCE routing ──

    def _route_to_convention(self, card_id: str, intent: str,
                             domain: str) -> None:
        """Route a card to ConventionProtocol instead of direct Cell dispatch.

        Creates an IssueCard linked to the source card, convenes the Cell's
        peer agents, and holds the source card until convergence completes
        (close_convention() completes it via source_card_id).
        """
        resolver = self._cell_resolver
        if not resolver:
            logger.warning("card %s: no cell resolver for convention", card_id)
            self.complete(card_id, error="no cell resolver for convention")
            return
        cell_id = ""
        try:
            cell_id = next(iter(self._cell_map.keys())) if self._cell_map else ""
            cell = resolver(cell_id)
        except Exception as e:
            logger.warning("card %s: convention cell resolve failed: %s", card_id, e)
            self.complete(card_id, error=f"convention cell resolve failed: {e}")
            return

        try:
            from l3.card.issue import IssueCard, get_table
            issue = IssueCard(title=intent, intent=intent, domain=domain)
            issue.agent_ids = list(cell._agents.keys())
            issue.cell_id = cell.cell_id
            issue.source_card_id = card_id
            get_table().submit(issue)

            from l3.cell.components.cell_convention import convene
            conv_r = convene(cell, issue)
            with self._lock:
                rec = self._cards.get(card_id)
                if rec:
                    rec.summary.columns["_issue_card_id"] = issue.id
            self.hold_card(card_id)
            logger.info("card %s routed to convention %s (%d agents)",
                        card_id, issue.id, len(issue.agent_ids))
        except Exception as e:
            logger.warning("card %s convention start failed: %s", card_id, e)
            self.complete(card_id, error=f"convention start failed: {e}")

    def _complete_convention_card(self, issue_card_id: str,
                                  convergence_doc: str = "") -> None:
        """Complete the source card after a convention converges.

        Only a bounded summary + file/archive references are injected into
        the session — the full deliberation .md stays on disk (readable via
        l3a_convention) to avoid polluting the session context window.
        """
        try:
            from l3.card.issue import get_table
            issue = get_table().get(issue_card_id)
        except Exception:
            issue = None
        if not issue or not issue.source_card_id:
            return
        src = issue.source_card_id
        with self._lock:
            rec = self._cards.get(src)
            if not rec or rec.state == CardLifecycle.COMPLETED:
                return
        # Locate persisted doc file for the reference
        doc_path = ""
        try:
            import os as _os

            from l1.kernel.params.agent import CONVENTION_DOC_DIR
            from l1.kernel.paths import get_paths as _gp
            doc_path = _os.path.join(_gp().data_dir, CONVENTION_DOC_DIR,
                                     f"{issue_card_id}.md")
            if not _os.path.isfile(doc_path):
                doc_path = ""
        except Exception:
            doc_path = ""
        self.complete(src, result={
            "convergence": convergence_doc[:LOG_TRUNC_500],
            "issue_card_id": issue_card_id,
            "doc_path": doc_path,
            "archive_ref": f"CONVENTION:{issue_card_id}",
        })
        logger.info("card %s completed after convention %s (doc=%s)",
                    src, issue_card_id, doc_path or "n/a")

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
            from l4.llm.llm import get_engine as _ge
            engine = _ge()
            from l1.kernel.prompts import get_prompt as _gp
            prompt = _gp("card_registry.generate_plan", "").format(intent=intent, domain=domain)
            r = engine.generate(prompt,
                                system=_gp("card_registry.generate_plan.system", "You are a planning assistant."),
                                max_tokens=1024,
                                **_get_model_service().resolve_dict(_MODEL_SPEC))
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
                "steps": [{"action": "think", "target": intent[:LOG_TRUNC_40],
                           "description": f"Process: {intent[:LOG_TRUNC_60]}"}],
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
        cid = card_id or f"card-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        with self._lock:
            if len(self._queue) >= CARD_QUEUE_PENDING_MAX:
                logger.warning("card queue full (%d/%d), rejecting: %s",
                               len(self._queue), CARD_QUEUE_PENDING_MAX, intent[:LOG_TRUNC_40])
                return ""
        card = CardUnified(id=cid, priority=priority)
        card.summary = CardSummary(title=intent, description="", columns={"domain": domain})
        card._depends_on = depends_on or []
        card.submit()
        with self._lock:
            self._cards[cid] = card
            self._queue.append(cid)
            self._queue.sort(key=lambda x: self._cards[x].priority if x in self._cards else 5)
        logger.info("card submitted: %s — %s", cid, intent[:LOG_TRUNC_60])
        emit_signal(EVENT_TASK_ASSIGN, sender="registry", target=SIGNAL_TARGET_L3,
                     data={"card_id": cid, "intent": intent[:LOG_TRUNC_60], "event": "submitted"})
        try:
            from l3.bus.reference_channel import get_rc as _rc
            _rc().card_lifecycle(cid, intent, "submitted", nature="", size="")
        except Exception:
            logger.debug("card_registry: rc lifecycle submit failed")
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
                cell_id = next(iter(self._cell_map.keys())) if self._cell_map else DEFAULT_CELL_ID

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
        emit_signal(EVENT_TASK_ASSIGN, sender="registry", target=SIGNAL_TARGET_L3,
                     data={"card_id": card_id, "state": record.state.value, "event": "completed"})
        # ── Completion subscribers (L3A session closed loop) ──
        self._notify_subscribers(card_id, record.state.value, result or {"error": error})
        # ── Task completion bus: fire webhooks ──
        try:
            from l3.bus.task_bus import get_task_bus
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
            from l3.bus.reference_channel import get_rc as _rc
            _rc().card_lifecycle(card_id, record.summary.title if record.summary else "",
                                 record.state.value, error=error)
        except Exception:
            logger.debug("card_registry: rc lifecycle update failed")
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
        self._notify_subscribers(card_id, CardLifecycle.CANCELLED.value, {"reason": "cancelled"})
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

    def execution_stats(self, limit: int = 20) -> dict:
        """Card end-to-end timing with per-Cell and per-Peer-Agent breakdown.

        Returns:
          cards:      per-card total (created→completed) + cell + agent sums
          by_cell:    aggregated cell wall-time across cards
          by_agent:   aggregated per-Peer-Agent wall-time across cards
        """
        with self._lock:
            cards = []
            by_cell: dict[str, dict] = {}
            by_agent: dict[str, dict] = {}
            for r in sorted(self._cards.values(),
                            key=lambda x: x.timestamps.completed_at or 0,
                            reverse=True):
                if not r.executions:
                    continue
                total = 0.0
                if r.timestamps.completed_at and r.timestamps.created_at:
                    total = round(r.timestamps.completed_at - r.timestamps.created_at, 3)
                cell_t = 0.0
                agent_t: dict[str, float] = {}
                for e in r.executions:
                    if e.executor == e.cell_id:
                        cell_t += e.elapsed
                    else:
                        agent_t[e.executor] = agent_t.get(e.executor, 0.0) + e.elapsed
                cards.append({
                    "card_id": r.id,
                    "state": r.state.value,
                    "title": r.summary.title[:LOG_TRUNC_80],
                    "total_elapsed": total,
                    "cell_elapsed": round(cell_t, 3),
                    "agents": {k: round(v, 3) for k, v in agent_t.items()},
                    "executions": [e.to_dict() for e in r.executions],
                })
                for e in r.executions:
                    if e.executor == e.cell_id:
                        agg = by_cell.setdefault(e.cell_id,
                                                 {"cards": 0, "elapsed": 0.0})
                        agg["cards"] += 1
                        agg["elapsed"] += e.elapsed
                    else:
                        agg = by_agent.setdefault(e.executor,
                                                  {"cards": 0, "elapsed": 0.0})
                        agg["cards"] += 1
                        agg["elapsed"] += e.elapsed
                if len(cards) >= limit:
                    break
            return {
                "cards": cards,
                "by_cell": {k: {"cards": v["cards"],
                                "elapsed": round(v["elapsed"], 3)}
                            for k, v in by_cell.items()},
                "by_agent": {k: {"cards": v["cards"],
                                 "elapsed": round(v["elapsed"], 3)}
                             for k, v in by_agent.items()},
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
