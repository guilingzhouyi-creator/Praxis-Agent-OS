"""Cell 鈥?Agent collaboration unit.

Architecture:
  L3A (an Agent) reads human natural language 鈫?produces a Card.
  The Card defines work scope and target agent role.
  Cell holds N agents + shared ScoutPool.

  L3A 鈫?Cell 鈫?Agents (N peer agents, roles from Card)
              鈹溾攢鈹€ each can delegate to ScoutPool (Ring 1 investigation)
              鈹溾攢鈹€ each can spawn SubAgent (inline quick-check)
              鈹斺攢鈹€ auto cross-review on write/delete (CROSS_REVIEW_REQ)
              鈫?           ScoutPool (Ring 1 only, shared across Cell)
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
from l1.kernel.params.agent import (
    DEFAULT_AGENT_CONFIGS,
    CELL_ROLLBACK_RING_SIZE,
    CELL_HISTORY_RING_SIZE,
    CELL_SNAPSHOT_MAX,
    CELL_L3_SENDER,
)
from ..agent_terminal import TerminalCard, CardMode as TermCardMode, TerminalStatus, get_terminal, get_terminals
from ..cell_agent import add_agent, _boot_agent
from ..scout import get_pool as get_scout_pool
from ..cell_buffer import CircularBuffer
from ..cell_decompose import decompose_card as _decompose_card, auto_agent_map as _auto_agent_map
from ..execution_plan import ExecutionPlan
from ..think_registry import get_think_registry
from ..cell_types import AgentStatus, AgentInfo, CellMessage, MessageType, is_peer, is_scout, is_subagent
from ..cell_cache import CellCache

logger = logging.getLogger(__name__)
from ..issue import IssueCard as _IssueCard



class Cell:
    """Agent collaboration unit 鈥?N agents + ScoutPool.

    Agents are NOT hardcoded by role.  When a Card arrives, its steps
    declare which agent (by role string) should execute each step.
    The Cell auto-maps role 鈫?available agent_id at dispatch time.

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
        # Lifecycle hooks — explicit interception points for Cell boot,
        # shutdown, agent spawn (add) and agent kill (remove). Each is a
        # list of callables invoked in registration order; a hook may
        # veto spawn/kill by returning {"success": False, "error": ...}.
        # Previously Cell had no explicit lifecycle hooks — callers had
        # to subscribe to SignalType on the event bus instead.
        self._boot_hooks: list[Callable] = []
        self._shutdown_hooks: list[Callable] = []
        self._spawn_hooks: list[Callable] = []
        self._kill_hooks: list[Callable] = []
        # Ring buffers for temp cache — evicted items go to R4 Archive
        self._rollback_ring = CircularBuffer(
            CELL_ROLLBACK_RING_SIZE,
            on_evict=lambda item: self._archive_item("rollback", item),
        )
        self._card_history = CircularBuffer(
            CELL_HISTORY_RING_SIZE,
            on_evict=lambda item: self._archive_item("card_history", item),
        )
        self._card_snapshots: dict[str, dict] = {}  # card_id → file snapshot (capped below)

        # Cell L2 shared cache — agents in this Cell share hot data here
        self._cache: CellCache = CellCache(cell_id)

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
            from ..think_registry import get_think_registry
            reg = get_think_registry()
            active = max(1, len([a for a in self._agents.values()
                                 if a.status.name in ("IDLE", "RUNNING")]))
            resolved = reg.resolve(self.cell_id, agent_id,
                                   active_agents=active,
                                   agent_model_config=info.model_config)
            if resolved:
                info.model_config = resolved
        # Spawn hooks 鈥?may veto by returning {"success": False, ...}.
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
        if auto_boot:
            return self.boot_agent(agent_id)
        return {"success": True}

    def remove_agent(self, agent_id: str) -> dict:
        """Remove an agent from the Cell.

        Shuts down the agent terminal, unregisters from mailbox and process table.
        Used by CentralController._process_admin_card (kill_agent).
        """
        # Kill hooks 鈥?may veto by returning {"success": False, ...}.
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
        try:
            term = get_terminals().get(agent_id)
            if term:
                term.shutdown()
        except Exception:
            pass
        try:
            from ..context_pool import unregister as _unregister_cp
            _unregister_cp(agent_id)
            from l3.memory import get_memory
            get_memory().forget_agent(agent_id)
        except Exception:
            pass
        return {"success": True, "agent_id": agent_id, "action": "removed"}

    # 鈹€鈹€ Cell state persistence 鈹€鈹€

    def save_state(self, path: str = "") -> dict:
        """Save Cell state (agents, conventions, snapshots) to JSON."""
        from l1.kernel.params.system import PRAXIS_CELL_STATE_TEMPLATE
        path = path or PRAXIS_CELL_STATE_TEMPLATE.format(self.cell_id)
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
        from l1.kernel.params.system import PRAXIS_CELL_STATE_TEMPLATE
        path = path or PRAXIS_CELL_STATE_TEMPLATE.format(self.cell_id)
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
                        from ..cell_types import AgentStatus
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

    # 鈹€鈹€ Agent-to-Agent Messaging 鈹€鈹€

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
            from l1.kernel.params.agent import CELL_MAILBOX_MAX_PER_AGENT
            now = time.time()
            inbox = self._mailbox.setdefault(target, [])
            inbox[:] = [m for m in inbox if now - m.timestamp < _ttl]
            if len(inbox) >= CELL_MAILBOX_MAX_PER_AGENT:
                inbox.pop(0)
            msg = CellMessage(msg_type=msg_type, sender=sender, target=target, payload=payload)
            inbox.append(msg)
            self._bus.emit(Signal(type=SignalType.TASK_ASSIGN, sender=sender,
                                  target=target, data={"cell": self.cell_id, "msg_type": msg_type.name}))
        from ..comm_monitor import get_monitor
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

    # 鈹€鈹€ Boot / Shutdown 鈹€鈹€

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
        # Boot hooks 鈥?observe boot (no veto; boot is system-controlled).
        for hook in self._boot_hooks:
            try:
                hook(agent_id)
            except Exception as e:
                logger.warning("boot hook %s raised: %s", hook, e)
        return _boot_agent(self, agent_id)

    def boot_all(self) -> dict:
        results = {}
        with self._lock:
            agent_ids = list(self._agents.keys())
        for aid in agent_ids:
            results[aid] = self.boot_agent(aid)
        return {"success": all(r.get("success", False) for r in results.values()),
                "agents": results}

    def shutdown_all(self) -> dict:
        # Shutdown hooks 鈥?observe shutdown (no veto).
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

    # 鈹€鈹€ Emergency stop & rollback 鈹€鈹€

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
          3. Clear Ring 1 (working memory) 鈥?the context pollution
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
            from ..memory import get_memory
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

    # 鈹€鈹€ Card Dispatch 鈹€鈹€

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
        emit_signal(EVENT_TASK_ASSIGN, sender=sender, target=target_agent,
                    data={"card_id": card_id, "action": action, "mode": mode.name})

        # 鈹€鈹€ Blocking cross-review gate for write operations 鈹€鈹€
        try:
            from ..tool_config import ToolConfig as _TC
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
        from ..cell_convention import convene as _convene
        return _convene(self, issue_card)

    def close_convention(self, issue_card_id: str) -> dict:
        from ..cell_convention import close_convention as _close
        return _close(self, issue_card_id)

    def handle_convention_message(self, agent_id: str, msg_type: MessageType,
                                  payload: dict) -> dict:
        from ..cell_convention import handle_convention_message as _handle
        return _handle(self, agent_id, msg_type, payload)


    # 鈹€鈹€ Card conversion helpers (extracted from execute_card) 鈹€鈹€

    def _raw_to_card(self, raw_intent: str, domain: str) -> Card:
        """Convert raw intent string to a structured Card via HTN or CardBuilder."""
        raw_domain = domain or (self.territory[0] if self.territory else "")
        try:
            from ..htn_planner import get_service as get_htn
            htn = get_htn()
            htn_task = htn.decompose(raw_intent, raw_domain)
            if htn_task.sub_tasks:
                return htn.to_card(htn_task, domain=raw_domain)
        except Exception as e:
            logger.warning('HTN decompose failed: %s', e)
        from ..card_builder import build_card as _build_structured_card
        return _build_structured_card(
            task_id=f'auto-{uuid.uuid4().hex[:8]}',
            intent=raw_intent, domain=raw_domain,
        )

    def _execute_decomposed(self, slices: list[dict]) -> dict:
        """Execute decomposed card slices and aggregate results."""
        all_steps = []
        overall_success = True
        for s in slices:
            plan = ExecutionPlan(s['card'], s['agent_map'], user_id=self._current_user_id)
            r = plan.execute()
            all_steps.extend(r.get('steps', []))
            if not r.get('success'):
                overall_success = False
        return {
            'success': overall_success, 'steps': all_steps,
            'total_steps': len(all_steps),
            'completed': sum(1 for s in all_steps if isinstance(s, dict) and s.get('success')),
            'failed': sum(1 for s in all_steps if isinstance(s, dict) and not s.get('success')),
            'territory_decomposed': True, 'sub_cards': len(slices),
        }

    def _snapshot_and_inject(self, card_id: str, card: Card) -> None:
        try:
            snapshot = self._take_snapshot(card)
            self._card_snapshots[card_id] = {"_ts": time.time(), "files": snapshot}
            if len(self._card_snapshots) > CELL_SNAPSHOT_MAX:
                oldest = min(self._card_snapshots.keys(),
                             key=lambda k: self._card_snapshots[k].get('_ts', 0))
                self._card_snapshots.pop(oldest, None)
                self._cleanup_snapshot(snapshot)
        except Exception as e:
            logger.warning('snapshot failed (non-fatal): %s', e)
        rollback_ring = self._rollback_ring
        if rollback_ring.all():
            try:
                from ..context import get_context as get_ctx_reg
                ctx_reg = get_ctx_reg(self.cell_id)
                ctx_reg.store(key='rollback_context', value=rollback_ring.all()[-1],
                              agent_id='system', entry_type='rollback')
            except Exception as e:
                logger.warning('rollback context inject failed: %s', e)

    def execute_card(self, card: Card | str, agent_map: dict[str, str] | None = None,
                     domain: str = "", user_id: str = "") -> dict:
        """Execute a Card through the Cell.

        Accepts both structured Card and raw intent string.
        Raw strings are auto-converted via CardBuilder (L3A).
        Cards with a domain are decomposed by territory 鈥?steps go
        to the owning agent.  Results are aggregated.

        Args:
            card:       structured Card with phases and steps, or raw intent string
            agent_map:  optional override (role 鈫?agent_id).
                        If omitted, auto-generated from Card steps + territory.
            domain:     domain/project path (used when card is a raw string)
            user_id:    human user ID for LLM KV cache isolation.
                        Passed through to AgentLoop 鈫?LLM API as user_id parameter.

        Returns aggregated plan result with per-step details.
        """
        # Detect IssueCard 鈫?route to convention protocol
        try:
            from ..issue import IssueCard as _IssueCard
        except ImportError:
            _IssueCard = None
        if isinstance(card, _IssueCard):
            return self.convene(card, agent_map)

        self._current_user_id = user_id
        try:
            from ..scheduler import get_scheduler as get_sched
            sched = get_sched()
            for aid, info in self._agents.items():
                sched.router.register(aid, self.territory, info.ring / 3.0)
        except Exception as e:
            logger.warning("scheduler register failed: %s", e)
        if isinstance(card, str):
            card = self._raw_to_card(card, domain)

        domain = domain or card.domain
        if domain and agent_map is None:
            slices = self.decompose_card(card, domain)
            if len(slices) > 1:
                result = self._execute_decomposed(slices)
                result["card_id"] = card.id
                result["intent"] = card.intent[:80]
                return result

        if agent_map is None:
            agent_map = self._auto_agent_map(card)

        all_terms = get_terminals()
        for _, aid in agent_map.items():
            term = all_terms.get(aid)
            if term and term.status in (TerminalStatus.BOOTING, TerminalStatus.STOPPED):
                term.boot()

        if self._emergency:
            return {"success": False, "error": "Cell emergency stopped", "cell_id": self.cell_id}

        card_id = card.id if hasattr(card, 'id') else f"card-{uuid.uuid4().hex[:8]}"

        # Pre-execution snapshot + rollback context injection
        self._snapshot_and_inject(card_id, card)

        plan = ExecutionPlan(card, agent_map, user_id=self._current_user_id)
        try:
            result = plan.execute()
        finally:
            # Clean up snapshot temp files for this card to avoid /tmp leaks.
            # The rollback_card path pops the snapshot for the same card_id first,
            # so only completed snapshots are cleaned here; rollback flow is unaffected.
            snap_wrapper = self._card_snapshots.pop(card_id, None)
            if snap_wrapper and isinstance(snap_wrapper, dict):
                self._cleanup_snapshot(snap_wrapper.get("files", {}))
        result["card_id"] = card_id

        # Record card history in ring buffer
        self._card_history.push({
            "card_id": card_id,
            "intent": card.intent[:60] if hasattr(card, 'intent') else str(card)[:60],
            "completed_at": time.time(),
            "success": result.get("success", False),
        })
        result["intent"] = card.intent[:80] if hasattr(card, 'intent') else str(card)[:80]
        result["agent_map"] = agent_map
        return result

    # 鈹€鈹€ Snapshot / Rollback 鈹€鈹€

    @staticmethod
    def _take_snapshot(card: Any) -> dict:
        import shutil
        import tempfile
        snapshot = {}
        steps = card.all_steps() if hasattr(card, 'all_steps') else []
        seen = set()
        for step in steps:
            target = getattr(step, 'target', '') or step.params.get('path', '') if hasattr(step, 'params') else ''
            if target and target not in seen and os.path.isfile(target):
                seen.add(target)
                fd, tmp = tempfile.mkstemp(suffix=".snapshot")
                os.close(fd)
                try:
                    shutil.copy2(target, tmp)
                    snapshot[target] = tmp
                except Exception as e:
                    logger.warning("snapshot failed for %s: %s", target, e)
        return snapshot

    @staticmethod
    def _cleanup_snapshot(snapshot: dict) -> None:
        for tmp_path in snapshot.values():
            try:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

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
        """Rollback changes from a card execution.

        Uses:
          1. fault_tolerance checkpoint (per-agent per-step)
          2. Pre-execution file snapshots (restore originals)
          3. Sandbox discard (pending changes)
          4. Terminal reset

        After rollback, stores info in _rollback_context for the next card.
        """
        from ..fault_tolerance import get_service as get_ft
        from ..sandbox import get_cell_sandbox
        ft = get_ft()
        results = {}

        # 1. Restore checkpoints
        if card_id:
            cp_r = ft.restore_checkpoint(card_id)
            results["checkpoint_restore"] = cp_r
        else:
            with self._lock:
                agents = list(self._agents.keys())
            for aid in agents:
                ft.restore_checkpoint(aid)
            results["checkpoint_restore"] = {"agents": agents}

        # 2. Restore file snapshots
        snap_wrapper = self._card_snapshots.pop(card_id, {})
        snap = snap_wrapper.get("files", snap_wrapper) if isinstance(snap_wrapper, dict) else {}
        restored_files = 0
        for original_path, tmp_path in snap.items():
            if original_path == "_ts":
                continue
            try:
                import shutil
                shutil.copy2(tmp_path, original_path)
                os.remove(tmp_path)
                restored_files += 1
            except Exception as e:
                logger.warning("rollback restore snapshot %s: %s", original_path, e)
        results["files_restored"] = restored_files

        # 3. Discard sandbox
        try:
            sb = get_cell_sandbox(self.cell_id)
            discard_r = sb.discard()
            results["sandbox_discard"] = discard_r
        except Exception as e:
            results["sandbox_discard"] = {"error": str(e)}

        # 4. Reset terminals to IDLE
        from ..agent_terminal import get_terminals
        terms = get_terminals()
        for aid in terms:
            try:
                terms[aid].pause()
                terms[aid].resume()
            except Exception as e:
                logger.warning("rollback reset terminal %s: %s", aid, e)
        results["terminals_reset"] = len(terms)

        # 5. Store rollback info in ring buffer for next card's context
        rollback_msg = f"Card {card_id} was rolled back. {results.get('files_restored', 0)} files restored."
        self._rollback_ring.push(rollback_msg)

        # 6. Remove from history ring
        if card_id:
            self._card_history.remove(card_id)
        else:
            self._card_history = CircularBuffer(CELL_HISTORY_RING_SIZE)

        logger.info("Cell %s rollback complete: %s", self.cell_id, results)
        return {"success": True, "cell_id": self.cell_id, "results": results,
                "rollback_context": rollback_msg}

    # 鈹€鈹€ Card decomposition engine (delegates to cell_decompose.py) 鈹€鈹€

    def decompose_card(self, card: Card, domain: str = "") -> list[dict]:
        return _decompose_card(domain, card, self.cell_id,
                               ensure_terminal_fn=self._ensure_terminal)

    # 鈹€鈹€ Cross-review dispatch 鈹€鈹€

    def _auto_cross_review(self, completed_agent: str, action: str,
                           target: str, card_id: str,
                           timeout: float = 60.0) -> dict:
        """After a write/delete/rename, BLOCKING wait for peer agent review.

        Sends CROSS_REVIEW_REQ to all peer agents, then blocks until
        all peers respond (CROSS_REVIEW_RESP) or timeout.

        Returns:
            {"approved": bool, "reviews": list[dict], "reason": str}
        """
        from threading import Event as _Event
        if action not in ("write_file", "replace_string", "delete", "rename"):
            return {"approved": True, "action": "skip"}
        if not target:
            return {"approved": True, "action": "skip"}
        if not is_peer(completed_agent):
            return {"approved": True, "action": "skip"}

        with self._lock:
            peers = [aid for aid in self._agents
                     if aid != completed_agent and is_peer(aid)]
        if not peers:
            return {"approved": True, "action": "no_peers"}

        # Create a one-shot event per peer to wait for responses
        resp_events: dict[str, _Event] = {p: _Event() for p in peers}
        resp_results: dict[str, dict] = {}

        def _on_resp(sender: str, payload: dict) -> None:
            if sender in resp_events:
                resp_results[sender] = payload
                resp_events[sender].set()

        # Register a temporary handler for CROSS_REVIEW_RESP
        _handler_key = f"_cr_resp_{card_id}"
        original = None
        try:
            from l1.kernel.event import get_bus as _get_bus
            bus = _get_bus()
            bus.on_any(lambda sig: (
                _on_resp(sig.sender, sig.data) if (
                    hasattr(sig, 'data') and
                    isinstance(sig.data, dict) and
                    sig.data.get("msg_type") == "CROSS_REVIEW_RESP" and
                    sig.data.get("card_id") == card_id
                ) else None
            ))
        except Exception as e:
            logger.warning("cross-review subscription failed: %s", e)

        # Send review requests
        for peer in peers:
            self.send_message(completed_agent, peer, MessageType.CROSS_REVIEW_REQ, {
                "file": target, "card_id": card_id, "action": action,
                "from": completed_agent,
                "msg": f"Please review changes to {target} made by {completed_agent}.",
            })
            logger.info("cross-review: %s 鈫?%s for %s (blocking)", completed_agent, peer, target)

        # Block until all peers respond or timeout
        approved = True
        reasons = []
        for peer, evt in resp_events.items():
            ok = evt.wait(timeout=timeout)
            if ok:
                resp = resp_results.get(peer, {})
                verdict = resp.get("verdict", resp.get("status", "APPROVED"))
                if verdict in ("REJECT", "REJECTED", "NEEDS_CHANGES"):
                    approved = False
                    reasons.append(f"{peer}: {resp.get('reason', verdict)}")
            else:
                reasons.append(f"{peer}: timeout after {timeout}s")

        return {
            "approved": approved,
            "reviews": list(resp_results.values()),
            "reason": "; ".join(reasons) if reasons else "",
        }

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
            from ..tool_spec import TOOL_REGISTRY
            term.set_tool_registry(TOOL_REGISTRY)
        except Exception as e:
            logger.warning("tool inject failed: %s", e)

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

    # ── Scout result cache ──

    def reuse_scout_result(self, template: str, scope: dict | None = None,
                           ttl: float = 0) -> dict | None:
        cached = scout_cache_get(template, scope, ttl or self.max_scout_cache_ttl)
        return cached

    # ── Think quota management ──

    def set_think_quota(self, distribution: str | None = None,
                        **config: Any) -> None:
        from ..think_registry import get_think_registry
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
            }

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
