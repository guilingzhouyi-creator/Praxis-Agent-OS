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
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..card.card_unified import CardUnified as Card
    from .components.cell_watchdog import WatchdogState

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal, get_event_bus
from l1.kernel.bus import SystemBus
from l1.kernel.params.agent import (
    AGENT_LOOP_DEFAULT_TIMEOUT,
    CARD_WAIT_TIMEOUT,
    CELL_HISTORY_RING_SIZE,
    CELL_L3_SENDER,
    CELL_ROLLBACK_RING_SIZE,
    DEFAULT_AGENT_CONFIGS,
    DEFAULT_AGENT_RING,
    DEFAULT_MAX_CONCURRENT_SCOUTS,
)
from l1.kernel.params.system import (
    CROSS_REVIEW_TIMEOUT,
    IRQ_DISPATCH_BATCH,
    LOG_TRUNC_80,
    LOG_TRUNC_5000,
    SCOUT_CACHE_TTL,
    SUBAGENT_ORCHESTRATE_VERIFY_TIMEOUT,
)
from l3.cell.components.cell_buffer import CircularBuffer

from ..agent.scout import get_pool as get_scout_pool
from ..agent.scout import scout_cache_get
from ..agent_terminal import CardMode as TermCardMode
from ..agent_terminal import TerminalCard, TerminalStatus, get_terminal, get_terminals
from ..card.issue import IssueCard as _IssueCard
from ..cell.components.cell_cross_review import auto_cross_review as _auto_cross_review
from ..cell.components.cell_decompose import auto_agent_map as _auto_agent_map
from ..cell.components.cell_decompose import decompose_card as _decompose_card
from ..cell.components.cell_execute import _execute_decomposed, _raw_to_card
from ..cell.components.cell_execute import execute_card as _execute_card
from ..cell.components.cell_lifecycle import CellLifecycleMixin
from ..cell.components.cell_messaging import CellMessagingMixin
from ..cell.components.cell_rollback import rollback_card as _rollback_card
from ..cell.components.cell_types import AgentInfo, CellMessage, MessageType
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
from ..services.cell_orchestrate import SubAgentOrchestrator

logger = logging.getLogger(__name__)



