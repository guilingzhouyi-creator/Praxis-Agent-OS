"""CentralCollector — cross-Cell token usage bus + aggregation.

Receives TOKEN_USAGE events from all Cells/Agents and aggregates them
into per-Cell, per-Agent, and global summaries, exposed via API.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from kernel import get_event_bus, SignalType
from kernel.params.system import TOKEN_CELL_QUOTA, TOKEN_GLOBAL_QUOTA

logger = logging.getLogger(__name__)


class CentralCollector:
    """Token usage collector — event-driven aggregation across all Cells.

    Subscribe to SignalType.TOKEN_USAGE on the event bus.
    Each event: {"agent_id", "cell_id", "input_tokens", "output_tokens", "provider", "model"}
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Per-Cell accumulators
        self._cells: dict[str, dict] = {}
        # Global histogram: 5min windows, last 24h
        self._history: list[dict] = []
        self._max_history = 288  # 288 × 5min = 24h
        self._started_at = time.time()

    def start(self) -> None:
        """Subscribe to the event bus."""
        bus = get_event_bus()
        bus.on(SignalType.TOKEN_USAGE, self._on_token_usage)
        logger.info("CentralCollector started")

    def stop(self) -> None:
        bus = get_event_bus()
        bus.off(SignalType.TOKEN_USAGE, self._on_token_usage)

    def _on_token_usage(self, signal: Any) -> None:
        """Event handler — aggregate token data."""
        data = signal.data or {}
        agent_id = data.get("agent_id", "unknown")
        cell_id = data.get("cell_id", "default")
        inp = data.get("input_tokens", 0)
        out = data.get("output_tokens", 0)
        provider = data.get("provider", "")
        model = data.get("model", "")

        with self._lock:
            # Per-Cell
            cell = self._cells.setdefault(cell_id, {
                "cell_id": cell_id, "agents": {},
                "total_input": 0, "total_output": 0, "total_calls": 0,
            })
            cell["total_input"] += inp
            cell["total_output"] += out
            cell["total_calls"] += 1

            agent = cell["agents"].setdefault(agent_id, {
                "agent_id": agent_id, "input": 0, "output": 0, "calls": 0,
            })
            agent["input"] += inp
            agent["output"] += out
            agent["calls"] += 1

            # Rolling history (5min window)
            window = int(time.time() // 300) * 300
            if self._history and self._history[-1]["window"] == window:
                self._history[-1]["input"] += inp
                self._history[-1]["output"] += out
                self._history[-1]["calls"] += 1
            else:
                if len(self._history) >= self._max_history:
                    self._history.pop(0)
                self._history.append({
                    "window": window, "input": inp, "output": out, "calls": 1,
                })

    def cell_summary(self) -> list[dict]:
        """Return per-Cell aggregated token usage."""
        with self._lock:
            return [
                {
                    "cell_id": cid,
                    "total_input": c["total_input"],
                    "total_output": c["total_output"],
                    "total_tokens": c["total_input"] + c["total_output"],
                    "total_calls": c["total_calls"],
                    "agents": list(c["agents"].values()),
                    "quota": TOKEN_CELL_QUOTA,
                    "usage_pct": round(
                        (c["total_input"] + c["total_output"]) / max(TOKEN_CELL_QUOTA, 1) * 100, 1
                    ),
                }
                for cid, c in self._cells.items()
            ]

    def global_summary(self) -> dict:
        """Return global token summary."""
        cells = self.cell_summary()
        total = sum(c["total_input"] + c["total_output"] for c in cells)
        return {
            "total_tokens": total,
            "total_input": sum(c["total_input"] for c in cells),
            "total_output": sum(c["total_output"] for c in cells),
            "total_calls": sum(c["total_calls"] for c in cells),
            "cells": len(cells),
            "quota": TOKEN_GLOBAL_QUOTA,
            "usage_pct": round(total / max(TOKEN_GLOBAL_QUOTA, 1) * 100, 1),
            "history": self._history[-48:],  # last 4h
            "uptime": round(time.time() - self._started_at),
        }

    def agent_detail(self, cell_id: str, agent_id: str) -> dict:
        """Return single agent's token usage."""
        with self._lock:
            cell = self._cells.get(cell_id)
            if not cell:
                return {"error": f"cell {cell_id} not found"}
            agent = cell["agents"].get(agent_id)
            if not agent:
                return {"error": f"agent {agent_id} not found in cell {cell_id}"}
            return {**agent, "cell_id": cell_id}


_collector: CentralCollector | None = None


def get_collector() -> CentralCollector:
    global _collector
    if _collector is None:
        _collector = CentralCollector()
    return _collector


def start_collector() -> None:
    get_collector().start()


def stop_collector() -> None:
    if _collector:
        _collector.stop()
