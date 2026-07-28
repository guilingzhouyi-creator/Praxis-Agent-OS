"""CellTokenMerger — per-Cell token accumulator, bridges ContextPool to CentralCollector and MonitorBus.

Each Cell runs one merger that polls ContextPool periodically and emits
token usage events to the monitoring pipeline.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class CellTokenMerger:
    """Cell-level token accumulator.  Polls ContextPool and emits TOKEN_USAGE."""

    def __init__(self, cell_id: str, interval: float = 60.0):
        self.cell_id = cell_id
        self._interval = interval
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"merger-{self.cell_id}")
        self._thread.start()
        logger.info("CellTokenMerger started for %s (interval=%.0fs)", self.cell_id, self._interval)

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._interval)
            try:
                self._emit()
            except Exception as e:
                logger.warning("CellTokenMerger %s: %s", self.cell_id, e)

    def _emit(self) -> None:
        from l3.memory.context_pool import cell_total
        data = cell_total(self.cell_id)
        total = data.get("total_tokens", 0)

        # → CentralCollector via EventBus
        try:
            from l1.kernel import emit_signal
            from l1.kernel.params.agent import EVENT_TOKEN_USAGE
            emit_signal(EVENT_TOKEN_USAGE, sender="cell_token_merger", target="central_collector",
                        data={"cell_id": self.cell_id, "input_tokens": total,
                              "agent_count": len(data.get("per_agent", {}))})
        except Exception:
            pass

        # → MonitorBus
        try:
            from l3.bus.monitor_bus import MonitorEvent, get_bus
            get_bus().emit(MonitorEvent(
                type="token.cell.usage", source="cell_token_merger",
                severity="info", cell_id=self.cell_id,
                data={"token_total": total, "per_agent": data.get("per_agent", {})},
            ))
        except Exception:
            pass
