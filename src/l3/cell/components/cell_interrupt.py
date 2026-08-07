"""InterruptController — priority-based interrupt delivery for Cell.

Hardware-style interrupt controller with 4 priority levels:

  NMI (0)   — unmaskable: watchdog crash, constitution violation, cell restart
  HIGH (1)  — maskable:   cross-review response, task timeout, agent crash signal
  NORMAL (2)— maskable:   task assign, message delivery, review request
  LOW (3)   — maskable:   heartbeat, scout progress, cache stats, token usage

Architecture:
  - IRQ table: {irq_num → (handler, priority, name)}
  - Priority masking: lower-number = higher priority
  - NMI bypasses all masks and the pending queue
  - Non-NMI interrupts queue per-priority; dispatch highest-priority first
  - Wraps the existing EventBus — legacy emit() calls go through
    InterruptController which assigns default NORMAL priority

Integration:
  - Cell.__init__ creates InterruptController, registers IRQs
  - Watchdog on_crash → controller.trigger(NMI, "watchdog.crash")
  - AgentTerminal dispatch → controller.trigger(HIGH, "task.complete")
  - Cell.send_message → controller.trigger(NORMAL, "message.delivered")
  - Cache flush → controller.trigger(LOW, "cache.flush")
  - PMU tracks: interrupt.triggered.{priority}, interrupt.handled
  - Constitution violation → controller.trigger(NMI, "constitution.violation")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from l1.kernel.params.system import IRQ_DISPATCH_BATCH, IRQ_TABLE_SIZE

logger = logging.getLogger(__name__)


class IrqPriority(IntEnum):
    """IrqPriority — irq priority."""

    NMI = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class IrqSlot:
    """IrqSlot — irq slot record (irq_num, name, handler, priority, masked)."""

    irq_num: int = 0
    name: str = ""
    handler: Callable | None = None
    priority: IrqPriority = IrqPriority.NORMAL
    masked: bool = False
    triggered_count: int = 0
    handled_count: int = 0
    last_triggered: float = 0.0


@dataclass
class IrqEvent:
    """IrqEvent — irq event record (irq_num, name, priority, data, timestamp)."""

    irq_num: int = 0
    name: str = ""
    priority: IrqPriority = IrqPriority.NORMAL
    data: Any = None
    timestamp: float = 0.0


class InterruptController:
    """Priority-based interrupt delivery.

    Thread-safe.  NMI interrupts are delivered inline (not queued).
    Non-NMI interrupts are queued and dispatched FIFO within priority.
    """

    def __init__(self, cell_id: str, table_size: int = IRQ_TABLE_SIZE, pmu: Any = None):
        self.cell_id = cell_id
        self._table_size = table_size
        self._pmu = pmu
        self._lock = threading.RLock()

        # IRQ table: irq_num → IrqSlot
        self._table: dict[int, IrqSlot] = {}

        # Per-priority pending queues
        self._pending: dict[IrqPriority, list[IrqEvent]] = defaultdict(list)

        # Total lifetime counter
        self._total_triggered: int = 0
        self._total_handled: int = 0

        # Register built-in IRQs
        self._register_builtin()

    # ── IRQ registration ──────────────────────────────────────────

    def register(
        self, irq_num: int, name: str, handler: Callable | None = None, priority: IrqPriority = IrqPriority.NORMAL
    ) -> dict:
        """Register an interrupt handler.

        irq_num: 0-31.  Returns {"success": True} or error dict.
        """
        if irq_num < 0 or irq_num >= self._table_size:
            return {"success": False, "error": f"irq_num {irq_num} out of range [0, {self._table_size})"}
        with self._lock:
            if irq_num in self._table:
                return {"success": False, "error": f"irq {irq_num} already registered: {self._table[irq_num].name}"}
            self._table[irq_num] = IrqSlot(
                irq_num=irq_num,
                name=name,
                handler=handler,
                priority=priority,
            )
            logger.debug("interrupt: registered IRQ%d %s (priority=%s)", irq_num, name, priority.name)
            return {"success": True, "irq_num": irq_num, "name": name}

    def unregister(self, irq_num: int) -> dict:
        """Unregister the interrupt slot for irq_num.

        Returns success/error dict.
        """
        with self._lock:
            if irq_num not in self._table:
                return {"success": False, "error": f"irq {irq_num} not registered"}
            self._table.pop(irq_num)
            return {"success": True}

    # ── Interrupt trigger ─────────────────────────────────────────

    def trigger(self, irq_num: int | str, data: Any = None) -> dict:
        """Trigger an interrupt by irq_num or by name.

        NMI interrupts fire the handler immediately (inline).
        Non-NMI interrupts are queued by priority.
        """
        with self._lock:
            slot = self._resolve_slot(irq_num)
            if slot is None:
                return {"success": False, "error": f"unknown irq: {irq_num}"}

            slot.triggered_count += 1
            slot.last_triggered = time.time()
            self._total_triggered += 1
            if self._pmu:
                self._pmu.increment(f"interrupt.triggered.{slot.priority.name.lower()}")

            event = IrqEvent(
                irq_num=slot.irq_num,
                name=slot.name,
                priority=slot.priority,
                data=data,
                timestamp=time.time(),
            )

            # NMI fires immediately (inline, cannot be masked)
            if slot.priority == IrqPriority.NMI:
                self._dispatch_nmi(slot, event)
                return {"success": True, "delivery": "nmi"}

            # Masked interrupts are dropped
            if slot.masked:
                logger.debug("interrupt: IRQ%d %s masked — dropped", slot.irq_num, slot.name)
                return {"success": False, "error": "masked"}

            # Queue for dispatch
            self._pending[slot.priority].append(event)
            return {"success": True, "delivery": "queued"}

    def dispatch_pending(self, max_total: int = IRQ_DISPATCH_BATCH) -> int:
        """Dispatch pending interrupts, highest priority first.

        Args:
            max_total: Global cap on total events dispatched across all
                       priority levels (not per-priority).

        Returns number of events dispatched.
        """
        dispatched = 0
        for priority in sorted(IrqPriority):
            if priority == IrqPriority.NMI:
                continue  # NMI is never queued
            queue = self._pending.get(priority, [])
            while queue and dispatched < max_total:
                event = queue.pop(0)
                with self._lock:
                    slot = self._table.get(event.irq_num)
                    if slot is None or slot.masked:
                        continue
                self._dispatch_safe(slot, event)
                dispatched += 1
                if self._pmu:
                    self._pmu.increment(f"interrupt.handled.{priority.name.lower()}")
        return dispatched

    # ── Masking ───────────────────────────────────────────────────

    def mask(self, irq_num: int | str) -> dict:
        """Mask an interrupt so its non-NMI events are dropped.

        Returns success/error dict.
        """
        with self._lock:
            slot = self._resolve_slot(irq_num)
            if slot is None:
                return {"success": False, "error": f"unknown irq: {irq_num}"}
            if slot.priority == IrqPriority.NMI:
                return {"success": False, "error": "cannot mask NMI"}
            slot.masked = True
            return {"success": True}

    def unmask(self, irq_num: int | str) -> dict:
        """Unmask the given interrupt so events are queued again.

        Returns success/error dict.
        """
        with self._lock:
            slot = self._resolve_slot(irq_num)
            if slot is None:
                return {"success": False, "error": f"unknown irq: {irq_num}"}
            slot.masked = False
            return {"success": True}

    def set_handler(self, irq_num: int | str, handler: Callable) -> dict:
        """Replace the handler for the given interrupt.

        Returns success/error dict.
        """
        with self._lock:
            slot = self._resolve_slot(irq_num)
            if slot is None:
                return {"success": False, "error": f"unknown irq: {irq_num}"}
            slot.handler = handler
            return {"success": True}

    # ── Stats ─────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return interrupt controller statistics as a dict."""
        with self._lock:
            return {
                "cell_id": self.cell_id,
                "total_triggered": self._total_triggered,
                "total_handled": self._total_handled,
                "registered_irqs": len(self._table),
                "pending_by_priority": {p.name.lower(): len(q) for p, q in self._pending.items()},
                "irqs": {
                    f"IRQ{n}": {
                        "name": s.name,
                        "priority": s.priority.name,
                        "masked": s.masked,
                        "triggered": s.triggered_count,
                        "handled": s.handled_count,
                    }
                    for n, s in sorted(self._table.items())
                },
            }

    # ── Internal ──────────────────────────────────────────────────

    def _resolve_slot(self, irq_num: int | str) -> IrqSlot | None:
        if isinstance(irq_num, int):
            return self._table.get(irq_num)
        for s in self._table.values():
            if s.name == irq_num:
                return s
        return None

    def _dispatch_nmi(self, slot: IrqSlot, event: IrqEvent) -> None:
        """Dispatch an NMI interrupt — inline, no queue, no mask check."""
        slot.handled_count += 1
        self._total_handled += 1
        if slot.handler:
            try:
                slot.handler(event)
            except Exception as e:
                logger.error("interrupt: NMI handler IRQ%d %s failed: %s", slot.irq_num, slot.name, e)

    def _dispatch_safe(self, slot: IrqSlot, event: IrqEvent) -> None:
        """Dispatch a queued interrupt safely."""
        slot.handled_count += 1
        self._total_handled += 1
        if slot.handler:
            try:
                slot.handler(event)
            except Exception as e:
                logger.warning("interrupt: handler IRQ%d %s failed: %s", slot.irq_num, slot.name, e)

    def _register_builtin(self) -> None:
        """Register built-in IRQ slots with default NMI priority for critical events."""
        builtin = [
            (0, "watchdog.crash", IrqPriority.NMI),
            (1, "constitution.violation", IrqPriority.NMI),
            (2, "cell.restart", IrqPriority.NMI),
            (3, "security.breach", IrqPriority.NMI),
            (4, "task.complete", IrqPriority.HIGH),
            (5, "review.response", IrqPriority.HIGH),
            (6, "task.timeout", IrqPriority.HIGH),
            (7, "agent.crash", IrqPriority.HIGH),
            (8, "task.assign", IrqPriority.NORMAL),
            (9, "message.delivered", IrqPriority.NORMAL),
            (10, "review.request", IrqPriority.NORMAL),
            (11, "scout.done", IrqPriority.NORMAL),
            (12, "heartbeat", IrqPriority.LOW),
            (13, "scout.progress", IrqPriority.LOW),
            (14, "cache.flush", IrqPriority.LOW),
            (15, "token.usage", IrqPriority.LOW),
            (16, "cell.rollback", IrqPriority.NORMAL),
        ]
        for irq_num, name, priority in builtin:
            self._table[irq_num] = IrqSlot(
                irq_num=irq_num,
                name=name,
                priority=priority,
            )
