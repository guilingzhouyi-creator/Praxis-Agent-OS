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

from l1.kernel import get_event_bus, emit_signal
from l1.kernel.constitution import get_constitution
from l1.kernel.allocator import get_allocator
from l1.kernel.params.agent import (
    DEFAULT_AGENT_CONFIGS,
    AGENT_CLEARANCE,
    AGENT_TERMINAL_MAX_SCOUTS,
    AGENT_TERMINAL_WORKER_JOIN_TIMEOUT,
    AGENT_TERMINAL_STDIN_MAX,
    AGENT_TERMINAL_STDOUT_MAX,
    AGENT_TERMINAL_STDERR_MAX,
    AGENT_TERMINAL_RESULTS_MAX,
    TERMINAL_MAX_WORKERS,
    AGENT_LOOP_DEFAULT_STEPS,
    AGENT_LOOP_DEFAULT_TIMEOUT,
    EVENT_TASK_ASSIGN,
    EVENT_REVIEW_REQUESTED,
)
from l1.kernel.params.system import POLL_INTERVAL_FAST, POLL_INTERVAL_SLOW, POLL_INTERVAL_PAUSED
from ..memory.cache import get_file_cache, get_context_register
from ..agent.scout import get_pool as get_scout_pool
from ..agent._term_types import TerminalStatus, CardMode, TerminalCard, CardResult
from ..agent._term_handlers import get_action_handler
from ..agent._term_lifecycle import run_cache_keepalive
from l3.services.model_service import get_service as _get_model_service
from ..tool_system.tool_pipeline import get_pipeline
from ..memory.context import get_context as get_context_manager

logger = logging.getLogger(__name__)

_PROJECT_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))

# ── Cache keepalive ──
from l1.kernel.params.agent import CACHE_KEEPALIVE_INTERVAL, CACHE_KEEPALIVE_PROMPT

_MODEL_SPEC = "peer_agent"


