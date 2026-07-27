"""Cell-level Component wrappers for SystemBus.

Each wrapper adapts an existing Praxis component to the Component protocol:
  - Declares meta (name, depends_on, tags)
  - Bridges bus_init/bus_start/bus_stop to the wrapped class
  - Converts direct callbacks to bus.emit() events
  - Provides bus_health()/bus_stats() from the wrapped stats()
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.bus import Component, ComponentMeta, SystemBus

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# CellPmuComponent
# ════════════════════════════════════════════════════════════════

class CellPmuComponent(Component):
    """Wraps CellPmu — 28 hardware-style performance counters per Cell."""

    meta = ComponentMeta(name="pmu", tags=["cell", "monitor"])

    def __init__(self, cell_id: str, **pmu_kwargs: Any):
        super().__init__()
        self.cell_id = cell_id
        self._pmu_kwargs = pmu_kwargs
        self._pmu = None

    def bus_init(self, bus: SystemBus) -> None:
        from .cell_pmu import CellPmu
        self._pmu = CellPmu(self.cell_id, **self._pmu_kwargs)
        self._bus = bus

    def increment(self, name: str, delta: int = 1) -> None:
        if self._pmu:
            self._pmu.increment(name, delta)

    def snapshot(self, force: bool = False):
        from .stats_center import get_center
        snap = self._pmu.snapshot(force=force)
        if snap:
            try:
                get_center().ingest_pmu_snapshot(self.cell_id, snap.counters, snap.timestamp)
            except Exception:
                pass
            self._bus.emit("pmu.snapshot", {"cell_id": self.cell_id, "counters": snap.counters})
        return snap

    def bus_health(self) -> dict:
        if not self._pmu:
            return {"status": "not_inited"}
        return {"status": "ok", "uptime": self._pmu.stats().get("uptime", 0)}

    def bus_stats(self) -> dict:
        if not self._pmu:
            return {}
        return self._pmu.stats().get("counters", {})

    @property
    def pmu(self):
        return self._pmu


# ════════════════════════════════════════════════════════════════
# CellWatchdogComponent
# ════════════════════════════════════════════════════════════════

class CellWatchdogComponent(Component):
    """Wraps CellWatchdog — per-agent liveness monitor.

    Converts callbacks to bus events:
      watchdog.timeout → bus.emit("watchdog.timeout", {agent_id, state})
      watchdog.crash   → bus.emit("watchdog.crash", {agent_id})
      watchdog.recovery → bus.emit("watchdog.recovery", {agent_id})
    """

    meta = ComponentMeta(name="watchdog", depends_on=["pmu"], tags=["cell", "monitor"])

    def __init__(self, cell_id: str, **wd_kwargs: Any):
        super().__init__()
        self.cell_id = cell_id
        self._wd_kwargs = wd_kwargs
        self._watchdog = None

    def bus_init(self, bus: SystemBus) -> None:
        from .cell_watchdog import CellWatchdog
        pmu_comp = bus.get("pmu")
        pmu = pmu_comp.pmu if pmu_comp else None
        self._watchdog = CellWatchdog(
            self.cell_id, pmu=pmu,
            on_timeout=lambda a, s: bus.emit("watchdog.timeout", {"agent_id": a, "state": s.name}),
            on_recovery=lambda a: bus.emit("watchdog.recovery", {"agent_id": a}),
            on_crash=lambda a: bus.emit("watchdog.crash", {"agent_id": a}),
        )
        self._bus = bus

    def register(self, agent_id: str, timeout: float = 0) -> None:
        if self._watchdog:
            self._watchdog.register(agent_id, timeout)

    def unregister(self, agent_id: str) -> None:
        if self._watchdog:
            self._watchdog.unregister(agent_id)

    def pet(self, agent_id: str) -> None:
        if self._watchdog:
            self._watchdog.pet(agent_id)

    def bus_start(self) -> None:
        if self._watchdog:
            self._watchdog.start()

    def bus_stop(self) -> None:
        if self._watchdog:
            self._watchdog.stop()

    def bus_health(self) -> dict:
        if not self._watchdog:
            return {"status": "not_inited"}
        return {"status": "ok", "running": self._watchdog._running}

    @property
    def watchdog(self):
        return self._watchdog


# ════════════════════════════════════════════════════════════════
# CellICacheComponent
# ════════════════════════════════════════════════════════════════

class CellICacheComponent(Component):
    """Wraps ICache — instruction cache (LFU, read-mostly)."""

    meta = ComponentMeta(name="icache", depends_on=["pmu"], tags=["cell", "cache"])

    def __init__(self, cell_id: str, **ic_kwargs: Any):
        super().__init__()
        self.cell_id = cell_id
        self._ic_kwargs = ic_kwargs
        self._icache = None

    def bus_init(self, bus: SystemBus) -> None:
        from .cell_icache import ICache
        pmu_comp = bus.get("pmu")
        pmu = pmu_comp.pmu if pmu_comp else None
        self._icache = ICache(self.cell_id, pmu=pmu, **self._ic_kwargs)

    def store(self, key: str, value: Any, **kw: Any) -> None:
        if self._icache:
            self._icache.store(key, value, **kw)

    def load(self, key: str) -> Any | None:
        return self._icache.load(key) if self._icache else None

    def bus_health(self) -> dict:
        if not self._icache:
            return {"status": "not_inited"}
        return {"status": "ok"}

    @property
    def icache(self):
        return self._icache


# ════════════════════════════════════════════════════════════════
# CellMmuComponent (includes TLB)
# ════════════════════════════════════════════════════════════════

class CellMmuComponent(Component):
    """Wraps CellMmu + CellTlb — territory→agent translation."""

    meta = ComponentMeta(name="mmu", depends_on=["pmu", "icache"], tags=["cell", "routing"])

    def __init__(self, cell_id: str, **mmu_kwargs: Any):
        super().__init__()
        self.cell_id = cell_id
        self._mmu_kwargs = mmu_kwargs
        self._mmu = None
        self._tlb = None

    def bus_init(self, bus: SystemBus) -> None:
        from .cell_mmu import CellMmu, CellTlb
        pmu_comp = bus.get("pmu")
        pmu = pmu_comp.pmu if pmu_comp else None
        ic = bus.get("icache")
        icache = ic.icache if ic else None
        self._tlb = CellTlb(pmu=pmu)
        self._mmu = CellMmu(self.cell_id, tlb=self._tlb, icache=icache, **self._mmu_kwargs)
        self._bus = bus

    def flush_agent(self, agent_id: str) -> int:
        if self._mmu:
            return self._mmu.flush_agent(agent_id)
        return 0

    def warm_from_agents(self, agents: dict) -> None:
        if self._mmu:
            self._mmu.warm_from_agents(agents)

    def bus_health(self) -> dict:
        if not self._mmu:
            return {"status": "not_inited"}
        return {"status": "ok", "tlb_entries": len(self._mmu.tlb._entries) if self._mmu.tlb else 0}

    @property
    def mmu(self):
        return self._mmu

    @property
    def tlb(self):
        return self._tlb


# ════════════════════════════════════════════════════════════════
# CellInterruptComponent
# ════════════════════════════════════════════════════════════════

class CellInterruptComponent(Component):
    """Wraps InterruptController — priority interrupt routing.

    Publishes events:
      interrupt.triggered → bus.emit("interrupt.triggered", {irq_num, name, priority})
    """

    meta = ComponentMeta(name="interrupt", depends_on=["pmu"], tags=["cell", "control"])

    def __init__(self, cell_id: str, **ic_kwargs: Any):
        super().__init__()
        self.cell_id = cell_id
        self._ic_kwargs = ic_kwargs
        self._interrupt = None

    def bus_init(self, bus: SystemBus) -> None:
        from .cell_interrupt import InterruptController
        pmu_comp = bus.get("pmu")
        pmu = pmu_comp.pmu if pmu_comp else None
        self._interrupt = InterruptController(self.cell_id, pmu=pmu, **self._ic_kwargs)

    def trigger(self, irq: int | str, data: Any = None) -> dict:
        if self._interrupt:
            r = self._interrupt.trigger(irq, data)
            self._bus.emit("interrupt.triggered", {"irq": irq, "data": data})
            return r
        return {"success": False, "error": "not inited"}

    def dispatch_pending(self, max_per: int = 5) -> int:
        if self._interrupt:
            return self._interrupt.dispatch_pending(max_per)
        return 0

    def bus_health(self) -> dict:
        if not self._interrupt:
            return {"status": "not_inited"}
        return {"status": "ok", "registered_irqs": len(self._interrupt._table)}

    @property
    def interrupt(self):
        return self._interrupt


# ════════════════════════════════════════════════════════════════
# CellCacheComponent
# ════════════════════════════════════════════════════════════════

class CellCacheComponent(Component):
    """Wraps CellCache — per-Cell L2 shared cache (D-Cache)."""

    meta = ComponentMeta(name="cache", depends_on=["pmu"], tags=["cell", "cache"])

    def __init__(self, cell_id: str, **cache_kwargs: Any):
        super().__init__()
        self.cell_id = cell_id
        self._cache_kwargs = cache_kwargs
        self._cache = None

    def bus_init(self, bus: SystemBus) -> None:
        from .cell_cache import CellCache
        pmu_comp = bus.get("pmu")
        pmu = pmu_comp.pmu if pmu_comp else None
        self._cache = CellCache(self.cell_id, pmu=pmu, **self._cache_kwargs)

    def inject(self, key: str, value: Any, **kw: Any) -> dict:
        if self._cache:
            return self._cache.inject(key, value, **kw)
        return {"success": False, "error": "not inited"}

    def lookup(self, key: str):
        return self._cache.lookup(key) if self._cache else None

    def flush(self) -> int:
        if self._cache:
            return self._cache.flush()
        return 0

    def bus_health(self) -> dict:
        if not self._cache:
            return {"status": "not_inited"}
        return {"status": "ok"}

    @property
    def cache(self):
        return self._cache