class Cell(CellLifecycleMixin, CellMessagingMixin):
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

    def __init__(self, cell_id: str, territory: list[str] | None = None,
                 max_scout_cache_ttl: float = SCOUT_CACHE_TTL,
                 think_quota: dict | None = None,
                 distribution_mode: str = "inherit"):
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
        pool_config = {}  # populated from cell config in future
        self._subagent_pool = SubAgentPool(cell_id, config=pool_config)

        # Register with ThinkQuotaRegistry
        if think_quota:
            get_think_registry().set_cell(
                cell_id, distribution=distribution_mode, **think_quota
            )

    def add_agent(self, agent_id: str, role: str = "",
                   territory: list[str] | None = None,
                   ring: int | None = None,
                   max_scouts: int | None = None,
                   model_config: dict | None = None,
                   auto_boot: bool = True) -> dict:
        """Register a new agent in this Cell."""
        defaults = DEFAULT_AGENT_CONFIGS.get(role) if role else None
        info = AgentInfo(role=role, ring=ring or (defaults.ring if defaults else DEFAULT_AGENT_RING),
                         territory=territory or [],
                         max_concurrent_scouts=max_scouts or (defaults.max_scouts if defaults else DEFAULT_MAX_CONCURRENT_SCOUTS))
        # Apply model_config: param overrides defaults, overrides registry
        if model_config:
            info.model_config = model_config
        elif defaults and defaults.model_config:
            info.model_config = dict(defaults.model_config)
        else:
            # Resolve from ThinkQuotaRegistry for this agent
            from ..scheduler.think_registry import get_think_registry
            reg = get_think_registry()
            active = max(1, len([a for a in self._agents.values()
                                 if a.status.name in ("IDLE", "RUNNING")]))
            resolved = reg.resolve(self.cell_id, agent_id,
                                   active_agents=active,
                                   agent_model_config=info.model_config)
            if resolved:
                info.model_config = resolved
        # Spawn hooks — may veto by returning {"success": False, ...}.
        for hook in self._spawn_hooks:
            try:
                vr = hook(agent_id, role, territory, ring)
                if isinstance(vr, dict) and not vr.get("success", True):
                    return {"success": False,
                            "error": f"spawn hook vetoed: {vr.get('error', '?')}",
                            "hook_error": vr}
            except Exception as e:
                logger.warning("spawn hook %s raised: %s", hook, e)
        with self._lock:
            if agent_id in self._agents:
                return {"success": False, "error": f"agent {agent_id} already registered"}
            self._agents[agent_id] = info
            self._mailbox[agent_id] = []
        # Warm MMU TLB with the new agent's territory mappings
        self._mmu.warm_from_agents(self._agents)
        if auto_boot:
            return self.boot_agent(agent_id)
        return {"success": True}

    def remove_agent(self, agent_id: str) -> dict:
        """Remove an agent from the Cell.

        Shuts down the agent terminal, unregisters from mailbox and process table.
        Used by CentralController._process_admin_card (kill_agent).
        """
        # Kill hooks — may veto by returning {"success": False, ...}.
        for hook in self._kill_hooks:
            try:
                vr = hook(agent_id)
                if isinstance(vr, dict) and not vr.get("success", True):
                    return {"success": False,
                            "error": f"kill hook vetoed: {vr.get('error', '?')}",
                            "hook_error": vr}
            except Exception as e:
                logger.warning("kill hook %s raised: %s", hook, e)
        from ..agent_terminal import get_terminals
        with self._lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"agent {agent_id} not found"}
            del self._agents[agent_id]
            self._mailbox.pop(agent_id, None)
            self._watchdog.unregister(agent_id)
            self._mmu.flush_agent(agent_id)
        try:
            term = get_terminals().get(agent_id)
            if term:
                term.shutdown()
        except Exception as e:
            logger.warning("cell/__init__: %s", e)
        try:
            from ..memory.context_pool import unregister as _unregister_cp
            _unregister_cp(agent_id)
            from l3.memory.memory import get_memory
            get_memory().forget_agent(agent_id)
        except Exception as e:
            logger.warning("cell/__init__: %s", e)
        # Emit cell bus event for sandbox _path_index cleanup
        try:
            self._cell_bus.emit("cell.agent_removed", {"agent_id": agent_id, "cell_id": self.cell_id})
        except Exception as e:
            logger.warning("cell/__init__: %s", e)
        return {"success": True, "agent_id": agent_id, "action": "removed"}

    # ══ Cell state persistence ══

    def save_state(self, path: str = "") -> dict:
        """Persist Cell state to disk."""
        from ..cell.components.cell_state import save_state as _save
        return _save(self, path)

    def restore_state(self, path: str = "") -> dict:
        """Restore Cell state from disk."""
        from ..cell.components.cell_state import restore_state as _restore
        return _restore(self, path)

    # ══ Card Dispatch ══

    def dispatch_card(self, target_agent: str, action: str,
                      target: str = "", params: dict | None = None,
                      mode: TermCardMode = TermCardMode.EXECUTE,
                      sender: str = CELL_L3_SENDER) -> dict:
        """Dispatch a card to the appropriate agent."""
        term = get_terminal(target_agent)
        if term.status in (TerminalStatus.BOOTING, TerminalStatus.STOPPED):
            term.boot()
        if term.status == TerminalStatus.CRASHED:
            return {"success": False, "error": f"terminal {target_agent} crashed"}
        card = TerminalCard(
            mode=mode, action=action, target=target,
            params=params or {}, sender=sender,
        )
        card_id = term.dispatch(card)
        self._pmu.increment("cards.dispatched")
        emit_signal(EVENT_TASK_ASSIGN, sender=sender, target=target_agent,
                    data={"card_id": card_id, "action": action, "mode": mode.name})

        # ══ Blocking cross-review gate for write operations ══
        try:
            from ..tool_system.tool_config import ToolConfig as _TC
            _is_write = action in _TC.write_tool_names()
        except Exception:
            _is_write = False
        if _is_write:
            review = self._auto_cross_review(target_agent, action, target, card_id)
            if not review.get("approved"):
                return {"success": False, "card_id": card_id,
                        "error": f"cross-review rejected: {review.get('reason', '')}",
                        "review": review}

        return {"success": True, "card_id": card_id}

    def convene(self, issue_card: Any, agent_map: dict[str, str] | None = None) -> dict:
        """Convene a multi-agent discussion on a topic."""
        from ..cell.components.cell_convention import convene as _convene
        return _convene(self, issue_card)

    # ── Memory policy engine (deliberation isolation) ──

    def set_memory_policy(self, policy: str) -> None:
        """Switch the Cell memory policy.

        isolated     — default: Peer Agents' R1-R3 stays agent-isolated
        deliberation — L3A conference mode: Cell's shared ring is activated
                       for the convention (convene() sets, close_convention()
                       restores)
        """
        from l1.kernel.params.agent import (
            CELL_MEMORY_POLICY_DELIBERATION,
            CELL_MEMORY_POLICY_ISOLATED,
        )
        if policy not in (CELL_MEMORY_POLICY_ISOLATED, CELL_MEMORY_POLICY_DELIBERATION):
            logger.warning("cell %s: unknown memory policy %r", self.cell_id, policy)
            return
        old = self._memory_policy
        self._memory_policy = policy
        if policy == CELL_MEMORY_POLICY_DELIBERATION:
            from l3.memory.central_memory import get_cell_memory
            self._convention_memory = get_cell_memory(self.cell_id)
        else:
            self._convention_memory = None
        logger.info("cell %s: memory policy %s → %s", self.cell_id, old, policy)

    def get_memory_policy(self) -> str:
        return self._memory_policy

    def convention_memory(self) -> Any | None:
        """Return the Cell's shared deliberation memory ring.

        Strategy guard: returns None unless the Cell is in deliberation
        (conference) mode — the shared ring is NOT accessible in isolated
        (default) mode. Peer Agents' negotiation context lives here during
        a convention; outside conventions each agent keeps isolated memory.
        """
        if self._memory_policy == "deliberation":
            return self._convention_memory
        return None

    def close_convention(self, issue_card_id: str) -> dict:
        """Close the currently active convention."""
        from ..cell.components.cell_convention import close_convention as _close
        return _close(self, issue_card_id)

    def handle_convention_message(self, agent_id: str, msg_type: MessageType,
                                  payload: dict) -> dict:
        """Process a message for the active convention."""
        from ..cell.components.cell_convention import handle_convention_message as _handle
        return _handle(self, agent_id, msg_type, payload)


    # ── Card conversion helpers (delegated to cell_execute.py) ──

    def _raw_to_card(self, raw_intent: str, domain: str,
                     skip_htn: bool = False) -> Card:
        """Convert raw intent string to a structured Card. Delegates to cell_execute.py."""
        return _raw_to_card(self, raw_intent, domain, skip_htn=skip_htn)

    def _execute_decomposed(self, slices: list[dict]) -> dict:
        """Execute decomposed card slices. Delegates to cell_execute.py."""
        return _execute_decomposed(self, slices)

    def _snapshot_and_inject(self, card_id: str, card: Card) -> None:
        """Snapshot files and inject rollback context. Delegates to cell_execute.py."""
        from ..cell.components.cell_execute import _snapshot_and_inject as _ssi
        _ssi(self, card_id, card)

    @staticmethod
    def _take_snapshot(card: Any) -> dict:
        """Snapshot files referenced in card steps. Delegates to cell_execute.py."""
        from ..cell.components.cell_execute import _take_snapshot as _ts
        return _ts(card)

    @staticmethod
    def _cleanup_snapshot(snapshot: dict) -> None:
        """Clean up temporary snapshot files. Delegates to cell_execute.py."""
        from ..cell.components.cell_execute import _cleanup_snapshot as _cs
        _cs(snapshot)

    @staticmethod
    def _archive_item(kind: str, item: Any) -> None:
        """Archive an evicted ring buffer item to R4 Archive.

        Called by CircularBuffer.on_evict when the ring is full.
        Prevents data loss: evicted items go to permanent cold storage.
        """
        try:
            import json as _json

            from tools._archive import archive_store
            content = _json.dumps(item, default=str, ensure_ascii=False) if not isinstance(item, str) else item
            title = item.get("intent", str(item)[:LOG_TRUNC_80]) if isinstance(item, dict) else str(item)[:LOG_TRUNC_80]
            card_id = item.get("card_id", "evicted") if isinstance(item, dict) else "evicted"
            archive_store(
                fonds=f"CELL:RING:{kind}",
                series=f"evicted:{kind}",
                title=title,
                content=content[:LOG_TRUNC_5000],
                tags=["ring_eviction", kind, card_id],
                agent_id="system",
            )
        except Exception as e:
            logging.getLogger(__name__).warning("archive_item %s: %s", kind, e)

    def rollback_card(self, card_id: str = "") -> dict:
        """Rollback changes from a card execution. Delegates to cell_rollback.py."""
        self._pmu.increment("cards.rolled_back")
        return _rollback_card(self, card_id=card_id)

    # ══ Card decomposition engine (delegates to cell_decompose.py) ══

    def decompose_card(self, card: Card, domain: str = "") -> list[dict]:
        """Decompose a card into executable steps."""
        return _decompose_card(domain, card, self.cell_id,
                               ensure_terminal_fn=self._ensure_terminal)

    # ── Cross-review dispatch (delegates to cell_cross_review.py) ──

    def _auto_cross_review(self, completed_agent: str, action: str,
                           target: str, card_id: str,
                           timeout: float = CROSS_REVIEW_TIMEOUT) -> dict:
        """After a write/delete/rename, BLOCKING wait for peer agent review.
        Delegates to cell_cross_review.py.
        """
        return _auto_cross_review(self, completed_agent, action, target, card_id, timeout=timeout)

    def execute_card(self, card: Any, agent_map: dict[str, str] | None = None,
                     domain: str = "", user_id: str = "") -> dict:
        """Execute a Card through the Cell. Delegates to cell_execute.py."""
        return _execute_card(self, card, agent_map=agent_map, domain=domain, user_id=user_id)

    def _auto_agent_map(self, card: Card) -> dict[str, str]:
        return _auto_agent_map(card, self.cell_id,
                               ensure_terminal_fn=lambda a, r, t: self._ensure_terminal(a, r, t or self.territory))

    def _ensure_terminal(self, aid: str, role: str, territory: list[str]) -> None:
        term = get_terminal(aid, role=role, territory=territory, cell_id=self.cell_id)
        if term.status in (TerminalStatus.BOOTING, TerminalStatus.STOPPED):
            term.boot()
        if term._tool_registry is None:
            self._inject_tools(term)

    def _inject_tools(self, term: Any) -> None:
        try:
            from ..tool_system.tool_spec import TOOL_REGISTRY
            term.set_tool_registry(TOOL_REGISTRY)
        except Exception as e:
            logger.warning("tool inject failed: %s", e)
        # Wire PMU to the global pipeline for tool execution counters
        try:
            from ..tool_system.tool_pipeline import get_pipeline
            get_pipeline().set_pmu(self._pmu)
        except Exception as e:
            logger.warning("pipeline pmu wire failed: %s", e)
        # Wire PMU to the AgentTerminal (→ AgentLoop for compression telemetry)
        try:
            term.set_pmu(self._pmu)
        except Exception as e:
            logger.warning("term pmu wire failed: %s", e)

    def agent_tools(self, agent_id: str) -> list[dict]:
        """List tools available to a specific agent."""
        all_terms = get_terminals()
        term = all_terms.get(agent_id)
        if not term:
            return []
        return term.list_tools()

    def cell_tools(self) -> dict[str, list[dict]]:
        """List tools registered at the Cell level."""
        all_terms = get_terminals()
        result: dict[str, list[dict]] = {}
        for aid, term in all_terms.items():
            tools = term.list_tools()
            if tools:
                result[aid] = tools
        return result

    def wait_for_card(self, card_id: str, timeout: float = CARD_WAIT_TIMEOUT) -> dict | None:
        """Block until a card is dispatched."""
        for term in get_terminals().values():
            result = term.wait_for_result(card_id, timeout)
            if result:
                return {"success": result.success, "card_id": result.card_id,
                        "action": result.action, "output": result.output,
                        "findings": result.findings, "error": result.error,
                        "elapsed": result.elapsed, "phases": result.phase}
        return None

    # ── Cell L2 shared cache ──

    @property
    def cache(self):
        """Access the Cell L2 shared cache (CellCache).

        Agents in the same Cell share hot data here via
        inject/lookup/search — low-token-cost cross-agent sharing.
        """
        return self._cache

    # ── PMU (Performance Monitoring Unit) ──

    @property
    def pmu(self):
        """Access the Cell PMU — hardware-style performance counters."""
        return self._pmu

    # ── Watchdog (per-agent liveness monitor) ──

    @property
    def watchdog(self):
        """Access the Cell Watchdog — monitors agent liveness via pet()."""
        return self._watchdog

    def _watchdog_on_timeout(self, agent_id: str, state: WatchdogState) -> None:
        """Called when an agent misses a pet deadline — mark UNRESPONSIVE."""
        logger.warning("watchdog timeout: %s → %s", agent_id, state.name)
        try:
            from ..agent_terminal import get_terminal
            term = get_terminal(agent_id)
            if term:
                term.pause()
        except Exception as e:
            logger.warning("watchdog pause failed: %s", e)

    def _watchdog_on_recovery(self, agent_id: str) -> None:
        """Called when an agent pets after being UNRESPONSIVE — resume."""
        logger.info("watchdog recovery: %s", agent_id)
        try:
            from ..agent_terminal import get_terminal
            term = get_terminal(agent_id)
            if term:
                term.resume()
        except Exception as e:
            logger.warning("watchdog resume failed: %s", e)

    def _watchdog_on_crash(self, agent_id: str) -> None:
        """Called after consecutive misses — NMI + TLB flush + auto-reboot."""
        logger.error("watchdog crash: %s — NMI + auto-reboot", agent_id)
        self._pmu.increment("agent.crashes")
        self._mmu.flush_agent(agent_id)
        self._interrupt.trigger("watchdog.crash", data={"agent_id": agent_id})
        try:
            from ..agent_terminal import get_terminal
            term = get_terminal(agent_id)
            if term:
                term.shutdown()
                term.boot()
                self._pmu.increment("agent.recoveries")
        except Exception as e:
            logger.warning("watchdog reboot failed: %s", e)

    # ── I-Cache (Instruction Cache) ──

    @property
    def icache(self):
        """Access the Cell I-Cache — instruction cache for tools/templates/territory maps."""
        return self._icache

    # ── MMU + TLB (Memory Management Unit) ──

    @property
    def mmu(self):
        """Access the Cell MMU — territory→agent translation unit."""
        return self._mmu

    @property
    def tlb(self):
        """Access the Cell TLB — translation lookaside buffer (part of MMU)."""
        return self._mmu.tlb

    # ── InterruptController (Priority Interrupt) ──

    @property
    def interrupt(self):
        """Access the Cell InterruptController — priority-based event routing."""
        return self._interrupt

    # ── PermissionController (Delegation Control) ──

    @property
    def permission(self):
        """Access the Cell PermissionController — delegation authorization."""
        return self._permission

    def _wire_interrupts(self) -> None:
        """Wire built-in handlers to interrupt IRQs + cell bus events."""
        if self._interrupt:
            self._interrupt.set_handler("task.assign", lambda e: self._pmu.increment("bus.signals_emitted") if self._pmu else None)
            self._interrupt.set_handler("token.usage", lambda e: self._pmu.increment("token.consumed") if self._pmu else None)
            self._interrupt.set_handler("cache.flush", lambda e: self._cache.flush() if self._cache else None)
            self._interrupt.set_handler("constitution.violation", lambda e: self._mmu.flush_all() if self._mmu else None)

        # Wire cell bus events (watchdog → TLB flush, etc.)
        try:
            self._cell_bus.on("watchdog.crash", lambda e: self._bus_watchdog_crash(e))
            self._cell_bus.on("watchdog.timeout", lambda e: self._bus_watchdog_timeout(e))
            self._cell_bus.on("watchdog.recovery", lambda e: self._bus_watchdog_recovery(e))
        except Exception as e:
            logger.warning("cell/__init__: %s", e)

        # Wire agent removal → sandbox cleanup
        try:
            self._cell_bus.on("cell.agent_removed", self._bus_agent_removed)
        except Exception as e:
            logger.warning("cell/__init__: %s", e)

        # Wire discussion events (Layer 3 integration)
        try:
            self._cell_bus.on("discussion.start", lambda e: self._bus_discussion_start(e))
        except Exception as e:
            logger.warning("cell/__init__: %s", e)

    def _bus_discussion_start(self, event: dict) -> None:
        """Bus event: start an AnswerSession for this Cell."""
        try:
            from l3.card.issue import get_table
            from l3.discussion.answer_session import AnswerSession
            data = event.get("data", {})
            session_id = data.get("session_id", "")
            issue_card_id = data.get("issue_card_id", "")
            if not session_id or not issue_card_id:
                return
            card = get_table().get(issue_card_id)
            if not card:
                return
            session = AnswerSession(session_id, self.cell_id, self, card)
            result = session.run()
            if result.get("success"):
                self._cell_bus.emit("discussion.cell_complete", {
                    "session_id": session_id,
                    "cell_id": self.cell_id,
                    "answer_count": result.get("phases", {}).get(5, {}).get("answers", 0),
                    "supplement_count": result.get("phases", {}).get(3, {}).get("supplements", 0),
                })
        except Exception as e:
            logger.warning("discussion start failed: %s", e)

    def _bus_watchdog_timeout(self, event: dict) -> None:
        """Bus event: watchdog timeout → pause terminal."""
        agent_id = event.get("data", {}).get("agent_id", "")
        if not agent_id:
            return
        try:
            from ..agent_terminal import get_terminal
            term = get_terminal(agent_id)
            if term:
                term.pause()
        except Exception as e:
            logger.warning("watchdog pause failed: %s", e)

    def _bus_watchdog_recovery(self, event: dict) -> None:
        """Bus event: watchdog recovery → resume terminal."""
        agent_id = event.get("data", {}).get("agent_id", "")
        if not agent_id:
            return
        try:
            from ..agent_terminal import get_terminal
            term = get_terminal(agent_id)
            if term:
                term.resume()
        except Exception as e:
            logger.warning("watchdog resume failed: %s", e)

    def _bus_watchdog_crash(self, event: dict) -> None:
        """Bus event: watchdog crash → NMI + TLB flush + auto-reboot."""
        agent_id = event.get("data", {}).get("agent_id", "")
        if not agent_id:
            return
        logger.error("watchdog crash: %s — NMI + auto-reboot", agent_id)
        if self._pmu:
            self._pmu.increment("agent.crashes")
        if self._mmu:
            self._mmu.flush_agent(agent_id)
        if self._interrupt:
            self._interrupt.trigger("watchdog.crash", data={"agent_id": agent_id})
        try:
            from ..agent_terminal import get_terminal
            term = get_terminal(agent_id)
            if term:
                term.shutdown()
                term.boot()
                if self._pmu:
                    self._pmu.increment("agent.recoveries")
        except Exception as e:
            logger.warning("watchdog reboot failed: %s", e)

    def _bus_agent_removed(self, event: dict) -> None:
        """Cell bus event: agent removed → clean up sandbox _path_index."""
        agent_id = event.get("data", {}).get("agent_id", "")
        if not agent_id:
            return
        try:
            from l4.sandbox.cell_sandbox import get_manager as _get_sm
            sb = _get_sm().get_cell(self.cell_id)
            if sb:
                sb.discard(agent_id)
        except Exception as e:
            logger.warning("sandbox cleanup for %s failed: %s", agent_id, e)

    def dispatch_pending_interrupts(self, max_per: int = IRQ_DISPATCH_BATCH) -> int:
        """Dispatch pending queued interrupts. Called periodically."""
        return self._interrupt.dispatch_pending(max_total=max_per)

    def subagent_orchestrate(self, sub_tasks: list[dict],
                              parent_agent_id: str = "",
                              verify_prompt: str = "",
                               fork_timeout: float = AGENT_LOOP_DEFAULT_TIMEOUT,
                              verify_timeout: float = SUBAGENT_ORCHESTRATE_VERIFY_TIMEOUT) -> dict:
        """Full fork-join orchestration: SubAgents + Scout verify + gap analysis.

        sub_tasks: [{"spec": "architect", "prompt": "review src/"},
                    {"spec": "security-auditor", "prompt": "check auth.py"}]
        verify_prompt: Scout prompt template ({spec}, {answer}, {result})

        Returns structured result with:
          - phases[].buffer_1  — SubAgent work results
          - phases[].buffer_2  — Scout verification results
          - phases[].gap_analysis — gaps vs verified
          - todo_items — TodoTracker-compatible self-correction items

        The Peer Agent should feed todo_items into its TodoTracker
        and let the AgentLoop's self-correction mechanism retry gaps.
        """
        orch = SubAgentOrchestrator(self, parent_agent_id)
        return orch.run(sub_tasks, verify_prompt, fork_timeout, verify_timeout)

    def subagent_dispatch_from_text(self, text: str,
                                     parent_agent_id: str = "") -> dict:
        """Parse @mention from text and dispatch via SubAgentPool."""
        return self._subagent_pool.dispatch_from_text(
            text, parent_agent_id, cell=self,
        )

    def subagent_dispatch(self, spec: str, prompt: str,
                          parent_agent_id: str = "",
                          post_actions: list | None = None,
                          card_type: str = "explore") -> dict:
        """Dispatch a single SubAgent task via the Cell's SubAgentPool.

        Documented in cell-agent.md — dispatches a SubAgent (read-only for
        ``card_type="explore"``), runs it in the pool's own worker, and
        returns the task id for later collection via ``pool.collect()``.

        ``post_actions`` is accepted for API compatibility; post-dispatch
        actions are executed by the pool/orchestrator pipeline.
        """
        from l3.agent.subagent_spec import SubAgentSpec
        sub_spec = SubAgentSpec(name=spec, read_only=(card_type == "explore"), description="")
        r = self._subagent_pool.commission(
            sub_spec, prompt, card_type=card_type,
            parent_agent_id=parent_agent_id, cell=self,
        )
        if not r.get("success"):
            return r
        return {
            "success": True,
            "task_id": r["task_id"],
            "spec": spec,
            "post_actions": post_actions or [],
        }

    # ── Scout result cache ──

    def reuse_scout_result(self, template: str, scope: dict | None = None,
                           ttl: float = 0) -> dict | None:
        """Reuse cached scout results to avoid re-scouting."""
        cached = scout_cache_get(template, scope, ttl or self.max_scout_cache_ttl)
        return cached

    # ── Think quota management ──

    def set_think_quota(self, distribution: str | None = None,
                        **config: Any) -> None:
        """Set think/reasoning quota for an agent."""
        from ..scheduler.think_registry import get_think_registry
        reg = get_think_registry()
        if distribution:
            self.distribution_mode = distribution
        if config:
            self.think_quota = {**(self.think_quota or {}), **config}
        reg.set_cell(self.cell_id,
                     distribution=self.distribution_mode,
                     **(self.think_quota or {}))
        active = max(1, len([a for a in self._agents.values()
                             if a.status.name in ("IDLE", "RUNNING")]))
        for aid, info in self._agents.items():
            resolved = reg.resolve(self.cell_id, aid,
                                   active_agents=active,
                                   agent_model_config=info.model_config)
            if resolved:
                info.model_config = resolved
        logger.info("cell %s: think_quota updated (distribution=%s, cfg=%s)",
                     self.cell_id, self.distribution_mode, config)

    def stats(self) -> dict:
        with self._lock:
            return {
                "cell_id": self.cell_id,
                "territory": self.territory,
                "think_distribution": self.distribution_mode,
                "think_quota": self.think_quota,
                "agents": {aid: {
                    "role": info.role if isinstance(info.role, str) else (
                        info.role.name if hasattr(info.role, 'name') else str(info.role)),
                    "ring": info.ring,
                    "status": info.status.name,
                    "active_scouts": info.active_scouts,
                    "max_scouts": info.max_concurrent_scouts,
                    "messages": len(self._mailbox.get(aid, [])),
                    "model_config": info.model_config,
                } for aid, info in self._agents.items()},
                "pmu": self._pmu.stats(),
                "watchdog": self._watchdog.status(),
                "icache": self._icache.stats(),
                "mmu": self._mmu.stats(),
                "interrupt": self._interrupt.stats(),
            }

    def get_agent_ids(self) -> list[str]:
        """Return list of agent IDs registered in this cell."""
        with self._lock:
            return list(self._agents.keys())

    def get_agent_count(self) -> int:
        """Return number of agents registered in this cell."""
        with self._lock:
            return len(self._agents)

    def pmu_snapshot(self) -> dict | None:
        """Take a PMU snapshot and return it as a dict."""
        snap = self._pmu.snapshot()
        if snap is None:
            return None
        return {"timestamp": snap.timestamp, "counters": snap.counters}

_cells: dict[str, Cell] = {}
_cells_lock = threading.Lock()


def get_cell(cell_id: str, territory: list[str] | None = None) -> Cell:
    with _cells_lock:
        if cell_id not in _cells:
            _cells[cell_id] = Cell(cell_id, territory)
        return _cells[cell_id]


def get_cells() -> dict[str, Cell]:
    """Return all registered Cells. Used by selector for preselect."""
    with _cells_lock:
        return dict(_cells)


def reset_cells() -> None:
    with _cells_lock:
        _cells.clear()
