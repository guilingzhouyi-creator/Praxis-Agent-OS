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
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from l1.kernel import EVENT_TASK_ASSIGN, get_event_bus, emit_signal, Signal, SignalType
from l1.kernel.bus import SystemBus
from l1.kernel.params.agent import (
    DEFAULT_AGENT_CONFIGS,
    CELL_ROLLBACK_RING_SIZE,
    CELL_HISTORY_RING_SIZE,
    CELL_SNAPSHOT_MAX,
    CELL_L3_SENDER,
)
from ..agent_terminal import TerminalCard, CardMode as TermCardMode, TerminalStatus, get_terminal, get_terminals
from ..cell.components.cell_agent import add_agent, _boot_agent
from ..agent.scout import get_pool as get_scout_pool
from l3.cell.components.cell_buffer import CircularBuffer
from ..cell.components.cell_decompose import decompose_card as _decompose_card, auto_agent_map as _auto_agent_map
from ..card.execution_plan import ExecutionPlan
from ..scheduler.think_registry import get_think_registry
from ..cell.components.cell_types import AgentStatus, AgentInfo, CellMessage, MessageType, is_peer, is_scout, is_subagent
from ..services.bus_components import (
    CellPmuComponent, CellWatchdogComponent, CellICacheComponent,
    CellMmuComponent, CellInterruptComponent, CellCacheComponent,
)
from ..cell.components.cell_execute import execute_card as _execute_card, _raw_to_card, _execute_decomposed
from ..cell.components.cell_rollback import rollback_card as _rollback_card
from ..cell.components.cell_cross_review import auto_cross_review as _auto_cross_review
from ..agent.subagent_spec import BUILTIN_SUBAGENTS
from ..agent.subagent_framework import get_dispatcher as get_subagent_dispatcher
from ..services.cell_orchestrate import SubAgentOrchestrator

logger = logging.getLogger(__name__)
from ..card.issue import IssueCard as _IssueCard