class AgentTerminal:
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

    def set_tool_registry(self, registry: dict[str, Any]) -> None:
        self._tool_registry = registry

    def set_watchdog_pet(self, fn: Any) -> None:
        """Set the watchdog pet callback, called after each card completes."""
        self._watchdog_pet = fn

    def list_tools(self) -> list[dict]:
        if not self._tool_registry:
            return []
        from l3.tool_system.tool_spec import is_muted as _is_muted
        from l1.kernel.params.kernel import RING_NUM_MAP as _RNM
        tools = []
        for name, spec in self._tool_registry.items():
            sr = getattr(spec, "ring", RING_1)
            if self.ring >= _RNM.get(sr, 1) and not _is_muted(name):
                tools.append({"name": name, "ring": sr,
                              "danger": getattr(spec, "danger", 0),
                              "description": getattr(spec, "description", "")[:80]})
        return sorted(tools, key=lambda t: (t["ring"], t["name"]))

    def boot(self) -> dict:
        """Boot the agent terminal: constitution check → warm memory → start workers."""
        phases = []
        cc = self.constitution.is_allowed("boot", self.agent_id, target=self.role, territory=self.territory)
        phases.append({"phase": "constitution_check", **cc})
        if not cc.get("allowed", True):
            self.status = TerminalStatus.CRASHED
            self._boot_result = {"success": False, "error": "constitution blocked boot", "phases": phases}
            return self._boot_result
        try:
            from l3.memory.memory import get_memory
            get_memory().remember(agent_id=self.agent_id, cell_id=self.cell_id, entry_type="boot",
                content=f"boot: role={self.role} territory={self.territory}", tags=["boot"], ring=1)
            phases.append({"phase": "memory_warm", "success": True})
        except Exception as e:
            phases.append({"phase": "memory_warm", "success": False, "error": str(e)})
        try:
            from ..memory.context_pool import register as _register_cp
            _register_cp(agent_id=self.agent_id, cell_id=self.cell_id, max_tokens=4096)
            phases.append({"phase": "context_pool_register", "success": True})
        except Exception as e:
            phases.append({"phase": "context_pool_register", "success": False, "error": str(e)})

        # ── Full manual loading on first boot ──
        try:
            from l1.kernel.skill import get_skill_manager
            sm = get_skill_manager()
            all_s = sm.list(limit=20)
            if all_s:
                parts = ["=== Agent Manual (boot) ==="]
                for s in all_s:
                    n = getattr(s, 'name', '?')
                    d = getattr(s, 'description', '')[:120]
                    p = getattr(s, 'prompt', '')[:300]
                    parts.append(f"[{n}] {d}\n{p}")
                from ..memory.context import get_context as _gc
                _gc().store(key=f"manual:{self.agent_id}", value="\n\n".join(parts),
                            agent_id=self.agent_id, entry_type="manual")
                phases.append({"phase": "manual_loaded", "count": len(all_s)})
                logger.info("agent %s: loaded %d skills", self.agent_id, len(all_s))
        except Exception as e:
            phases.append({"phase": "manual_loaded", "error": str(e)})

        # ── Persistence session — load snapshot / init hooks ──
        try:
            from l3.agent.agent_persist import SnapshotHook, load_snapshot
            self._snapshot_hook = SnapshotHook(self.agent_id)
            snapshot = load_snapshot(self.agent_id)
            if snapshot:
                phases.append({"phase": "persist_restore", "status": snapshot.get("status")})
            else:
                phases.append({"phase": "persist_restore", "note": "no snapshot"})
            logger.info("agent %s: persist ready", self.agent_id)
        except Exception as e:
            self._snapshot_hook = None
            phases.append({"phase": "persist_init", "error": str(e)})

        from l1.kernel.params.agent import EVENT_TASK_ASSIGN
        emit_signal(EVENT_TASK_ASSIGN, sender=self.agent_id, target="cell",
                     data={"event": "agent_boot", "role": self.role, "ring": self.ring})
        self._running = True
        for i in range(self._max_workers):
            w = threading.Thread(target=self._worker, daemon=True, name=f"term-{self.agent_id}-w{i}")
            w.start()
            self._workers.append(w)
        self.status = TerminalStatus.IDLE
        self._boot_result = {"success": True, "phases": phases}

        kt = threading.Thread(target=run_cache_keepalive, args=(self,), daemon=True,
                              name=f"keepalive-{self.agent_id}")
        kt.start()
        return self._boot_result

    # ── Worker / dispatch ──

    def _worker(self) -> None:
        from l3.scheduler.scheduler import get_time_scheduler as _get_ts
        while self._running:
            if self._paused:
                time.sleep(POLL_INTERVAL_PAUSED)
                continue
            card = None
            with self._lock:
                if self.stdin:
                    card = self.stdin.popleft()
                    self._active_cards += 1
            if card is None:
                time.sleep(POLL_INTERVAL_FAST)
                continue
            with self._lock:
                self.status = TerminalStatus.PROCESSING if self._active_cards > 0 else TerminalStatus.IDLE
                self._current_card = card.card_id
                self._loop_state = f"processing {card.action} on {card.target[:40]}"
            from l3.error_bus import error_boundary, capture
            with error_boundary("worker card failed", component="services", agent_id=self.agent_id):
                result = self._process_card(card)
            if result is None:
                result = CardResult(card_id=card.card_id, action=card.action, success=False, error="unknown")
            with self._lock:
                from l1.kernel.params.agent import TERMINAL_STATE_DEFAULT
                self._loop_state = TERMINAL_STATE_DEFAULT
                self._current_card = ""
            result.elapsed = time.time() - card.timestamp
            try:
                tick_r = _get_ts().tick(self.agent_id, result.elapsed)
                if tick_r.get("status") in ("preempt", "timeout"):
                    logger.warning("agent %s preempted: %.1fs used (quantum=%.1f)",
                                   self.agent_id, tick_r.get("used", 0), tick_r.get("quantum", 0))
            except Exception as e:
                logger.warning("services/agent_terminal: %s", e)
            with self._lock:
                self._cards_processed += 1
                self._cards_since_pressure_check += 1
                self._active_cards -= 1
                self.stdout.append(result)
                self._results[card.card_id] = result
                # LRU eviction: keep newest results, discard oldest
                self._results.move_to_end(card.card_id)
                while len(self._results) > AGENT_TERMINAL_RESULTS_MAX:
                    self._results.popitem(last=False)
                # Periodic memory pressure check (every 10 cards, non-think actions)
                if self._cards_since_pressure_check >= 10 and card.action != "think":
                    self._cards_since_pressure_check = 0
                    try:
                        from ..memory.memory import get_memory
                        p = get_memory().pressure(self.agent_id)
                        if p.get("level") == "high":
                            get_memory().stub_compact(self.agent_id)
                            logger.info("periodic compact for %s: pressure=%s",
                                        self.agent_id, p.get("level"))
                    except Exception:
                        pass
                ev = self._pending.pop(card.card_id, None)
                if ev:
                    ev.set()
                if self._active_cards <= 0:
                    self.status = TerminalStatus.IDLE
                # Watchdog pet after each completed card
                if self._watchdog_pet:
                    try:
                        self._watchdog_pet(self.agent_id)
                    except Exception as e:
                        logger.warning("watchdog pet failed: %s", e)
        with self._lock:
            self._active_cards = 0
            self.status = TerminalStatus.IDLE

    def _process_card(self, card: TerminalCard) -> CardResult:
        if card.action == "convention":
            return self._convention_handler(card)
        if card.action == "direct_message":
            return self._handle_direct(card)
        if card.mode == CardMode.ISSUE:
            return self._issue_card(card)
        return self._execute_card(card)

    def _execute_card(self, card: TerminalCard) -> CardResult:
        phases = ["start"]
        result_output = ""
        result_findings: list[dict] = []

        # Begin context cycle: load working memory into register
        ctx = get_context_manager()
        ctx.begin(self.agent_id, task=getattr(card, 'intent', '') or card.action)
        phases.append("context_begin")

        # Build toolkit args from card params
        args = dict(card.params or {})
        if card.target:
            args.setdefault("path", card.target)
            args.setdefault("target", card.target)

        # Resolve handler via registration API (func registry → method registry → legacy _HANDLER_MAP)
        def _handler_executor(tool_name: str, tool_args: dict, agent_id: str) -> dict:
            nonlocal result_output, result_findings, phases
            h = get_action_handler(self, tool_name)
            if h:
                output, findings, ok = h(self, card, phases)
                result_output = output or str(tool_args)
                result_findings = findings or []
                # Inject scout findings into context register
                if findings:
                    from l1.kernel.params.agent import TERMINAL_SCOUT_FINDINGS_LIMIT
                    for f in findings[:TERMINAL_SCOUT_FINDINGS_LIMIT]:
                        ctx.push("observation", str(f)[:500], source="scout")
                return {"success": ok, "output": result_output, "findings": result_findings}
            phases.append(f"execute:{tool_name}")
            result_output = f"executed {tool_name} on {card.target}"
            return {"success": True, "output": result_output}

        pipeline = get_pipeline()

        # ── Batch execution: multiple tools in parallel (Agent internal parallelism) ──
        if card.batch:
            import concurrent.futures
            batch_results: list[dict] = []
            batch_errors: list[str] = []

            def _exec_one(batch_item: dict) -> dict:
                bn = batch_item.get("name", "")
                ba = dict(batch_item.get("input", {}))
                ba.setdefault("path", ba.get("path", ba.get("target", card.target or "")))
                ba.setdefault("target", ba.get("target", ba.get("path", card.target or "")))
                return pipeline.execute(tool_name=bn, agent_id=self.agent_id,
                                        args=ba, _executor=_handler_executor)

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(card.batch)) as ex:
                futures = {ex.submit(_exec_one, item): item for item in card.batch}
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        r = fut.result()
                        batch_results.append(r)
                        if not r.get("success"):
                            batch_errors.append(r.get("error", "batch item failed"))
                    except Exception as e:
                        batch_errors.append(str(e))

            phases.append(f"batch_done:{len(batch_results)}")
            success = len(batch_errors) == 0
            pr = {"success": success, "error": "; ".join(batch_errors) if batch_errors else "",
                  "steps": phases, "batch_results": batch_results}
        else:
            # ── Single tool execution (original path) ──
            pr = pipeline.execute(
                tool_name=card.action,
                agent_id=self.agent_id,
                args=args,
                _executor=_handler_executor,
            )

        phases.extend(pr.get("steps", []))
        if not pr.get("success"):
            ctx.end(success=False, summary=pr.get("error", "pipeline rejected"))
            return CardResult(card_id=card.card_id, action=card.action,
                              success=False, error=pr.get("error", "pipeline rejected"),
                              output=result_output, findings=result_findings, phase=phases)
        try:
            from l3.memory.memory import get_memory
            mem = get_memory()
            mem.remember(agent_id=self.agent_id, entry_type="card_result",
                content=f"{card.action} {card.target}: {result_output[:200]}",
                tags=[card.action], ring=1)
            phases.append("memory_store")

            # ── Auto-compact on high memory pressure after think actions ──
            if card.action == "think":
                p = mem.pressure(self.agent_id)
                if p["level"] == "high":
                    from l1.kernel.params.agent import TERMINAL_CONTEXT_RECENT
                    snapshot = list(self.context.recent(TERMINAL_CONTEXT_RECENT))
                    compact_r = mem.compact(self.agent_id)
                    for item in snapshot:
                        self.context.store(
                            key=f"restored:{item.get('key', '')}",
                            value=item.get("value", ""),
                            agent_id=self.agent_id,
                            entry_type="restored",
                        )
                    phases.append(f"compact:{compact_r.get('merged', 0)}")
                    logger.info("auto-compact for %s: merged=%d tokens=%d",
                                self.agent_id, compact_r.get("merged", 0),
                                compact_r.get("saved_tokens", 0))
        except Exception:
            phases.append("memory_store:skip")
        try:
            from l1.kernel import record_audit
            record_audit(f"card.{card.action}", self.agent_id, success=True,
                         detail=f"{card.target}:{result_output[:60]}")
        except Exception as e:
            logger.warning("agent terminal keepalive: %s", e)

        if card.action in ("write_file",) and result_output:
            try:
                emit_signal(EVENT_REVIEW_REQUESTED, sender=self.agent_id,
                            target=self.cell_id or "cell",
                            data={"type": "cross_review", "action": card.action,
                                  "target": card.target, "created_by": self.agent_id,
                                  "output_snippet": result_output[:200]})
                phases.append("cross_review→signal")
            except Exception:
                phases.append("cross_review:skip")

        ctx.end(success=True, summary=f"{card.action} {card.target}: {result_output[:200]}")
        phases.append("context_end")

        return CardResult(card_id=card.card_id, action=card.action,
                          success=True, output=result_output, findings=result_findings, phase=phases)

    def _issue_card(self, card: TerminalCard) -> CardResult:
        emit_signal(EVENT_REVIEW_REQUESTED, sender=self.agent_id, target="cell",
                     data={"type": "issue", "action": card.action, "target": card.target,
                           "params": card.params, "card_id": card.card_id, "proposed_by": self.agent_id})
        return CardResult(card_id=card.card_id, action=card.action,
                          success=True, output=f"issue created: {card.action}", phase=["issue"])

    # ── Todo Table API ──

    def add_todo(self, intent: str, domain: str = "", priority: int = 5,
                 depends_on: list[str] | None = None) -> str:
        tid = self.todo.add(intent, domain, priority, depends_on)
        with self._lock:
            if self.status in (TerminalStatus.IDLE,):
                self.status = TerminalStatus.PROCESSING
        return tid

    def list_todos(self, status: str = "", limit: int = 20) -> list[dict]:
        from ..services.todo import TodoStatus
        st = TodoStatus[status.upper()] if status else None
        return self.todo.list(st, limit)

    def cancel_todo(self, todo_id: str) -> bool:
        return self.todo.cancel(todo_id)

    def todo_stats(self) -> dict:
        return self.todo.stats()

    # ── External API ──

    def dispatch(self, card: TerminalCard) -> str:
        with self._lock:
            self.add_todo(f"{card.action} {card.target}", priority=3)
            self.stdin.append(card)
            if self.status in (TerminalStatus.IDLE,):
                self.status = TerminalStatus.PROCESSING
        return card.card_id

    def wait_for_result(self, card_id: str, timeout: float = 30.0) -> CardResult | None:
        event = threading.Event()
        with self._lock:
            if card_id in self._results:
                return self._results[card_id]
            self._pending[card_id] = event
        event.wait(timeout=timeout)
        with self._lock:
            return self._results.get(card_id)

    def read_stdout(self, clear: bool = True) -> list[CardResult]:
        with self._lock:
            r = list(self.stdout)
            if clear:
                self.stdout.clear()
            return r

    def read_stderr(self, clear: bool = True) -> list[str]:
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
                content=f"{sender}: {text[:200]}\nAgent: {answer[:500]}",
                tags=["direct_session"], ring=2,
            )
        except Exception:
            pass
        return CardResult(card_id=card.card_id, action="direct_message",
                          success=True, output=answer)

    def spawn_scout_async(self, template: str, scope: dict | None = None) -> dict:
        scout_id = f"async-{self.agent_id}-{uuid.uuid4().hex[:8]}"
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

    def collect_scout(self, scout_id: str, timeout: float = 310.0) -> dict:
        event = threading.Event()
        with self._lock:
            if scout_id in self._async_scouts:
                return self._async_scouts.pop(scout_id)
            self._async_scout_events[scout_id] = event
        event.wait(timeout=timeout)
        with self._lock:
            return self._async_scouts.pop(scout_id, {"success": False, "error": "timeout"})

    def collect_all_scouts(self, timeout: float = 310.0) -> list[dict]:
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

    def set_mode(self, mode: str) -> dict:
        from l1.kernel.params.agent import TERMINAL_MODE_VALID
        valid = TERMINAL_MODE_VALID
        if mode not in valid:
            return {"success": False, "error": f"mode must be one of {valid}"}
        self._loop_mode = mode
        return {"success": True, "mode": mode}

    def pause(self) -> dict:
        self._paused = True
        self.status = TerminalStatus.BLOCKED
        return {"success": True, "paused": True}

    def resume(self) -> dict:
        self._paused = False
        self.status = TerminalStatus.IDLE
        return {"success": True, "resumed": True}

    def shutdown(self) -> dict:
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
                    pass
        self._convention_loops.clear()
        self._results.clear()
        self.status = TerminalStatus.STOPPED
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
        from ..agent._term_types import TerminalCard, CardMode as TermCardMode
        card = TerminalCard(
            mode=TermCardMode.EXECUTE,
            action="direct_message",
            target=f"direct-{uuid.uuid4().hex[:8]}",
            params={"text": text, "sender": sender},
            sender=sender,
        )
        cid = self.dispatch(card)
        return {"success": True, "card_id": cid}

    def status_report(self) -> dict:
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
    with _terminals_lock:
        if agent_id not in _terminals:
            _terminals[agent_id] = AgentTerminal(agent_id, role, territory, cell_id)
    return _terminals[agent_id]


def get_terminals() -> dict[str, AgentTerminal]:
    with _terminals_lock:
        return dict(_terminals)


def reset_terminals() -> None:
    with _terminals_lock:
        for t in list(_terminals.values()):
            t.shutdown()
        _terminals.clear()
