"""Kernel interrupt table — interrupt handling for ops_console."""
from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from .params.kernel import INTERRUPT_MAX_HISTORY, INTERRUPT_QUERY_LIMIT

logger = logging.getLogger(__name__)


class InterruptType(Enum):
    AGENT_CRASH = auto()
    RESOURCE_EXHAUSTION = auto()
    DEADLOCK_DETECTED = auto()
    OOM_KILL = auto()


@dataclass
class Interrupt:
    type: InterruptType
    agent_id: str = ""
    reason: str = ""
    data: dict = field(default_factory=dict)


class InterruptTable:
    """Kernel interrupt table — tracks, dispatches, and queries interrupts.

    Fixes: added recent() for registry.py compatibility.
    """

    def __init__(self):
        self._handlers: dict[InterruptType, list[Callable]] = {}
        self._counts: dict[str, int] = {}
        self._history: deque[dict] = deque(maxlen=INTERRUPT_MAX_HISTORY)
        self._lock = threading.RLock()

    def register(self, itype: InterruptType, handler: Callable) -> None:
        """Register a callback handler for the given interrupt type."""
        self._handlers.setdefault(itype, []).append(handler)

    def fire(self, itype: InterruptType, agent_id: str = "", reason: str = "",
             data: dict | None = None) -> None:
        """Dispatch an interrupt to all registered handlers and log it to history."""
        name = itype.name
        self._counts[name] = self._counts.get(name, 0) + 1
        intr = Interrupt(type=itype, agent_id=agent_id, reason=reason, data=data or {})
        self._history.append({
            "type": name, "agent": agent_id, "reason": reason,
            "data": data or {}, "seq": self._counts[name],
        })
        # deque(maxlen=INTERRUPT_MAX_HISTORY) prunes oldest entry automatically
        for cb in self._handlers.get(itype, []):
            try:
                cb(intr)
            except Exception as e:
                    logger.warning("kernel/interrupt: %s", e)

    def counts(self) -> dict[str, int]:
        """Return a copy of per-interrupt-type occurrence counts."""
        return dict(self._counts)

    def recent(self, limit: int = INTERRUPT_QUERY_LIMIT) -> list[dict]:
        """Return the most recent interrupt history entries up to limit."""
        with self._lock:
            entries = list(self._history)
        return entries[-limit:]


_table = InterruptTable()


def get_table() -> InterruptTable:
    """Return the process-wide singleton InterruptTable instance."""
    return _table


def register_handler(itype: InterruptType, handler: Callable) -> None:
    """Register a callback handler on the singleton interrupt table."""
    _table.register(itype, handler)


def fire(itype: InterruptType, agent_id: str = "", reason: str = "",
         data: dict | None = None) -> None:
    """Fire an interrupt through the singleton interrupt table."""
    _table.fire(itype, agent_id, reason, data)
