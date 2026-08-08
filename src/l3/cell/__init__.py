"""Cell — Agent collaboration unit.

Architecture:
  L3A (an Agent) reads human natural language → produces a Card.
  The Card defines work scope and target agent role.
  Cell holds N agents + shared ScoutPool.

  L3A → Cell → Agents (N peer agents, roles from Card)
              ├── each can delegate to ScoutPool (Ring 1 investigation)
              ├── each can spawn SubAgent (inline quick-check)
              └── auto cross-review on write/delete (CROSS_REVIEW_REQ)
              →            ScoutPool (Ring 1 only, shared across Cell)

The Cell class composes five domain mixins from ``components/``:
core (agents/skills/state), card (dispatch/execution), events (bus wiring),
stats (observability), and subagent (orchestration).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from l1.kernel import get_event_bus
from l1.kernel.bus import SystemBus
from l1.kernel.params.agent import (
    CELL_HISTORY_RING_SIZE,
    CELL_ROLLBACK_RING_SIZE,
)
from l1.kernel.params.system import SCOUT_CACHE_TTL
from l3.cell.components.cell_buffer import CircularBuffer

from ..agent.scout import get_pool as get_scout_pool
from ..cell.components.cell_card import CellCardMixin
from ..cell.components.cell_core import CellCoreMixin
from ..cell.components.cell_events import CellEventsMixin
from ..cell.components.cell_lifecycle import CellLifecycleMixin
from ..cell.components.cell_messaging import CellMessagingMixin
from ..cell.components.cell_stats import CellStatsMixin
from ..cell.components.cell_subagent import CellSubAgentMixin
from ..cell.components.cell_types import AgentInfo, CellMessage
from ..scheduler.think_registry import get_think_registry
from ..services.bus_components import (
    CellCacheComponent,
    CellICacheComponent,
    CellInterruptComponent,
    CellMmuComponent,
    CellPermissionComponent,
    CellPmuComponent,
    CellWatchdogComponent,
)

logger = logging.getLogger(__name__)


class Cell(
    CellLifecycleMixin,
    CellMessagingMixin,
    CellCoreMixin,
    CellCardMixin,
    CellEventsMixin,
    CellStatsMixin,
    CellSubAgentMixin,
):
    """Agent collaboration unit — N agents + ScoutPool.

    Agents are NOT hardcoded by role.  When a Card arrives, its steps
    declare which agent (by role string) should execute each step.
    The Cell auto-maps role → available agent_id at dispatch time.

    Usage:
      cell = Cell("cell-1", territory=["src", "docs"])
      cell.add_agent("agent-a", role="reader", territory=["docs"], ring=1)
      cell.add_agent("agent-b", role="writer", territory=["src"], ring=2)
      cell.execute_card("fix bug in login")
    """

    def __init__(
        self,
        cell_id: str,
        territory: list[str] | None = None,
        max_scout_cache_ttl: float = SCOUT_CACHE_TTL,
        think_quota: dict | None = None,
        distribution_mode: str = "inherit",
    ):
        self.cell_id = cell_id
        self.territory = territory or []
        self.max_scout_cache_ttl = max_scout_cache_ttl
        self.think_quota: dict | None = think_quota
        self.distribution_mode: str = distribution_mode

        self._agents: dict[str, AgentInfo] = {}
        self._mailbox: dict[str, list[CellMessage]] = {}
        # RLock: add_agent → boot_agent →_boot_agent re-enters the same lock;
        # Lock() would deadlock on a second acquire from the same thread.
        self._lock = threading.RLock()
        self._bus = get_event_bus()
        self._pool = get_scout_pool()
        self._current_user_id: str = ""
        self._emergency: bool = False
        self._conventions: dict[str, Any] = {}
        # Memory policy engine: isolated (default) vs deliberation (conference mode)
        from l1.kernel.params.agent import CELL_MEMORY_POLICY_ISOLATED

        self._memory_policy: str = CELL_MEMORY_POLICY_ISOLATED
        self._convention_memory: Any = None
        # Lifecycle hooks
        self._boot_hooks: list[Callable] = []
        self._shutdown_hooks: list[Callable] = []
        self._spawn_hooks: list[Callable] = []
        self._kill_hooks: list[Callable] = []
        # Ring buffers for temp cache
        self._rollback_ring = CircularBuffer(
            CELL_ROLLBACK_RING_SIZE,
            on_evict=lambda item: self._archive_item("rollback", item),
        )
        self._card_history = CircularBuffer(
            CELL_HISTORY_RING_SIZE,
            on_evict=lambda item: self._archive_item("card_history", item),
        )
        self._card_snapshots: dict[str, dict] = {}

        # ── SystemBus: register all components ──
        self._cell_bus = SystemBus(name=cell_id)
        try:
            from l1.kernel.bus import get_root_bus

            root = get_root_bus()
            root._children[cell_id] = self._cell_bus
            self._cell_bus.parent = root
        except Exception as e:
            logger.warning("cell/__init__: %s", e)

        self._cell_bus.register(CellPmuComponent(cell_id))
        self._cell_bus.register(CellWatchdogComponent(cell_id))
        self._cell_bus.register(CellICacheComponent(cell_id))
        self._cell_bus.register(CellMmuComponent(cell_id))
        self._cell_bus.register(CellInterruptComponent(cell_id))
        self._cell_bus.register(CellCacheComponent(cell_id))
        self._cell_bus.register(CellPermissionComponent(cell_id))
        self._cell_bus.install()

        # Shortcuts for backward-compatible access
        pmu_comp = self._cell_bus.get("pmu")
        self._pmu = pmu_comp.pmu if pmu_comp else None
        self._watchdog = getattr(self._cell_bus.get("watchdog"), "watchdog", None)
        self._icache = getattr(self._cell_bus.get("icache"), "icache", None)
        mmu_comp = self._cell_bus.get("mmu")
        self._mmu = mmu_comp.mmu if mmu_comp else None
        self._tlb = mmu_comp.tlb if mmu_comp else None
        self._interrupt = getattr(self._cell_bus.get("interrupt"), "interrupt", None)
        self._cache = getattr(self._cell_bus.get("cache"), "cache", None)
        self._permission = getattr(self._cell_bus.get("permission"), "permission", None)

        # Wire interrupt handlers
        self._wire_interrupts()

        # Bind constitution to cell bus (for violation NMI emission)
        try:
            from l1.kernel.constitution import get_constitution

            get_constitution().bind_cell(self._cell_bus)
        except Exception as e:
            logger.warning("cell/__init__: %s", e)

        # SubAgent delegation pool (async, ring-limited)
        from l3.agent.subagent_pool import SubAgentPool

        pool_config: dict = {}  # populated from cell config in future
        self._subagent_pool = SubAgentPool(cell_id, config=pool_config)

        # Register with ThinkQuotaRegistry
        if think_quota:
            get_think_registry().set_cell(cell_id, distribution=distribution_mode, **think_quota)


_cells: dict[str, Cell] = {}
_cells_lock = threading.Lock()


def get_cell(cell_id: str, territory: list[str] | None = None) -> Cell:
    """Return the Cell for cell_id, creating it lazily."""
    with _cells_lock:
        if cell_id not in _cells:
            _cells[cell_id] = Cell(cell_id, territory)
        return _cells[cell_id]


def get_cells() -> dict[str, Cell]:
    """Return all registered Cells. Used by selector for preselect."""
    with _cells_lock:
        return dict(_cells)


def reset_cells() -> None:
    """Clear all registered Cells."""
    with _cells_lock:
        _cells.clear()
