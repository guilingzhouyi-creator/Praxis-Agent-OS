"""Kernel interrupt table — interrupt handling for ops_console."""
from __future__ import annotations
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Callable

import logging

from .params import INTERRUPT_MAX_HISTORY, INTERRUPT_QUERY_LIMIT

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
        self._history: list[dict] = []
        self._max_history = INTERRUPT_MAX_HISTORY

    def register(self, itype: InterruptType, handler: Callable) -> None:
        self._handlers.setdefault(itype, []).append(handler)

    def fire(self, itype: InterruptType, agent_id: str = "", reason: str = "",
             data: dict | None = None) -> None:
        name = itype.name
        self._counts[name] = self._counts.get(name, 0) + 1
        intr = Interrupt(type=itype, agent_id=agent_id, reason=reason, data=data or {})
        self._history.append({
            "type": name, "agent": agent_id, "reason": reason,
            "data": data or {}, "seq": self._counts[name],
        })
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        for cb in self._handlers.get(itype, []):
            try:
                cb(intr)
            except Exception as e:
                    logger.warning("kernel/interrupt: %s", e)

    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def recent(self, limit: int = INTERRUPT_QUERY_LIMIT) -> list[dict]:
        return list(self._history[-limit:])


_table = InterruptTable()


def get_table() -> InterruptTable:
    return _table


def register_handler(itype: InterruptType, handler: Callable) -> None:
    _table.register(itype, handler)


def fire(itype: InterruptType, agent_id: str = "", reason: str = "",
         data: dict | None = None) -> None:
    _table.fire(itype, agent_id, reason, data)