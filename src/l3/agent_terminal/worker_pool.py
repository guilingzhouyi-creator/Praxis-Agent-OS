"""WorkerPoolMixin — worker-thread pool + boot orchestration for AgentTerminal.

Extracted from agent_terminal/__init__.py (P1-2 split).  ``TerminalStatus`` /
``CardResult`` / ``run_cache_keepalive`` are imported lazily from the parent
module to avoid a circular import.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from l1.kernel import emit_signal
from l1.kernel.params.agent import AGENT_TERMINAL_RESULTS_MAX, EVENT_TASK_ASSIGN, SUBAGENT_MAX_TOKENS
from l1.kernel.params.system import (
    LOG_TRUNC_40,
    LOG_TRUNC_120,
    LOG_TRUNC_300,
    POLL_INTERVAL_FAST,
    POLL_INTERVAL_PAUSED,
)

if TYPE_CHECKING:
    from collections import OrderedDict, deque
    from collections.abc import Callable

    from l1.kernel.constitution import Constitution
    from l3.agent._term_types import CardResult, TerminalCard, TerminalStatus
    from l3.agent.agent_persist import SnapshotHook
    from l3.memory.cache import ContextRegister

logger = logging.getLogger(__name__)


class WorkerPoolMixin:
    """WorkerPoolMixin — boot sequence and the per-worker card loop."""

    # ── Attributes injected by the concrete AgentTerminal (see agent_terminal/__init__.py) ──
    agent_id: str
    role: str
    territory: list[str]
    cell_id: str
    ring: int
    constitution: Constitution
    status: TerminalStatus
    context: ContextRegister
    _boot_result: dict
    _snapshot_hook: SnapshotHook | None
    _running: bool
    _max_workers: int
    _workers: list[threading.Thread]
    _paused: bool
    _card_timeout: float
    _card_deadline: float
    _lock: threading.RLock
    _current_card: str
    _results: OrderedDict[str, CardResult]
    _pending: dict[str, threading.Event]
    stdin: deque[TerminalCard]
    stdout: deque[CardResult]
    _active_cards: int
    _loop_state: str
    _cards_processed: int
    _cards_since_pressure_check: int
    _watchdog_pet: Callable[[str], None] | None

    def _process_card(self, card: TerminalCard) -> CardResult:
        """Process a card (implemented by CardExecutionMixin)."""
        raise NotImplementedError

    def boot(self) -> dict:
        """Boot the agent terminal: constitution check → warm memory → start workers."""
        from l3.agent_terminal import TerminalStatus, run_cache_keepalive
        phases = []
        cc = self.constitution.is_allowed("boot", self.agent_id, target=self.role, territory=self.territory)
        phases.append({"phase": "constitution_check", **cc})
        if not cc.get("allowed", True):
            self.status = TerminalStatus.CRASHED
            self._boot_result = {"success": False, "error": "constitution blocked boot", "phases": phases}
            return self._boot_result
        try:
            from l3.memory.memory import get_memory
            get_memory().remember(agent_id=self.agent_id, cell_id=self.cell_id, entry_type="boot",
                content=f"boot: role={self.role} territory={self.territory}", tags=["boot"], ring=1)
            phases.append({"phase": "memory_warm", "success": True})
        except Exception as e:
            phases.append({"phase": "memory_warm", "success": False, "error": str(e)})
        try:
            from ..memory.context_pool import register as _register_cp
            _register_cp(agent_id=self.agent_id, cell_id=self.cell_id, max_tokens=SUBAGENT_MAX_TOKENS)
            phases.append({"phase": "context_pool_register", "success": True})
        except Exception as e:
            phases.append({"phase": "context_pool_register", "success": False, "error": str(e)})

        # ── Full manual loading on first boot ──
        try:
            from l1.kernel.skill import get_skill_manager
            sm = get_skill_manager()
            all_s = sm.list_skills(limit=20)
            if all_s:
                parts = ["=== Agent Manual (boot) ==="]
                for s in all_s:
                    n = getattr(s, 'name', '?')
                    d = getattr(s, 'description', '')[:LOG_TRUNC_120]
                    p = getattr(s, 'prompt', '')[:LOG_TRUNC_300]
                    parts.append(f"[{n}] {d}\n{p}")
                self.context.store(key=f"manual:{self.agent_id}", value="\n\n".join(parts),
                                   agent_id=self.agent_id, entry_type="manual")
                phases.append({"phase": "manual_loaded", "count": len(all_s)})
                logger.info("agent %s: loaded %d skills", self.agent_id, len(all_s))
        except Exception as e:
            phases.append({"phase": "manual_loaded", "error": str(e)})

        # ── Persistence session — load snapshot / init hooks ──
        try:
            from l3.agent.agent_persist import SnapshotHook, load_snapshot
            self._snapshot_hook = SnapshotHook(self.agent_id)
            snapshot = load_snapshot(self.agent_id)
            if snapshot:
                phases.append({"phase": "persist_restore", "status": snapshot.get("status")})
            else:
                phases.append({"phase": "persist_restore", "note": "no snapshot"})
            logger.info("agent %s: persist ready", self.agent_id)
        except Exception as e:
            self._snapshot_hook = None
            phases.append({"phase": "persist_init", "error": str(e)})

        emit_signal(EVENT_TASK_ASSIGN, sender=self.agent_id, target="cell",
                     data={"event": "agent_boot", "role": self.role, "ring": self.ring})
        self._running = True
        for i in range(self._max_workers):
            w = threading.Thread(target=self._worker, daemon=True, name=f"term-{self.agent_id}-w{i}")
            w.start()
            self._workers.append(w)
        self.status = TerminalStatus.IDLE
        self._boot_result = {"success": True, "phases": phases}

        kt = threading.Thread(target=run_cache_keepalive, args=(self,), daemon=True,
                              name=f"keepalive-{self.agent_id}")
        kt.start()
        return self._boot_result

    def _worker(self) -> None:
        from l3.agent_terminal import CardResult, TerminalStatus
        from l3.scheduler.scheduler_time import get_time_scheduler as _get_ts
        while self._running:
            if self._paused:
                time.sleep(POLL_INTERVAL_PAUSED)
                continue
            # Stuck card detection: if card_timeout is set and a card exceeded deadline,
            # mark it as failed and skip to next card
            if self._card_timeout > 0 and self._card_deadline > 0 and time.time() > self._card_deadline:
                with self._lock:
                    stuck_id = self._current_card
                    if stuck_id:
                        logger.warning("agent %s: card %s timed out (%.1fs), cancelling",
                                       self.agent_id, stuck_id, self._card_timeout)
                        self._results[stuck_id] = CardResult(
                            card_id=stuck_id, action="timeout",
                            success=False, error=f"card timed out after {self._card_timeout}s",
                        )
                        ev = self._pending.pop(stuck_id, None)
                        if ev:
                            ev.set()
                        self._current_card = ""
                        self._card_deadline = 0
            card = None
            with self._lock:
                if self.stdin:
                    card = self.stdin.popleft()
                    self._active_cards += 1
                    if self._card_timeout > 0:
                        self._card_deadline = time.time() + self._card_timeout
            if card is None:
                time.sleep(POLL_INTERVAL_FAST)
                continue
            with self._lock:
                self.status = TerminalStatus.PROCESSING if self._active_cards > 0 else TerminalStatus.IDLE
                self._current_card = card.card_id
                self._loop_state = f"processing {card.action} on {card.target[:LOG_TRUNC_40]}"
            from l3.error_bus import error_boundary
            result = None  # error_boundary consumes exceptions; keep it defined
            with error_boundary("worker card failed", component="services", agent_id=self.agent_id):
                result = self._process_card(card)
            if result is None:
                result = CardResult(card_id=card.card_id, action=card.action, success=False, error="unknown")
            with self._lock:
                from l1.kernel.params.agent import TERMINAL_STATE_DEFAULT
                self._loop_state = TERMINAL_STATE_DEFAULT
                self._current_card = ""
            result.elapsed = time.time() - card.timestamp
            try:
                tick_r = _get_ts().tick(self.agent_id, result.elapsed)
                if tick_r.get("status") in ("preempt", "timeout"):
                    logger.warning("agent %s preempted: %.1fs used (quantum=%.1f)",
                                   self.agent_id, tick_r.get("used", 0), tick_r.get("quantum", 0))
            except Exception as e:
                logger.warning("services/agent_terminal: %s", e)
            with self._lock:
                self._cards_processed += 1
                self._cards_since_pressure_check += 1
                self._active_cards -= 1
                self.stdout.append(result)
                self._results[card.card_id] = result
                # LRU eviction: keep newest results, discard oldest
                self._results.move_to_end(card.card_id)
                while len(self._results) > AGENT_TERMINAL_RESULTS_MAX:
                    self._results.popitem(last=False)
                # Periodic memory pressure check (every 10 cards, non-think actions)
                if self._cards_since_pressure_check >= 10 and card.action != "think":
                    self._cards_since_pressure_check = 0
                    try:
                        from ..memory.memory import get_memory
                        p = get_memory().pressure(self.agent_id)
                        if p.get("level") == "high":
                            get_memory().stub_compact(self.agent_id)
                            logger.info("periodic compact for %s: pressure=%s",
                                        self.agent_id, p.get("level"))
                    except Exception:
                        logger.debug("agent_terminal: memory pressure check failed")
                ev = self._pending.pop(card.card_id, None)
                if ev:
                    ev.set()
                if self._active_cards <= 0:
                    self.status = TerminalStatus.IDLE
                # Watchdog pet after each completed card
                if self._watchdog_pet:
                    try:
                        self._watchdog_pet(self.agent_id)
                    except Exception as e:
                        logger.warning("watchdog pet failed: %s", e)
        with self._lock:
            self._active_cards = 0
            self.status = TerminalStatus.IDLE
