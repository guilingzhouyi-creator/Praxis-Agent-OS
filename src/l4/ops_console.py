"""Ops Console — central monitoring for all Cells, Agents, Scouts, and system health.

Provides:
  - Unified view of all Cells and their Peer Agents
  - Agent health monitoring (heartbeat, crash, deadlock detection)
  - Scout pool integrity checks
  - Centralized agent output collection
  - Structured alert system
  - /ops VFS mount for querying from shell

Usage:
  from l4.ops_console import get_ops
  ops = get_ops()
  ops.register_cell("cell-1", {"agent_a": "reader", "agent_b": "writer"})
  status = ops.summary()
  alerts = ops.recent_alerts()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.interrupt import InterruptType, register_handler
from l1.kernel.interrupt import get_table as get_int_table
from l1.kernel.params.agent import AGENT_STATUS_CRASHED, SIGNAL_TARGET_L3
from l1.kernel.params.system import (
    AGENT_UNRESPONSIVE_TIMEOUT,
    INTERRUPT_HIGH_COUNT,
    OPS_CONSOLE_POOL_WARN_RATIO,
    OPS_MAX_ALERTS,
    SCOUT_POOL_MAX_TOTAL,
)

logger = logging.getLogger(__name__)


class AlertLevel:
    """AlertLevel — alert level."""
    INFO = "info"
    WARN = "warn"
    CRIT = "crit"


@dataclass
class Alert:
    """Alert — alert record (level, source, message, timestamp, data)."""
    level: str
    source: str
    message: str
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)


@dataclass
class CellStatus:
    """CellStatus — cell status record (cell_id, agents, agent_status, agent_uptime, agent_cards)."""
    cell_id: str
    agents: dict[str, str] = field(default_factory=dict)  # agent_id → role
    agent_status: dict[str, str] = field(default_factory=dict)  # agent_id → status
    agent_uptime: dict[str, float] = field(default_factory=dict)
    agent_cards: dict[str, int] = field(default_factory=dict)
    last_seen: float = 0.0
    healthy: bool = True


class OpsConsole:
    """Central operations monitoring for the entire Agent OS."""

    def __init__(self):
        self._cells: dict[str, CellStatus] = {}
        self._alerts: list[Alert] = []
        self._max_alerts = OPS_MAX_ALERTS
        self._lock = threading.RLock()
        self._running = False
        self._monitor_thread: threading.Thread | None = None

        # Register kernel interrupt handlers for ops monitoring
        register_handler(InterruptType.AGENT_CRASH, self._on_agent_crash)
        register_handler(InterruptType.DEADLOCK_DETECTED, self._on_deadlock)
        register_handler(InterruptType.OOM_KILL, self._on_oom)

    def start(self, interval: float = 15.0) -> dict:
        """Start background health monitor."""
        self._running = True
        self._monitor_event = threading.Event()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, args=(interval,), daemon=True
        )
        self._monitor_thread.start()
        return {"success": True}

    def stop(self) -> None:
        """Stop the background health monitor."""
        self._running = False
        if hasattr(self, '_monitor_event'):
            self._monitor_event.set()

    # ── Cell registration ──

    def register_cell(self, cell_id: str, agents: dict[str, str]) -> None:
        """Register a Cell with its agent roster."""
        with self._lock:
            if cell_id not in self._cells:
                self._cells[cell_id] = CellStatus(cell_id=cell_id, agents=agents)
            else:
                self._cells[cell_id].agents.update(agents)

    def unregister_cell(self, cell_id: str) -> None:
        """Remove a cell from the monitoring registry."""
        with self._lock:
            self._cells.pop(cell_id, None)

    # ── Agent status updates ──

    def report_agent_status(self, cell_id: str, agent_id: str,
                            status: str, cards: int = 0,
                            uptime: float = 0.0) -> None:
        """Record the latest status, card count, and uptime for an agent."""
        with self._lock:
            cell = self._cells.get(cell_id)
            if not cell:
                return
            cell.agent_status[agent_id] = status
            cell.agent_cards[agent_id] = cards
            cell.agent_uptime[agent_id] = uptime
            cell.last_seen = time.time()

    def report_agent_crash(self, cell_id: str, agent_id: str,
                           reason: str = "") -> None:
        """Mark an agent as crashed, flag the cell unhealthy, and raise a critical alert."""
        with self._lock:
            cell = self._cells.get(cell_id)
            if cell:
                cell.agent_status[agent_id] = AGENT_STATUS_CRASHED
                cell.healthy = False
        self._alert(AlertLevel.CRIT, f"cell/{cell_id}",
                     f"Agent {agent_id} crashed: {reason}",
                     {"agent_id": agent_id, "cell_id": cell_id})

    # ── Interrupt handlers ──

    def _on_agent_crash(self, intr) -> None:
        self._alert(AlertLevel.CRIT, "kernel/interrupt",
                     f"Agent crash: {intr.agent_id} — {intr.reason}",
                     {"agent_id": intr.agent_id, "reason": intr.reason})

    def _on_deadlock(self, intr) -> None:
        self._alert(AlertLevel.CRIT, "kernel/interrupt",
                     f"Deadlock detected — {intr.reason}",
                     {"reason": intr.reason})

    def _on_oom(self, intr) -> None:
        self._alert(AlertLevel.WARN, "kernel/allocator",
                     f"OOM kill: {intr.agent_id} — {intr.reason}",
                     {"agent_id": intr.agent_id, "reason": intr.reason})

    # ── Background health monitor ──

    def _monitor_loop(self, interval: float) -> None:
        while self._running:
            # Wait for interval or wakeup signal (from stop())
            self._monitor_event.wait(timeout=interval)
            self._monitor_event.clear()
            if not self._running:
                break
            try:
                self._health_check()
            except Exception as e:
                logger.warning("ops health check error: %s", e)

    def _health_check(self) -> None:
        """Check all Cells, agents, and system health."""
        now = time.time()

        with self._lock:
            for cell_id, cell in list(self._cells.items()):
                # Check agent heartbeats — use individual agent uptime, not cell.last_seen
                for aid, uptime in list(cell.agent_uptime.items()):
                    if uptime > 0 and now - uptime > AGENT_UNRESPONSIVE_TIMEOUT:
                        if cell.agent_status.get(aid) != AGENT_STATUS_CRASHED:
                            cell.agent_status[aid] = "UNRESPONSIVE"
                            self._alert(AlertLevel.WARN, f"cell/{cell_id}",
                                         f"Agent {aid} unresponsive for 60s",
                                         {"agent_id": aid, "cell_id": cell_id})

        # Check scout pool
        try:
            from .agent.scout import get_pool
            pool = get_pool()
            ps = pool.stats()
            if ps.get("active", 0) >= ps.get("max_total", SCOUT_POOL_MAX_TOTAL) * OPS_CONSOLE_POOL_WARN_RATIO:
                self._alert(AlertLevel.WARN, "scout/pool",
                             f"Scout pool near capacity: {ps['active']}/{ps['max_total']}",
                             ps)
        except Exception as e:
            logger.warning("services/ops_console: %s", e)

        # Check interrupt counts for recent anomalies
        try:
            it = get_int_table()
            counts = it.counts()
            for iname, count in counts.items():
                if count > INTERRUPT_HIGH_COUNT:
                    self._alert(AlertLevel.WARN, "kernel/interrupt",
                                 f"High interrupt count: {iname} = {count}",
                                 {"type": iname, "count": count})
        except Exception as e:
            logger.warning("services/ops_console: %s", e)

    # ── Alert system ──

    def _alert(self, level: str, source: str, message: str,
               data: dict | None = None) -> None:
        alert = Alert(level=level, source=source, message=message, data=data or {})
        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) > self._max_alerts:
                self._alerts = self._alerts[-self._max_alerts:]
        emit_signal(EVENT_TASK_ASSIGN, sender="ops", target=SIGNAL_TARGET_L3,
                     data={"alert": level, "source": source, "message": message})

    def recent_alerts(self, level: str = "", limit: int = 20) -> list[dict]:
        """Return the most recent alerts, optionally filtered by level."""
        with self._lock:
            result = [{"level": a.level, "source": a.source,
                        "message": a.message, "timestamp": a.timestamp}
                       for a in self._alerts[-limit:]]
            if level:
                result = [a for a in result if a["level"] == level]
            return result[-limit:]

    # ── Status queries ──

    def summary(self) -> dict:
        """Full system summary."""
        with self._lock:
            cells_info = {}
            for cid, cell in self._cells.items():
                cells_info[cid] = {
                    "agents": {aid: {
                        "role": cell.agents.get(aid, ""),
                        "status": cell.agent_status.get(aid, "unknown"),
                        "cards": cell.agent_cards.get(aid, 0),
                        "uptime": round(cell.agent_uptime.get(aid, 0), 1),
                    } for aid in cell.agents},
                    "healthy": cell.healthy,
                    "last_seen": round(time.time() - cell.last_seen, 1) if cell.last_seen else 0,
                }
            return {
                "cells": cells_info,
                "alerts": {
                    "total": len(self._alerts),
                    "crit": sum(1 for a in self._alerts if a.level == AlertLevel.CRIT),
                    "warn": sum(1 for a in self._alerts if a.level == AlertLevel.WARN),
                },
                "cell_count": len(self._cells),
            }

    def cell_summary(self, cell_id: str) -> dict | None:
        """Return the monitoring summary for one cell, or None if unknown."""
        with self._lock:
            cell = self._cells.get(cell_id)
            if not cell:
                return None
            return {
                "cell_id": cell_id,
                "agents": cell.agents,
                "statuses": dict(cell.agent_status),
                "cards": dict(cell.agent_cards),
                "healthy": cell.healthy,
                "last_seen": round(time.time() - cell.last_seen, 1) if cell.last_seen else 0,
            }

    def health(self) -> dict:
        """Quick health check — all cells healthy?"""
        with self._lock:
            all_healthy = all(c.healthy for c in self._cells.values())
            return {
                "healthy": all_healthy,
                "cells": len(self._cells),
                "agents": sum(len(c.agents) for c in self._cells.values()),
                "alerts": len(self._alerts),
            }


_ops: OpsConsole | None = None
_ops_lock = threading.Lock()


def get_ops() -> OpsConsole:
    """Return the process-wide OpsConsole singleton."""
    global _ops
    if _ops is None:
        with _ops_lock:
            if _ops is None:
                _ops = OpsConsole()
    return _ops


def reset_ops() -> None:
    """Stop and clear the OpsConsole singleton."""
    global _ops
    if _ops:
        _ops.stop()
    _ops = None
