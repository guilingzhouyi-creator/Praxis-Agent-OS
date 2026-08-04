"""Global service Component wrappers for SystemBus.

Wraps singletons (StatsCenter, RecordCenter, CentralController, etc.)
into the Component protocol so they join the unified lifecycle.
"""

from __future__ import annotations

import logging
import threading
import time

from l1.kernel.bus import Component, ComponentMeta, SystemBus
from l1.kernel.params.system import THREAD_JOIN_TIMEOUT

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# StatsCenterComponent
# ════════════════════════════════════════════════════════════════

class StatsCenterComponent(Component):
    """Wraps StatsCenter — cross-Cell metric aggregation.

    Listens to *.stats events from all components for auto-ingestion.
    """

    meta = ComponentMeta(name="stats_center", depends_on=[], tags=["global", "monitor"])

    def bus_init(self, bus: SystemBus) -> None:
        from l3.services.stats_center import get_center
        self._center = get_center()
        self._bus = bus
        self._thread: threading.Thread | None = None
        # Auto-ingest stats from all components on heartbeat
        bus.on("stats.heartbeat", lambda e: self._collect(bus))

    def bus_start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._heartbeat_loop, name="stats-heartbeat", daemon=True)
        self._thread.start()

    def bus_stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=THREAD_JOIN_TIMEOUT)

    def _collect(self, bus: SystemBus) -> None:
        """Collect stats from all child buses and ingest into StatsCenter."""
        try:
            all_stats = bus.stats()
            from l3.services.stats_center import MetricPoint
            for key, value in all_stats.items():
                if isinstance(value, (int, float)):
                    self._center.ingest(MetricPoint(
                        name=key, value=float(value),
                        tags={"source": "systembus"},
                        metric_type="gauge",
                    ))
        except Exception as e:
            logger.warning("stats_center collect: %s", e)

    def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                self._snapshot_all_pmus()
                if self._bus:
                    self._bus.emit("stats.heartbeat", {"ts": time.time()})
            except Exception as e:
                logger.warning("stats heartbeat: %s", e)
            time.sleep(60.0)

    @staticmethod
    def _snapshot_all_pmus() -> None:
        try:
            from l3.cell import get_cells
            for cell_id, cell in get_cells().items():
                pmu = getattr(cell, "pmu", None)
                if pmu:
                    pmu.snapshot()
        except Exception:
            pass

    def bus_health(self) -> dict:
        if not self._center:
            return {"status": "not_inited"}
        s = self._center.stats()
        return {"status": "ok", "metrics": s.get("active_metrics", 0)}

    @property
    def center(self):
        return self._center


# ════════════════════════════════════════════════════════════════
# RecordCenterComponent
# ════════════════════════════════════════════════════════════════

class RecordCenterComponent(Component):
    """Wraps RecordCenter — unified error/log/reference record store."""

    meta = ComponentMeta(name="record_center", depends_on=["stats_center"], tags=["global", "logging"])

    def bus_init(self, bus: SystemBus) -> None:
        from l3.services.record_center import get_record_center
        self._center = get_record_center()

    def bus_start(self) -> None:
        self._center.bridge_stats()

    def bus_health(self) -> dict:
        s = self._center.stats()
        return {"status": "ok", "errors": s.get("errors", {}).get("total", 0)}

    @property
    def center(self):
        return self._center


# ════════════════════════════════════════════════════════════════
# EventBusComponent
# ════════════════════════════════════════════════════════════════

class EventBusComponent(Component):
    """Wraps the kernel EventBus (pub/sub, Signal/SignalType).

    The EventBus itself remains the transport layer.
    This wrapper just plugs it into the SystemBus lifecycle.
    """

    meta = ComponentMeta(name="event_bus", depends_on=[], tags=["kernel", "transport"])

    def bus_init(self, bus: SystemBus) -> None:
        from l1.kernel import get_event_bus
        self._bus_impl = get_event_bus()

    def bus_health(self) -> dict:
        if not self._bus_impl:
            return {"status": "not_inited"}
        return {"status": "ok"}


# ════════════════════════════════════════════════════════════════
# CentralControllerComponent
# ════════════════════════════════════════════════════════════════

class CentralControllerComponent(Component):
    """Wraps CentralController — cross-Cell orchestration (L3A + L3B + HTN-A)."""

    meta = ComponentMeta(name="central_controller", depends_on=["event_bus"], tags=["global", "control"])

    def bus_init(self, bus: SystemBus) -> None:
        from l3.cell.peers.l3 import get_coordinator
        self._controller = get_coordinator()

    def bus_start(self) -> None:
        pass

    def bus_health(self) -> dict:
        return {"status": "ok"}

    @property
    def controller(self):
        return self._controller


# ════════════════════════════════════════════════════════════════
# L3BComponent + L3BBusComponent
# ════════════════════════════════════════════════════════════════

class L3BComponent(Component):
    """Wraps a single L3BComposite — bridges two adjacent Cells."""

    meta = ComponentMeta(name="l3b", depends_on=[], tags=["cross-cell", "routing"])

    def __init__(self, composite_id: str, prev_cell: str, next_cell: str):
        super().__init__()
        self.composite_id = composite_id
        self.prev_cell = prev_cell
        self.next_cell = next_cell
        self.meta.name = composite_id
        self._composite = None

    def bus_init(self, bus: SystemBus) -> None:
        from l3.bus.l3b import L3BComposite
        self._composite = L3BComposite(self.composite_id, self.prev_cell, self.next_cell)

    def bus_start(self) -> None:
        if self._composite:
            self._composite.boot()

    def bus_stop(self) -> None:
        if self._composite:
            self._composite.shutdown()

    def bus_health(self) -> dict:
        if not self._composite:
            return {"status": "not_inited"}
        return {"status": "ok", "active": self._composite.active}


class L3BBusComponent(Component):
    """Wraps L3BBus — inter-composite messaging transport."""

    meta = ComponentMeta(name="l3b_bus", depends_on=[], tags=["cross-cell", "transport"])

    def bus_init(self, bus: SystemBus) -> None:
        from l3.bus.l3b_bus import get_bus
        self._bus_impl = get_bus()

    def bus_health(self) -> dict:
        return {"status": "ok"}
