"""CellEventsMixin — component accessors, watchdog callbacks, bus wiring.

Provides the Cell's hardware-style component accessors (pmu, watchdog,
icache, mmu, tlb, interrupt, cache, permission), the watchdog lifecycle
callbacks, and all SystemBus/EventBus wiring and event handlers. Composed
by Cell; ``_wire_interrupts`` is invoked from ``Cell.__init__``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from l1.kernel import Signal, SignalType
from l1.kernel.params.system import IRQ_DISPATCH_BATCH

if TYPE_CHECKING:
    from .cell_watchdog import WatchdogState

logger = logging.getLogger(__name__)


class CellEventsMixin:
    """Component accessors + watchdog callbacks + event bus wiring/handlers."""

    # ── Cell L2 shared cache ──

    @property
    def cache(self):
        """Access the Cell L2 shared cache (CellCache).

        Agents in the same Cell share hot data here via
        inject/lookup/search — low-token-cost cross-agent sharing.
        """
        return self._cache

    # ── PMU (Performance Monitoring Unit) ──

    @property
    def pmu(self):
        """Access the Cell PMU — hardware-style performance counters."""
        return self._pmu

    # ── Watchdog (per-agent liveness monitor) ──

    @property
    def watchdog(self):
        """Access the Cell Watchdog — monitors agent liveness via pet()."""
        return self._watchdog

    def _watchdog_on_timeout(self, agent_id: str, state: WatchdogState) -> None:
        """Called when an agent misses a pet deadline — mark UNRESPONSIVE."""
        logger.warning("watchdog timeout: %s → %s", agent_id, state.name)
        try:
            from ..agent_terminal import get_terminal

            term = get_terminal(agent_id)
            if term:
                term.pause()
        except Exception as e:
            logger.warning("watchdog pause failed: %s", e)

    def _watchdog_on_recovery(self, agent_id: str) -> None:
        """Called when an agent pets after being UNRESPONSIVE — resume."""
        logger.info("watchdog recovery: %s", agent_id)
        try:
            from ..agent_terminal import get_terminal

            term = get_terminal(agent_id)
            if term:
                term.resume()
        except Exception as e:
            logger.warning("watchdog resume failed: %s", e)

    def _watchdog_on_crash(self, agent_id: str) -> None:
        """Called after consecutive misses — NMI + TLB flush + auto-reboot."""
        logger.error("watchdog crash: %s — NMI + auto-reboot", agent_id)
        self._pmu.increment("agent.crashes")
        self._mmu.flush_agent(agent_id)
        self._interrupt.trigger("watchdog.crash", data={"agent_id": agent_id})
        try:
            from ..agent_terminal import get_terminal

            term = get_terminal(agent_id)
            if term:
                term.shutdown()
                term.boot()
                self._pmu.increment("agent.recoveries")
        except Exception as e:
            logger.warning("watchdog reboot failed: %s", e)

    # ── I-Cache (Instruction Cache) ──

    @property
    def icache(self):
        """Access the Cell I-Cache — instruction cache for tools/templates/territory maps."""
        return self._icache

    # ── MMU + TLB (Memory Management Unit) ──

    @property
    def mmu(self):
        """Access the Cell MMU — territory→agent translation unit."""
        return self._mmu

    @property
    def tlb(self):
        """Access the Cell TLB — translation lookaside buffer (part of MMU)."""
        return self._mmu.tlb

    # ── InterruptController (Priority Interrupt) ──

    @property
    def interrupt(self):
        """Access the Cell InterruptController — priority-based event routing."""
        return self._interrupt

    # ── PermissionController (Delegation Control) ──

    @property
    def permission(self):
        """Access the Cell PermissionController — delegation authorization."""
        return self._permission

    def _wire_interrupts(self) -> None:
        """Wire built-in handlers to interrupt IRQs + cell bus events."""
        if self._interrupt:
            self._interrupt.set_handler(
                "task.assign", lambda e: self._pmu.increment("bus.signals_emitted") if self._pmu else None
            )
            self._interrupt.set_handler(
                "token.usage", lambda e: self._pmu.increment("token.consumed") if self._pmu else None
            )
            self._interrupt.set_handler("cache.flush", lambda e: self._cache.flush() if self._cache else None)
            self._interrupt.set_handler(
                "constitution.violation", lambda e: self._mmu.flush_all() if self._mmu else None
            )

        # Wire cell bus events (watchdog → TLB flush, etc.)
        try:
            self._cell_bus.on("watchdog.crash", lambda e: self._bus_watchdog_crash(e))
            self._cell_bus.on("watchdog.timeout", lambda e: self._bus_watchdog_timeout(e))
            self._cell_bus.on("watchdog.recovery", lambda e: self._bus_watchdog_recovery(e))
        except Exception as e:
            logger.warning("cell/__init__: %s", e)

        # Wire agent removal → sandbox cleanup
        try:
            self._cell_bus.on("cell.agent_removed", self._bus_agent_removed)
        except Exception as e:
            logger.warning("cell/__init__: %s", e)

        # Wire discussion events (Layer 3 integration)
        try:
            self._cell_bus.on("discussion.start", lambda e: self._bus_discussion_start(e))
        except Exception as e:
            logger.warning("cell/__init__: %s", e)

        # Wire SystemBus events that were emitted but had no handlers (G5):
        # interrupt.triggered, pmu.snapshot, discussion.cell_complete.
        try:
            self._cell_bus.on("interrupt.triggered", lambda e: self._bus_interrupt_triggered(e))
            self._cell_bus.on("pmu.snapshot", lambda e: self._bus_pmu_snapshot(e))
            self._cell_bus.on("discussion.cell_complete", lambda e: self._bus_discussion_complete(e))
        except Exception as e:
            logger.warning("cell/__init__: %s", e)

        # Wire EventBus typed subscriptions (consume orphan signals: TASK_ASSIGN,
        # REVIEW_REQUESTED, FILE_CHANGED previously had zero subscribers).
        try:
            self._bus.on(SignalType.TASK_ASSIGN, self._on_task_assign)
            self._bus.on(SignalType.REVIEW_REQUESTED, self._on_review_requested)
            self._bus.on(SignalType.FILE_CHANGED, self._on_file_changed)
            # G3: internal consumer for hook-emitted string events so they are
            # not only broadcast to SSE wildcard listeners.
            self._bus.on_event("agent.turn_complete", self._on_turn_complete)
        except Exception as e:
            logger.warning("cell/__init__: event bus subscribe: %s", e)

    def _on_turn_complete(self, sig: Signal) -> None:
        """EventBus: consume agent.turn_complete string event (G3)."""
        if self._pmu:
            self._pmu.increment("bus.turns_complete")
        logger.debug("cell %s: turn complete: %s", self.cell_id, sig.data)

    def _bus_interrupt_triggered(self, event: dict) -> None:
        """SystemBus event: an interrupt was triggered on this cell."""
        if self._pmu:
            self._pmu.increment("interrupts.received")
        logger.debug("cell %s: interrupt triggered: %s", self.cell_id, event.get("data", {}))

    def _bus_pmu_snapshot(self, event: dict) -> None:
        """SystemBus event: a PMU snapshot was published for this cell."""
        if event.get("data", {}).get("cell_id") not in ("", self.cell_id):
            return
        if self._pmu:
            self._pmu.increment("bus.pmu_snapshots")
        logger.debug("cell %s: pmu snapshot", self.cell_id)

    def _bus_discussion_complete(self, event: dict) -> None:
        """SystemBus event: a discussion completed for this cell."""
        if self._pmu:
            self._pmu.increment("bus.discussions_complete")
        logger.debug("cell %s: discussion complete: %s", self.cell_id, event.get("data", {}))

    def _on_task_assign(self, sig: Signal) -> None:
        """EventBus: consume TASK_ASSIGN targeted at this cell."""
        if sig.target not in ("", "cell", self.cell_id):
            return
        if self._pmu:
            self._pmu.increment("bus.task_assign_received")
        logger.debug("cell %s: task assigned: %s", self.cell_id, sig.data)

    def _on_review_requested(self, sig: Signal) -> None:
        """EventBus: consume REVIEW_REQUESTED (was unsubscribed)."""
        if self._pmu:
            self._pmu.increment("bus.reviews_requested")
        logger.debug("cell %s: review requested: %s", self.cell_id, sig.data)

    def _on_file_changed(self, sig: Signal) -> None:
        """EventBus: consume FILE_CHANGED from the sandbox (was unsubscribed)."""
        if sig.data.get("cell_id") not in ("", self.cell_id):
            return
        if self._pmu:
            self._pmu.increment("bus.files_changed")
        logger.debug("cell %s: file changed: %s", self.cell_id, sig.data.get("path"))

    def _bus_discussion_start(self, event: dict) -> None:
        """Bus event: start an AnswerSession for this Cell."""
        try:
            from l3.card.issue import get_table
            from l3.discussion.answer_session import AnswerSession

            data = event.get("data", {})
            session_id = data.get("session_id", "")
            issue_card_id = data.get("issue_card_id", "")
            if not session_id or not issue_card_id:
                return
            card = get_table().get(issue_card_id)
            if not card:
                return
            session = AnswerSession(session_id, self.cell_id, self, card)
            result = session.run()
            if result.get("success"):
                self._cell_bus.emit(
                    "discussion.cell_complete",
                    {
                        "session_id": session_id,
                        "cell_id": self.cell_id,
                        "answer_count": result.get("phases", {}).get(5, {}).get("answers", 0),
                        "supplement_count": result.get("phases", {}).get(3, {}).get("supplements", 0),
                    },
                )
        except Exception as e:
            logger.warning("discussion start failed: %s", e)

    def _bus_watchdog_timeout(self, event: dict) -> None:
        """Bus event: watchdog timeout → pause terminal."""
        agent_id = event.get("data", {}).get("agent_id", "")
        if not agent_id:
            return
        try:
            from ..agent_terminal import get_terminal

            term = get_terminal(agent_id)
            if term:
                term.pause()
        except Exception as e:
            logger.warning("watchdog pause failed: %s", e)

    def _bus_watchdog_recovery(self, event: dict) -> None:
        """Bus event: watchdog recovery → resume terminal."""
        agent_id = event.get("data", {}).get("agent_id", "")
        if not agent_id:
            return
        try:
            from ..agent_terminal import get_terminal

            term = get_terminal(agent_id)
            if term:
                term.resume()
        except Exception as e:
            logger.warning("watchdog resume failed: %s", e)

    def _bus_watchdog_crash(self, event: dict) -> None:
        """Bus event: watchdog crash → NMI + TLB flush + auto-reboot."""
        agent_id = event.get("data", {}).get("agent_id", "")
        if not agent_id:
            return
        logger.error("watchdog crash: %s — NMI + auto-reboot", agent_id)
        if self._pmu:
            self._pmu.increment("agent.crashes")
        if self._mmu:
            self._mmu.flush_agent(agent_id)
        if self._interrupt:
            self._interrupt.trigger("watchdog.crash", data={"agent_id": agent_id})
        try:
            from ..agent_terminal import get_terminal

            term = get_terminal(agent_id)
            if term:
                term.shutdown()
                term.boot()
                if self._pmu:
                    self._pmu.increment("agent.recoveries")
        except Exception as e:
            logger.warning("watchdog reboot failed: %s", e)

    def _bus_agent_removed(self, event: dict) -> None:
        """Cell bus event: agent removed → clean up sandbox _path_index."""
        agent_id = event.get("data", {}).get("agent_id", "")
        if not agent_id:
            return
        try:
            from l4.sandbox.cell_sandbox import get_manager as _get_sm

            sb = _get_sm().get_cell(self.cell_id)
            if sb:
                sb.discard(agent_id)
        except Exception as e:
            logger.warning("sandbox cleanup for %s failed: %s", agent_id, e)

    def dispatch_pending_interrupts(self, max_per: int = IRQ_DISPATCH_BATCH) -> int:
        """Dispatch pending queued interrupts. Called periodically."""
        return self._interrupt.dispatch_pending(max_total=max_per)