class Cell:
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
                 max_scout_cache_ttl: float = 30.0,
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
        except Exception:
            pass

        self._cell_bus.register(CellPmuComponent(cell_id))
        self._cell_bus.register(CellWatchdogComponent(cell_id))
        self._cell_bus.register(CellICacheComponent(cell_id))
        self._cell_bus.register(CellMmuComponent(cell_id))
        self._cell_bus.register(CellInterruptComponent(cell_id))
        self._cell_bus.register(CellCacheComponent(cell_id))
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

        # Wire interrupt handlers
        self._wire_interrupts()

        # Register built-in subagent specs
        self._subagent_dispatcher = get_subagent_dispatcher()
        for spec in BUILTIN_SUBAGENTS.values():
            self._subagent_dispatcher.register_spec(spec)

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
                   auto_boot: bool = False) -> dict:
        defaults = DEFAULT_AGENT_CONFIGS.get(role) if role else None
        info = AgentInfo(role=role, ring=ring or (defaults.ring if defaults else 1),
                         territory=territory or [],
                         max_concurrent_scouts=max_scouts or (defaults.max_scouts if defaults else 3))
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
        except Exception:
            pass
        try:
            from ..memory.context_pool import unregister as _unregister_cp
            _unregister_cp(agent_id)
            from l3.memory.memory import get_memory
            get_memory().forget_agent(agent_id)
        except Exception:
            pass
        return {"success": True, "agent_id": agent_id, "action": "removed"}

    # ══ Cell state persistence ══

    def save_state(self, path: str = "") -> dict:
        """Save Cell state (agents, conventions, snapshots) to JSON."""
        from l1.kernel.paths import get_paths as _gp
        path = path or _gp().cell_state_template.format(self.cell_id)
        state = {
            "cell_id": self.cell_id, "territory": self.territory,
            "agents": {},
            "card_history": [h for h in self._card_history],
        }
        with self._lock:
            for aid, info in self._agents.items():
                state["agents"][aid] = {
                    "role": info.role, "ring": info.ring,
                    "territory": info.territory,
                    "max_concurrent_scouts": info.max_concurrent_scouts,
                    "status": info.status.name,
                }
        try:
            import json as _json
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(state, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, path)
            return {"success": True, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def restore_state(self, path: str = "") -> dict:
        """Restore Cell state from JSON."""
        from l1.kernel.paths import get_paths as _gp
        path = path or _gp().cell_state_template.format(self.cell_id)
        if not os.path.exists(path):
            return {"success": False, "error": "no state file"}
        try:
            import json as _json
            with open(path, encoding="utf-8") as f:
                state = _json.load(f)
            self.cell_id = state.get("cell_id", self.cell_id)
            with self._lock:
                for aid, d in state.get("agents", {}).items():
                    if aid not in self._agents:
                        from ..cell.components.cell_types import AgentStatus
                        from l1.kernel.params.agent import DEFAULT_AGENT_CONFIGS
                        cfg = DEFAULT_AGENT_CONFIGS.get(d.get("role", ""))
                        info = AgentInfo(
                            role=d.get("role", ""),
                            ring=d.get("ring", cfg.ring if cfg else 1),
                            territory=d.get("territory", []),
                            max_concurrent_scouts=d.get("max_concurrent_scouts",
                                                         cfg.max_scouts if cfg else 3),
                            status=AgentStatus[d.get("status", "IDLE")],
                        )
                        self._agents[aid] = info
                        self._mailbox[aid] = []
            return {"success": True, "agents": len(state.get("agents", {}))}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══ Agent-to-Agent Messaging ══

    _CONVENTION_TYPES = frozenset({
        MessageType.CONVENE, MessageType.CROSS_EXAMINE,
        MessageType.REBUT, MessageType.PROPOSE_ISSUE,
        MessageType.CONVENE_CLOSE,
    })

    def send_message(self, sender: str, target: str,
                     msg_type: MessageType, payload: Any = None) -> dict:
        with self._lock:
            if target not in self._agents:
                return {"success": False, "error": f"unknown target: {target}"}
            if sender not in self._agents:
                return {"success": False, "error": f"unknown sender: {sender}"}
            # TTL cleanup: discard expired messages
            from l1.kernel.params.agent import CELL_MAILBOX_MAX_PER_AGENT, CELL_MAILBOX_TTL
            now = time.time()
            inbox = self._mailbox.setdefault(target, [])
            inbox[:] = [m for m in inbox if now - m.timestamp < CELL_MAILBOX_TTL]
            if len(inbox) >= CELL_MAILBOX_MAX_PER_AGENT:
                inbox.pop(0)
            msg = CellMessage(msg_type=msg_type, sender=sender, target=target, payload=payload)
            inbox.append(msg)
            self._bus.emit(Signal(type=SignalType.TASK_ASSIGN, sender=sender,
                                  target=target, data={"cell": self.cell_id, "msg_type": msg_type.name}))
        self._pmu.increment("bus.messages_sent")
        from ..bus.comm_monitor import get_monitor
        get_monitor().record_message(channel="cell_mailbox", msg_type="send",
                                      direction="out", agent_id=sender, target=target)
        # Convention messages also dispatch a TerminalCard to the agent's execution loop
        if msg_type in self._CONVENTION_TYPES:
            try:
                from ..agent_terminal import get_terminal, TerminalCard, CardMode as TermCardMode
                term = get_terminal(target)
                from l1.kernel.params.agent import AGENT_STATUS_CRASHED
                if term.status.name not in (AGENT_STATUS_CRASHED,):
                    tcard = TerminalCard(
                        mode=TermCardMode.EXECUTE,
                        action="convention",
                        target=payload.get("card_id", "conv-unknown"),
                        params={"msg_type": msg_type.name, "payload": payload, "sender": sender},
                        sender="cell",
                    )
                    term.dispatch(tcard)
            except Exception as e:
                logger.warning("cell dispatch convention card to %s failed: %s", target, e)
        return {"success": True, "msg_id": msg.msg_id}

    def read_messages(self, agent_id: str, clear: bool = True) -> list[dict]:
        with self._lock:
            msgs = self._mailbox.get(agent_id, [])
            if clear:
                self._mailbox[agent_id] = []
            return [
                {"msg_id": m.msg_id, "type": m.msg_type.name,
                 "sender": m.sender, "payload": m.payload, "timestamp": m.timestamp}
                for m in msgs
            ]

    def agent_reachable(self, agent_id: str) -> dict:
        """Check if a specific agent can accept a direct message."""
        from ..agent_terminal import get_terminals
        term = get_terminals().get(agent_id)
        if not term:
            return {"reachable": False, "reason": "no_terminal", "agent_id": agent_id}
        return term.session_reachable()

    def send_direct_message(self, agent_id: str, text: str) -> dict:
        """Send a direct message to an agent via its stdin queue."""
        from ..agent_terminal import get_terminals
        term = get_terminals().get(agent_id)
        if not term:
            return {"success": False, "error": f"unknown agent: {agent_id}"}
        r = term.session_reachable()
        if not r.get("reachable"):
            return {"success": False, "error": f"unreachable: {r.get('reason')}"}
        return term.send_direct_message(text)

    def liveness(self) -> dict:
        """Check Cell and all agent terminals liveness.

        Used by Shell (L2) Direct Mode to verify target reachability.
        Returns aggregate status: healthy / degraded / unreachable.
        """
        from ..agent_terminal import get_terminals
        terms = get_terminals()
        agent_results = {}
        healthy_count = 0
        total_count = 0
        with self._lock:
            agent_ids = list(self._agents.keys())
        for aid in agent_ids:
            total_count += 1
            term = terms.get(aid)
            if term is None:
                agent_results[aid] = {"status": "no_terminal", "alive": False}
                continue
            from l1.kernel.params.agent import (
                AGENT_STATUS_IDLE,
                AGENT_STATUS_PROCESSING,
                AGENT_STATUS_WAITING_SCOUT,
                AGENT_STATUS_BOOTING,
            )
            if term.status.name in (AGENT_STATUS_IDLE, AGENT_STATUS_PROCESSING, AGENT_STATUS_WAITING_SCOUT):
                agent_results[aid] = {"status": term.status.name.lower(), "alive": True}
            elif term.status.name in (AGENT_STATUS_BOOTING,):
                agent_results[aid] = {"status": "booting", "alive": True}
                healthy_count += 1
            else:
                agent_results[aid] = {"status": term.status.name, "alive": False}

        if healthy_count == total_count:
            overall = "healthy"
        elif healthy_count > 0:
            overall = "degraded"
        else:
            overall = "unreachable"

        return {
            "cell_id": self.cell_id,
            "overall": overall,
            "agents": agent_results,
            "healthy": healthy_count,
            "total": total_count,
            "territory": self.territory,
        }

    def agent_status(self, agent_id: str) -> dict:
        return _agent_status(self, agent_id)

    # ══ Boot / Shutdown ══

    def on_boot(self, hook: Callable) -> None:
        """Register a boot hook invoked before each agent boots.

        ``hook(agent_id)`` is an observation point (no veto); boot is
        system-controlled. Raised exceptions are logged and swallowed.
        """
        if hook not in self._boot_hooks:
            self._boot_hooks.append(hook)

    def on_shutdown(self, hook: Callable) -> None:
        """Register a shutdown hook invoked before Cell shutdown.

        ``hook()`` is an observation point (no veto). Raised exceptions
        are logged and swallowed.
        """
        if hook not in self._shutdown_hooks:
            self._shutdown_hooks.append(hook)

    def on_spawn(self, hook: Callable) -> None:
        """Register a spawn hook invoked before adding an agent.

        ``hook(agent_id, role, territory, ring)`` may veto the spawn by
        returning ``{"success": False, "error": ...}``.
        """
        if hook not in self._spawn_hooks:
            self._spawn_hooks.append(hook)

    def on_kill(self, hook: Callable) -> None:
        """Register a kill hook invoked before removing an agent.

        ``hook(agent_id)`` may veto the kill by returning
        ``{"success": False, "error": ...}``.
        """
        if hook not in self._kill_hooks:
            self._kill_hooks.append(hook)

    def boot_agent(self, agent_id: str) -> dict:
        # Boot hooks — observe boot (no veto; boot is system-controlled).
        for hook in self._boot_hooks:
            try:
                hook(agent_id)
            except Exception as e:
                logger.warning("boot hook %s raised: %s", hook, e)
        self._pmu.increment("agent.boots")
        self._watchdog.register(agent_id)
        # Wire watchdog pet callback to agent terminal
        try:
            from ..agent_terminal import get_terminal
            term = get_terminal(agent_id)
            if term:
                term.set_watchdog_pet(lambda aid: self._watchdog.pet(aid))
        except Exception as e:
            logger.warning("watchdog wire failed: %s", e)
        return _boot_agent(self, agent_id)

    def boot_all(self) -> dict:
        results = {}
        with self._lock:
            agent_ids = list(self._agents.keys())
        for aid in agent_ids:
            results[aid] = self.boot_agent(aid)
        self._watchdog.start()
        return {"success": all(r.get("success", False) for r in results.values()),
                "agents": results}

    def shutdown_all(self) -> dict:
        self._watchdog.stop()
        # Shutdown hooks — observe shutdown (no veto).
        for hook in self._shutdown_hooks:
            try:
                hook()
            except Exception as e:
                logger.warning("shutdown hook %s raised: %s", hook, e)
        from ..agent_terminal import reset_terminals
        reset_terminals()
        with self._lock:
            for info in self._agents.values():
                info.status = AgentStatus.IDLE
        return {"success": True}

    # ══ Emergency stop & rollback ══

    def emergency_stop(self) -> dict:
        with self._lock:
            self._emergency = True
            agent_ids = list(self._agents.keys())
        from ..agent_terminal import get_terminals
        all_terms = get_terminals()
        paused = 0
        for aid in agent_ids:
            term = all_terms.get(aid)
            if term:
                try:
                    term.pause()
                    paused += 1
                except Exception as e:
                    logger.warning("Cell %s emergency_stop agent %s: %s", self.cell_id, aid, e)
        logger.warning("Cell %s EMERGENCY STOP: %d agents paused", self.cell_id, paused)
        return {"success": True, "cell_id": self.cell_id, "agents_paused": paused}

    def resume(self) -> dict:
        with self._lock:
            self._emergency = False
            agent_ids = list(self._agents.keys())
        from ..agent_terminal import get_terminals
        all_terms = get_terminals()
        resumed = 0
        for aid in agent_ids:
            term = all_terms.get(aid)
            if term:
                try:
                    term.resume()
                    resumed += 1
                except Exception as e:
                    logger.warning("Cell %s resume agent %s: %s", self.cell_id, aid, e)
        logger.info("Cell %s resumed: %d agents", self.cell_id, resumed)
        return {"success": True, "cell_id": self.cell_id, "agents_resumed": resumed}

    def reset_agent_context(self, agent_id: str) -> dict:
        """Reset an agent's working context to combat context pollution.

        Workflow:
          1. Pause the agent terminal (stop processing new cards)
          2. Compact low-value memory entries
          3. Clear Ring 1 (working memory) — the context pollution
          4. Reload Ring 2 (cached session memory) for continuity
          5. Resume the agent terminal

        Used by CentralController._process_admin_card (refresh_agent).
        """
        from ..agent_terminal import get_terminals
        term = get_terminals().get(agent_id)
        if not term:
            return {"success": False, "error": f"agent {agent_id} not found"}
        try:
            term.pause()
        except Exception as e:
            logger.warning("reset_agent_context pause failed: %s", e)
        try:
            from ..memory.memory import get_memory
            mem = get_memory()
            mem.compact(agent_id)
            mem.forget_agent(agent_id)
            mem.restore(ring2_limit=50)
        except Exception as e:
            logger.warning("reset_agent_context memory reset failed: %s", e)
        try:
            term.resume()
        except Exception as e:
            logger.warning("reset_agent_context resume failed: %s", e)
        logger.info("Cell %s reset context for agent %s", self.cell_id, agent_id)
        return {"success": True, "cell_id": self.cell_id, "agent_id": agent_id, "action": "context_reset"}

    # ══ Card Dispatch ══

    def dispatch_card(self, target_agent: str, action: str,
                      target: str = "", params: dict | None = None,
                      mode: TermCardMode = TermCardMode.EXECUTE,
                      sender: str = CELL_L3_SENDER) -> dict:
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
        from ..cell.components.cell_convention import convene as _convene
        return _convene(self, issue_card)

    def close_convention(self, issue_card_id: str) -> dict:
        from ..cell.components.cell_convention import close_convention as _close
        return _close(self, issue_card_id)

    def handle_convention_message(self, agent_id: str, msg_type: MessageType,
                                  payload: dict) -> dict:
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
            from tools._archive import archive_store
            import json as _json
            content = _json.dumps(item, default=str, ensure_ascii=False) if not isinstance(item, str) else item
            title = item.get("intent", str(item)[:80]) if isinstance(item, dict) else str(item)[:80]
            card_id = item.get("card_id", "evicted") if isinstance(item, dict) else "evicted"
            archive_store(
                fonds=f"CELL:RING:{kind}",
                series=f"evicted:{kind}",
                title=title,
                content=content[:5000],
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
        return _decompose_card(domain, card, self.cell_id,
                               ensure_terminal_fn=self._ensure_terminal)

    # ── Cross-review dispatch (delegates to cell_cross_review.py) ──

    def _auto_cross_review(self, completed_agent: str, action: str,
                           target: str, card_id: str,
                           timeout: float = 60.0) -> dict:
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

    def agent_tools(self, agent_id: str) -> list[dict]:
        all_terms = get_terminals()
        term = all_terms.get(agent_id)
        if not term:
            return []
        return term.list_tools()

    def cell_tools(self) -> dict[str, list[dict]]:
        all_terms = get_terminals()
        result: dict[str, list[dict]] = {}
        for aid, term in all_terms.items():
            tools = term.list_tools()
            if tools:
                result[aid] = tools
        return result

    def wait_for_card(self, card_id: str, timeout: float = 30.0) -> dict | None:
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
        except Exception:
            pass

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

    def dispatch_pending_interrupts(self, max_per: int = 5) -> int:
        """Dispatch pending queued interrupts. Called periodically."""
        return self._interrupt.dispatch_pending(max_per_priority=max_per)

    # ── SubAgent dispatch (Peer Agent → SubAgent delegation) ──

    def subagent_dispatch(self, spec_name: str, prompt: str,
                          parent_agent_id: str = "",
                          context: dict | None = None,
                          post_actions: list[dict] | None = None) -> dict:
        """Dispatch a SubAgent task with Cell-wired result delivery.

        The SubAgent runs in its own daemon thread.  On completion,
        the result is delivered to the parent Peer Agent via the
        CellMessage mailbox (SUBAGENT_RESULT).  If the Peer Agent is
        busy, the message queues in its mailbox (TTL 1h).

        post_actions: optional list of actions to execute after the
                      SubAgent completes, before delivery.  Each action:
                      {"type": "scout", "prompt": "Verify {result}"}
        """
        if post_actions:
            from ..agent.subagent_spec import SubAgentSpec
            # Create an anonymous spec with the post_actions
            spec = SubAgentSpec(
                name=spec_name,
                description="",
                read_only=True,
                post_actions=post_actions,
            )
            return self._subagent_dispatcher.dispatch(
                spec_name, prompt, parent_agent_id, context, cell=self,
            )
        return self._subagent_dispatcher.dispatch(
            spec_name=spec_name,
            prompt=prompt,
            parent_agent_id=parent_agent_id,
            context=context,
            cell=self,
        )
        """Dispatch a SubAgent task with Cell-wired result delivery.

        The SubAgent runs in its own daemon thread.  On completion,
        the result is delivered to the parent Peer Agent via the
        CellMessage mailbox (SUBAGENT_RESULT).  If the Peer Agent is
        busy, the message queues in its mailbox (TTL 1h).
        """
        return self._subagent_dispatcher.dispatch(
            spec_name=spec_name,
            prompt=prompt,
            parent_agent_id=parent_agent_id,
            context=context,
            cell=self,
        )

    def subagent_orchestrate(self, sub_tasks: list[dict],
                              parent_agent_id: str = "",
                              verify_prompt: str = "",
                              fork_timeout: float = 120.0,
                              verify_timeout: float = 60.0) -> dict:
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
        """Parse @mention from text and dispatch SubAgent."""
        return self._subagent_dispatcher.dispatch_from_text(
            text, parent_agent_id, cell=self,
        )

    # ── Scout result cache ──

    def reuse_scout_result(self, template: str, scope: dict | None = None,
                           ttl: float = 0) -> dict | None:
        cached = scout_cache_get(template, scope, ttl or self.max_scout_cache_ttl)
        return cached

    # ── Think quota management ──

    def set_think_quota(self, distribution: str | None = None,
                        **config: Any) -> None:
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
