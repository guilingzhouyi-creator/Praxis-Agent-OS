"""AgentTerminal — persistent background terminal process for one Agent.

Extracted from:
  - _term_types.py: TerminalStatus, CardMode, TerminalCard, CardResult
  - _term_handlers.py: handler registry, default handlers, _HANDLER_MAP
"""
from __future__ import annotations

import logging
import os as _os
import threading
import time
import uuid
from collections import OrderedDict, deque
from typing import Any

from l1.kernel import emit_signal, get_event_bus
from l1.kernel.allocator import get_allocator
from l1.kernel.constitution import get_constitution
from l1.kernel.params.agent import (
    AGENT_CLEARANCE,
    AGENT_LOOP_DEFAULT_STEPS,
    AGENT_LOOP_DEFAULT_TIMEOUT,
    AGENT_TERMINAL_MAX_SCOUTS,
    AGENT_TERMINAL_STDERR_MAX,
    AGENT_TERMINAL_STDIN_MAX,
    AGENT_TERMINAL_STDOUT_MAX,
    AGENT_TERMINAL_WORKER_JOIN_TIMEOUT,
    CARD_WAIT_TIMEOUT,
    DEFAULT_AGENT_CONFIGS,
    EVENT_REVIEW_REQUESTED,
    TERMINAL_MAX_WORKERS,
)
from l1.kernel.params.kernel import RING_1
from l1.kernel.params.system import (
    HASH_TRUNC_SHORT,
    LOG_TRUNC_80,
    LOG_TRUNC_200,
    LOG_TRUNC_500,
    POLL_INTERVAL_SLOW,
    SCOUT_COLLECT_TIMEOUT,
)
from l3.services.model_service import get_service as _get_model_service

from ..agent._term_lifecycle import run_cache_keepalive  # noqa: F401  (re-export)
from ..agent._term_types import CardMode, CardResult, TerminalCard, TerminalStatus  # noqa: F401  (CardMode re-export)
from ..agent.scout import get_pool as get_scout_pool
from ..memory.cache import get_context_register, get_file_cache
from .card_execution import CardExecutionMixin
from .worker_pool import WorkerPoolMixin

logger = logging.getLogger(__name__)

_PROJECT_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))

_MODEL_SPEC = "peer_agent"


