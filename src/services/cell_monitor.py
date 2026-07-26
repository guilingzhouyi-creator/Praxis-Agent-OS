"""CellMonitor — centralized Cell health monitoring with ring buffer event log.

One of the six centers of Praxis Agent OS:
  CentralController · CentralScheduler · ObservabilityBus · R4Agent · CellMonitor · L3B

CellMonitor tracks:
  - Cell registration / status changes
  - Agent-level health (boot, crash, card_done, card_fail)
  - A rolling ring buffer of the latest events for L3A queries and human visualization
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default ring size — keeps the last 1000 events across all Cells
_DEFAULT_RING_SIZE = 1000


@dataclass
class CellSnapshot:
    """Point-in-time snapshot of a Cell's status."""
    cell_id: str
    territory: list[str] = field(default_factory=list)
    agents: dict[str, str] = field(default_factory=dict)       # agent_id → role
    agent_status: dict[str, str] = field(default_factory=dict)  # agent_id → status
    agent_cards: dict[str, int] = field(default_factory=dict)   # agent_id → card count
    cell_healthy: bool = True
    last_seen: float = 0.0
    created_at: float = field(default_factory=time.time)


@dataclass
class CellEvent:
    """A single event recorded in the CellMonitor ring buffer."""
    cell_id: str
    event: str          # registered | boot | crash | health_change | card_done | card_fail
    agent_id: str = ""
    message: str = ""
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class CellMonitor:
    """Centralized Cell monitoring — ring buffer + snapshot tracking."""

    def __init__(self, ring_size: int = _DEFAULT_RING_SIZE):
        self._snapshots: dict[str, CellSnapshot] = {}
        self._ring: deque[CellEvent] = deque(maxlen=ring_size)
        self._lock = threading.RLock()
        self._event_count = 0

    # ── Cell lifecycle ──

    def register_cell(self, cell_id: str, territory: list[str] | None = None,
                      agents: dict[str, str] | None = None) -> dict:
        with self._lock:
            self._snapshots[cell_id] = CellSnapshot(
                cell_id=cell_id, territory=territory or [],
                agents=agents or {},
            )
        self._push_event(cell_id, "registered", data={"territory": territory, "agents": agents})
        logger.info("cellmonitor: %s registered (%d agents)", cell_id, len(agents or {}))
        return {"success": True}

    def unregister_cell(self, cell_id: str) -> dict:
        with self._lock:
            self._snapshots.pop(cell_id, None)
        self._push_event(cell_id, "unregistered")
        return {"success": True}

    # ── Agent status ──

    def report_agent(self, cell_id: str, agent_id: str, role: str = "",
                     status: str = "", cards: int = 0) -> dict:
        with self._lock:
            snap = self._snapshots.get(cell_id)
            if not snap:
                return {"success": False, "error": f"unknown cell: {cell_id}"}
            if role:
                snap.agents[agent_id] = role
            if status:
                snap.agent_status[agent_id] = status
            if cards:
                snap.agent_cards[agent_id] = cards
            snap.last_seen = time.time()
        return {"success": True}

    def report_agent_crash(self, cell_id: str, agent_id: str,
                           reason: str = "") -> dict:
        self._push_event(cell_id, "crash", agent_id=agent_id, message=reason)
        with self._lock:
            snap = self._snapshots.get(cell_id)
            if snap:
                from kernel.params.agent import AGENT_STATUS_CRASHED
                snap.agent_status[agent_id] = AGENT_STATUS_CRASHED
                snap.cell_healthy = False
        return {"success": True}

    def report_card_result(self, cell_id: str, agent_id: str,
                           card_id: str, success: bool) -> dict:
        event = "card_done" if success else "card_fail"
        self._push_event(cell_id, event, agent_id=agent_id,
                         data={"card_id": card_id, "success": success})
        with self._lock:
            snap = self._snapshots.get(cell_id)
            if snap:
                snap.agent_cards[agent_id] = snap.agent_cards.get(agent_id, 0) + 1
                if not success:
                    snap.cell_healthy = False
        return {"success": True}

    # ── Query API ──

    def list_cells(self) -> list[dict]:
        with self._lock:
            return [
                {"cell_id": s.cell_id, "territory": s.territory,
                 "agent_count": len(s.agents), "healthy": s.cell_healthy,
                 "last_seen": s.last_seen}
                for s in self._snapshots.values()
            ]

    def get_cell(self, cell_id: str) -> dict | None:
        with self._lock:
            s = self._snapshots.get(cell_id)
            if not s:
                return None
            return {
                "cell_id": s.cell_id, "territory": s.territory,
                "agents": {aid: {"role": r, "status": s.agent_status.get(aid, "unknown"),
                                  "cards": s.agent_cards.get(aid, 0)}
                            for aid, r in s.agents.items()},
                "healthy": s.cell_healthy, "last_seen": s.last_seen,
                "created_at": s.created_at,
            }

    def get_events(self, cell_id: str = "", since: float = 0.0,
                   limit: int = 50) -> list[dict]:
        with self._lock:
            results = []
            for e in reversed(self._ring):
                if cell_id and e.cell_id != cell_id:
                    continue
                if since and e.timestamp < since:
                    continue
                results.append({
                    "timestamp": e.timestamp, "cell_id": e.cell_id,
                    "event": e.event, "agent_id": e.agent_id,
                    "message": e.message, "data": e.data,
                })
                if len(results) >= limit:
                    break
            return results

    def stats(self) -> dict:
        with self._lock:
            return {
                "cells": len(self._snapshots),
                "events_total": self._event_count,
                "events_buffered": len(self._ring),
            }

    # ── Internal ──

    def _push_event(self, cell_id: str, event: str, agent_id: str = "",
                    message: str = "", data: dict | None = None) -> None:
        with self._lock:
            self._ring.append(CellEvent(
                cell_id=cell_id, event=event, agent_id=agent_id,
                message=message, data=data or {},
            ))
            self._event_count += 1
        # Also emit to MonitorBus
        try:
            from .monitor_bus import MonitorEvent, get_bus as _mb
            severity_map = {"crash": "crit", "card_fail": "warn", "card_done": "info", "registered": "info"}
            _mb().emit(MonitorEvent(
                type="service.cell." + event, source="cell_monitor",
                severity=severity_map.get(event, "info"),
                agent_id=agent_id, cell_id=cell_id,
                message=message or event, data=data or {},
            ))
        except Exception:
            pass


_cell_monitor: CellMonitor | None = None


def get_cell_monitor() -> CellMonitor:
    global _cell_monitor
    if _cell_monitor is None:
        _cell_monitor = CellMonitor()
    return _cell_monitor


def reset_cell_monitor() -> None:
    global _cell_monitor
    _cell_monitor = None