class AgentTerminal(CardExecutionMixin, WorkerPoolMixin):
    """Persistent background terminal process for one Agent."""

    def __init__(self, agent_id: str, role: str = "",
                 territory: list[str] | None = None,
                 cell_id: str = "", project_root: str = ""):
        self.agent_id = agent_id
        self.role = role
        self.territory = territory or []
        self.cell_id = cell_id
        self._project_root = project_root or _PROJECT_ROOT

        cfg = DEFAULT_AGENT_CONFIGS.get(role) if role else None
        self.ring = cfg.ring if cfg else AGENT_CLEARANCE.get(role, 1)
        self.max_scouts = cfg.max_scouts if cfg else AGENT_TERMINAL_MAX_SCOUTS
        # model_config: resolve from ThinkQuotaRegistry (global → cell → agent)
        self.model_config = None
        try:
            from ..scheduler.think_registry import get_think_registry
            reg = get_think_registry()
            self.model_config = reg.resolve(
                cell_id, agent_id,
                agent_model_config=cfg.model_config if cfg else None,
            ) or None
        except Exception:
            # Fallback: use config defaults directly
            self.model_config = cfg.model_config if cfg and cfg.model_config else None
        self.system_prompt_key = cfg.system_prompt_key if cfg and cfg.system_prompt_key else ""
        self.status = TerminalStatus.BOOTING
        self.bus = get_event_bus()
        self.constitution = get_constitution()
        self.allocator = get_allocator()
        self.scout_pool = get_scout_pool()
        self.file_cache = get_file_cache(cell_id)
        self.context = get_context_register(cell_id)

        self.stdin: deque[TerminalCard] = deque(maxlen=AGENT_TERMINAL_STDIN_MAX)
        self.stdout: deque[CardResult] = deque(maxlen=AGENT_TERMINAL_STDOUT_MAX)
        self.stderr: deque[str] = deque(maxlen=AGENT_TERMINAL_STDERR_MAX)
        self._pending: dict[str, threading.Event] = {}
        self._results: OrderedDict[str, CardResult] = OrderedDict()
        self._lock = threading.RLock()
        self._running = False
        self._workers: list[threading.Thread] = []
        self._max_workers = TERMINAL_MAX_WORKERS
        self._boot_result: dict = {}
        self._convention_loops: dict[str, Any] = {}
        self._cards_processed = 0
        self._active_cards = 0
        self._async_scouts: dict[str, dict] = {}
        self._async_pending: set[str] = set()
        self._async_scout_events: dict[str, threading.Event] = {}
        self._async_scout_count = 0
        self._tool_registry: dict[str, Any] | None = None
        from l1.kernel.params.agent import TERMINAL_MODE_DEFAULT, TERMINAL_STATE_DEFAULT
        self._loop_mode: str = TERMINAL_MODE_DEFAULT
        self._loop_state: str = TERMINAL_STATE_DEFAULT
        self._paused: bool = False
        # Persistent AgentLoop — reuse across cards for conversational continuity
        self._persistent_loop: bool = False
        self._active_loop: Any = None
        self._active_loop_lock: Any = threading.Lock()
        # Card timeout guard — interrupt stuck cards
        self._card_timeout: float = 0.0
        self._card_deadline: float = 0.0
        self._current_card: str = ""
        self._cards_since_pressure_check: int = 0
        # ── AgentLoop instance budget (reserved, not yet enforced) ──
        from l1.kernel.params.agent import TERMINAL_MAX_CONCURRENT_LOOPS
        self._max_concurrent_loops: int = TERMINAL_MAX_CONCURRENT_LOOPS
        self._active_loops: int = 0
        from ..services.todo import TodoTable
        self.todo = TodoTable(agent_id)
        # Watchdog pet callback (set by Cell)
        self._watchdog_pet: Any = None
        # PMU reference (set by Cell._inject_tools)
        self._pmu: Any = None

    def set_max_workers(self, count: int) -> dict:
        """Dynamically adjust the max worker thread count.

        If the terminal is already running and *count* exceeds the current
        worker count, additional worker threads are spawned immediately.
        Reduced counts take effect as workers finish their current card.
        """
        self._max_workers = max(1, count)
        if self._running:
            current = len([w for w in self._workers if w.is_alive()])
            for i in range(current, self._max_workers):
                w = threading.Thread(target=self._worker, daemon=True,
                                     name=f"term-{self.agent_id}-w{i}")
                w.start()
                self._workers.append(w)
        return {"success": True, "max_workers": self._max_workers}

    def set_pmu(self, pmu: Any) -> None:
        """Attach the PMU reference used for tool injection."""
        self._pmu = pmu

    def set_tool_registry(self, registry: dict[str, Any]) -> None:
        """Attach the tool registry used for tool listing."""
        self._tool_registry = registry

    def set_watchdog_pet(self, fn: Any) -> None:
        """Set the watchdog pet callback, called after each card completes."""
        self._watchdog_pet = fn

    def list_tools(self) -> list[dict]:
        """List tools available to this terminal, filtered by ring and muting."""
        if not self._tool_registry:
            return []
        from l1.kernel.params.kernel import RING_NUM_MAP as _RNM
        from l3.tool_system.tool_spec import is_muted as _is_muted
        tools = []
        for name, spec in self._tool_registry.items():
            sr = getattr(spec, "ring", RING_1)
            if self.ring >= _RNM.get(sr, 1) and not _is_muted(name):
                tools.append({"name": name, "ring": sr,
                              "danger": getattr(spec, "danger", 0),
                              "description": getattr(spec, "description", "")[:LOG_TRUNC_80]})
        return sorted(tools, key=lambda t: (t["ring"], t["name"]))







    def _issue_card(self, card: TerminalCard) -> CardResult:
        emit_signal(EVENT_REVIEW_REQUESTED, sender=self.agent_id, target="cell",
                     data={"type": "issue", "action": card.action, "target": card.target,
                           "params": card.params, "card_id": card.card_id, "proposed_by": self.agent_id})
        return CardResult(card_id=card.card_id, action=card.action,
                          success=True, output=f"issue created: {card.action}", phase=["issue"])

    # ── Todo Table API ──

    def add_todo(self, intent: str, domain: str = "", priority: int = 5,
                 depends_on: list[str] | None = None) -> str:
        """Add a todo entry; returns the new todo id."""
        tid = self.todo.add(intent, domain, priority, depends_on)
        with self._lock:
            if self.status in (TerminalStatus.IDLE,):
                self.status = TerminalStatus.PROCESSING
        return tid

    def list_todos(self, status: str = "", limit: int = 20) -> list[dict]:
        """List todos, optionally filtered by status, up to *limit* entries."""
        from ..services.todo import TodoStatus
        st = TodoStatus[status.upper()] if status else None
        return self.todo.list(st, limit)

    def cancel_todo(self, todo_id: str) -> bool:
        """Cancel a todo entry; returns True on success."""
        return self.todo.cancel(todo_id)

    def todo_stats(self) -> dict:
        """Return todo table statistics."""
        return self.todo.stats()

    # ── External API ──

    def dispatch(self, card: TerminalCard) -> str:
        """Queue a card for execution; returns the card id."""
        with self._lock:
            self.add_todo(f"{card.action} {card.target}", priority=3)
            self.stdin.append(card)
            if self.status in (TerminalStatus.IDLE,):
                self.status = TerminalStatus.PROCESSING
        return card.card_id

    def wait_for_result(self, card_id: str, timeout: float = CARD_WAIT_TIMEOUT) -> CardResult | None:
        """Block until the card result is ready or *timeout* elapses."""
        event = threading.Event()
        with self._lock:
            if card_id in self._results:
                return self._results[card_id]
            self._pending[card_id] = event
        event.wait(timeout=timeout)
        with self._lock:
            return self._results.get(card_id)

    def read_stdout(self, clear: bool = True) -> list[CardResult]:
        """Read accumulated stdout results, optionally clearing them."""
        with self._lock:
            r = list(self.stdout)
            if clear:
                self.stdout.clear()
            return r

    def read_stderr(self, clear: bool = True) -> list[str]:
        """Read accumulated stderr messages, optionally clearing them."""
        with self._lock:
            r = list(self.stderr)
            if clear:
                self.stderr.clear()
            return r

    # ── Convention handler (persistent AgentLoop per convention) ──

    def _convention_handler(self, card: TerminalCard) -> CardResult:
        from ..agent._term_convention import convention_handler as _ch
        return _ch(self, card)

    # ── Direct message handler ──

    def _handle_direct(self, card: TerminalCard) -> CardResult:
        """Handle direct message via stdin queue. Runs AgentLoop, writes to Memory R2."""
        from ..agent.agent_loop import AgentLoop
        text = card.params.get("text", "")
        sender = card.params.get("sender", "shell")
        from l1.kernel.prompts import get_prompt as _get_prompt
        loop = AgentLoop(
            task=text, agent_id=self.agent_id,
            system=_get_prompt("agent_terminal.direct").format(
                agent_id=self.agent_id, role=self.role,
            ),
            cell_id=self.cell_id,
        )
        result = loop.run(max_steps=AGENT_LOOP_DEFAULT_STEPS, timeout=AGENT_LOOP_DEFAULT_TIMEOUT,
                          **_get_model_service().resolve_dict(_MODEL_SPEC))
        answer = result.get("answer", "")
        try:
            from ..memory.memory import get_memory
            get_memory().remember(
                agent_id=self.agent_id, entry_type="direct_message",
                content=f"{sender}: {text[:LOG_TRUNC_200]}\nAgent: {answer[:LOG_TRUNC_500]}",
                tags=["direct_session"], ring=2,
            )
        except Exception:
            logger.debug("agent_terminal: direct message remember failed")
        return CardResult(card_id=card.card_id, action="direct_message",
                          success=True, output=answer)

    def spawn_scout_async(self, template: str, scope: dict | None = None) -> dict:
        """Spawn a scout in the background; returns an ack with scout_id."""
        scout_id = f"async-{self.agent_id}-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        with self._lock:
            if self._async_scout_count >= self.max_scouts:
                return {"success": False, "error": f"max async scouts ({self.max_scouts})"}
            self._async_scout_count += 1
            self._async_pending.add(scout_id)
        threading.Thread(target=self._run_async_scout, args=(scout_id, template, scope or {}),
                         daemon=True).start()
        return {"success": True, "scout_id": scout_id, "async": True}

    def _run_async_scout(self, scout_id: str, template: str, scope: dict) -> None:
        try:
            result = self.scout_pool.commission(self.agent_id, template, scope)
        except Exception as e:
            result = {"success": False, "error": str(e)}
        with self._lock:
            self._async_scouts[scout_id] = result
            self._async_pending.discard(scout_id)
            ev = self._async_scout_events.pop(scout_id, None)
            if ev:
                ev.set()
            self._async_scout_count = max(0, self._async_scout_count - 1)

    def collect_scout(self, scout_id: str, timeout: float = SCOUT_COLLECT_TIMEOUT) -> dict:
        """Collect an async scout result, waiting up to *timeout* seconds."""
        event = threading.Event()
        with self._lock:
            if scout_id in self._async_scouts:
                return self._async_scouts.pop(scout_id)
            self._async_scout_events[scout_id] = event
        event.wait(timeout=timeout)
        with self._lock:
            return self._async_scouts.pop(scout_id, {"success": False, "error": "timeout"})

    def collect_all_scouts(self, timeout: float = SCOUT_COLLECT_TIMEOUT) -> list[dict]:
        """Collect all pending async scout results, waiting up to *timeout*."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if not self._async_pending:
                    return [self._async_scouts.pop(sid) for sid in list(self._async_scouts.keys())]
            time.sleep(POLL_INTERVAL_SLOW)
        with self._lock:
            ids = list(self._async_scouts.keys())
            results = [self._async_scouts.pop(sid) for sid in ids]
            self._async_pending.clear()
            return results

    def set_persistent_loop(self, enabled: bool = True) -> dict:
        """Enable or disable persistent AgentLoop mode.

        When enabled, the AgentTerminal reuses the same AgentLoop instance
        across multiple cards, preserving LLM conversational context.
        Call ``reset_persistent_loop()`` to force a fresh start.
        """
        self._persistent_loop = enabled
        logger.info("agent %s: persistent_loop=%s", self.agent_id, enabled)
        return {"success": True, "persistent_loop": enabled}

    def reset_persistent_loop(self) -> dict:
        """Force-reset the persistent AgentLoop, discarding accumulated context."""
        with self._active_loop_lock:
            if self._active_loop is not None:
                self._active_loop._context_trail = None
            self._active_loop = None
        logger.info("agent %s: persistent loop reset", self.agent_id)
        return {"success": True, "action": "persistent_loop_reset"}

    def set_card_timeout(self, timeout: float) -> dict:
        """Set per-card execution timeout in seconds (0 = disabled)."""
        self._card_timeout = timeout
        logger.info("agent %s: card_timeout=%.1fs", self.agent_id, timeout)
        return {"success": True, "card_timeout": timeout}

    def set_mode(self, mode: str) -> dict:
        """Set the loop mode; returns success or a validation error."""
        from l1.kernel.params.agent import TERMINAL_MODE_VALID
        valid = TERMINAL_MODE_VALID
        if mode not in valid:
            return {"success": False, "error": f"mode must be one of {valid}"}
        self._loop_mode = mode
        return {"success": True, "mode": mode}

    def pause(self) -> dict:
        """Pause the terminal; blocks card processing."""
        self._paused = True
        self.status = TerminalStatus.BLOCKED
        return {"success": True, "paused": True}

    def resume(self) -> dict:
        """Resume the terminal after a pause."""
        self._paused = False
        self.status = TerminalStatus.IDLE
        return {"success": True, "resumed": True}

    def shutdown(self) -> dict:
        """Stop the terminal, join workers, and emit session_end hooks."""
        self._running = False
        for w in self._workers:
            w.join(timeout=AGENT_TERMINAL_WORKER_JOIN_TIMEOUT)
        # Clean up any orphaned convention loops
        for conv_id, session in list(self._convention_loops.items()):
            loop_obj = session.get("loop")
            if loop_obj:
                try:
                    loop_obj.task = "Convention closed by agent shutdown."
                except Exception:
                    logger.debug("agent_terminal: convention loop cleanup failed")
        self._convention_loops.clear()
        self._results.clear()
        self.status = TerminalStatus.STOPPED
        # Lifecycle hook chain: session_end (agent session terminated)
        try:
            from l3.services.hook import get_hook_chain as _get_hc
            _get_hc().session_end({"agent_id": self.agent_id,
                                   "cards_processed": self._cards_processed,
                                   "status": "stopped"})
        except Exception as e:
            logger.debug("agent_terminal: session_end hook emit failed: %s", e)
        return {"success": True, "agent_id": self.agent_id, "cards_processed": self._cards_processed}

    def session_reachable(self) -> dict:
        """Check if this agent can accept a direct message (via stdin queue)."""
        if not self._running:
            return {"reachable": False, "reason": "not_running"}
        if self.status in (TerminalStatus.CRASHED, TerminalStatus.STOPPED):
            return {"reachable": False, "reason": self.status.name.lower()}
        return {"reachable": True, "reason": "ready",
                "queue_depth": len(self.stdin) if hasattr(self, 'stdin') else 0}

    def send_direct_message(self, text: str, sender: str = "shell") -> dict:
        """Queue a direct message as a TerminalCard via stdin."""
        from ..agent._term_types import CardMode as TermCardMode
        from ..agent._term_types import TerminalCard
        card = TerminalCard(
            mode=TermCardMode.EXECUTE,
            action="direct_message",
            target=f"direct-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}",
            params={"text": text, "sender": sender},
            sender=sender,
        )
        cid = self.dispatch(card)
        return {"success": True, "card_id": cid}

    def status_report(self) -> dict:
        """Return a snapshot of terminal status and counters."""
        with self._lock:
            return {
                "agent_id": self.agent_id, "role": self.role, "ring": self.ring,
                "status": self.status.name, "cards_processed": self._cards_processed,
                "alive": self._running, "active_cards": self._active_cards,
                "mode": self._loop_mode, "loop_state": self._loop_state,
                "paused": self._paused, "current_card": self._current_card,
            }


# ── Factory ──

_terminals: dict[str, AgentTerminal] = {}
_terminals_lock = threading.Lock()


def get_terminal(agent_id: str, role: str = "",
                 territory: list[str] | None = None,
                 cell_id: str = "") -> AgentTerminal:
    """Return the shared terminal for *agent_id*, creating it on first use."""
    with _terminals_lock:
        if agent_id not in _terminals:
            _terminals[agent_id] = AgentTerminal(agent_id, role, territory, cell_id)
    return _terminals[agent_id]


def get_terminals() -> dict[str, AgentTerminal]:
    """Return a copy of all registered terminals keyed by agent id."""
    with _terminals_lock:
        return dict(_terminals)


def reset_terminals() -> None:
    """Shut down and clear all registered terminals."""
    with _terminals_lock:
        for t in list(_terminals.values()):
            t.shutdown()
        _terminals.clear()
