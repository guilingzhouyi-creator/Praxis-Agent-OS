"""ExecutionPlan — card decomposition and step-by-step execution engine.

Flow:
  Card → ExecutionPlan → PlanSteps → AgentTerminal dispatch → results

A Card is decomposed into an ordered list of PlanSteps.
Each PlanStep is routed to the correct AgentTerminal.
Steps can be sequential or parallel within a phase.
Results from earlier steps feed into later steps via shared context.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.system import LOG_TRUNC_80, MEMORY_PRESSURE_INTERVAL

from .execution_run import _execute_agent as _run_execute_agent
from .execution_run import _execute_step, _run_phase
from .execution_run import execute as _execute
from .models import Card, CardMode
from .plan_step_types import PlanStep, StepState

SANDBOX_EXEC_TIMEOUT = get_tool_config("exec_timeout", 300)

logger = logging.getLogger(__name__)

# ── Action scope classification constants ──
_ACTION_READ_KEYWORDS: tuple[str, ...] = ("read", "inspect", "scout")
_ACTION_WRITE_KEYWORDS: tuple[str, ...] = ("write", "edit", "create", "replace")
_ACTION_SHELL_KEYWORDS: tuple[str, ...] = ("run", "execute", "build", "test")
_ACTION_THINK_KEYWORD: str = "think"
# Fallback tool sets when ToolConfig is unavailable
_FALLBACK_READ_TOOLS: set[str] = {"read_file", "grep_search"}
_FALLBACK_SHELL_TOOLS: set[str] = {"run_shell", "execute_command", "bash"}


class ExecutionPlan:
    """A decomposed Card ready for execution.

    Holds the ordered list of PlanSteps, tracks progress,
    and manages step dependencies.

    Usage:
      plan = ExecutionPlan(card, agent_map={
          "scout":    "scout_pool",
          "http":     "alice",
          "business": "bob",
          "security": "mallory",
      })
      plan.execute()   # blocking, runs all steps
      print(plan.summary())
    """

    def __init__(self, card: Card, agent_map: dict[str, str], user_id: str = ""):
        self.card: Any = card  # may be CardUnified (new model) or legacy Card
        self.plan_id = card.id  # alias for ExecutionEngine compatibility
        self.agent_map = agent_map
        self.user_id = user_id
        self.steps: list[PlanStep] = []
        self._step_index: dict[str, PlanStep] = {}
        self._context: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._started_at = 0.0
        self._completed_at = 0.0
        self._cancelled = False
        self._approval_requests: list = []
        self._turn_log: list[dict] = []
        self._last_compact: float = 0.0
        # Detect if card is CardUnified (new model) or old Card
        self._is_unified = type(card).__name__ == "CardUnified"
        # Dynamic step budget via ScopeScheduler
        if self._is_unified:
            n_phases = len(card.phases)
            n_steps = sum(len(getattr(p, "tasks", [])) for p in card.phases)
        else:
            n_phases = len(card.phases)
            n_steps = sum(len(p.steps) for p in card.phases)
        from l3.scheduler.scheduler_scope import get_scope_scheduler

        self._step_budget = get_scope_scheduler().calc_step_budget(
            n_phases,
            n_steps,
        )

        self._decompose()

    # ── Card-model normalizers (bridge old Card ↔ CardUnified) ──

    def _card_intent(self) -> str:
        return self.card.summary.title if self._is_unified else self.card.intent

    def _card_domain(self) -> str:
        if self._is_unified:
            return self.card.summary.columns.get("domain", self.card.nature)
        return self.card.domain

    def _card_mode(self) -> str:
        """Return a normalized mode string: 'execute' | 'issue' | 'parallel_all'."""
        if self._is_unified:
            return self.card.nature
        mode = self.card.mode
        return {CardMode.EXECUTE: "execution", CardMode.ISSUE: "issue", CardMode.PARALLEL_ALL: "parallel_all"}.get(
            mode, "execution"
        )

    def _phase_mode(self, phase) -> str:
        """Return normalized phase mode string: 'sequential' | 'parallel'."""
        if self._is_unified:
            from .card_unified import PhaseMode as NewPM

            return "parallel" if phase.mode == NewPM.MULTI else "sequential"
        from .models import PhaseMode as OldPM

        return "parallel" if phase.mode == OldPM.PARALLEL else "sequential"

    def _card_phases_items(self, phase):
        """Iterate items (steps/tasks) within a phase."""
        return phase.tasks if self._is_unified else phase.steps

    def _decompose(self) -> None:
        """Convert Card phases/steps into ordered PlanSteps."""
        step_id = 0
        for phase in self.card.phases:
            # CardUnified: phase.tasks (CardTask)
            # Old Card:    phase.steps (Step)
            items = phase.tasks if self._is_unified else phase.steps
            for item in items:
                aid = self._resolve_agent(item.agent)
                ps = PlanStep(
                    step_id=f"s{step_id:03d}",
                    action=item.action,
                    target=item.target,
                    params=item.params if self._is_unified else item.params,
                    agent=aid,
                    phase=phase.name,
                    depends_on=list(item.depends_on) if not self._is_unified else [],
                )
                self.steps.append(ps)
                self._step_index[ps.step_id] = ps
                step_id += 1

    def _resolve_agent(self, role: str) -> str:
        """Map a role name to a specific agent_id in this Cell."""
        if role == "scout":
            return "scout_pool"
        return self.agent_map.get(role, role)

    def _save_step_checkpoint(self, ps: PlanStep) -> None:
        """Save checkpoint before executing a step."""
        try:
            from l3.services.fault_tolerance import get_service

            ft = get_service()
            ft.save_checkpoint(
                agent_id=ps.agent,
                task_id=f"{self.card.id}:{ps.step_id}",
                progress={"phase": ps.phase, "step": ps.step_id, "action": ps.action},
            )
        except Exception as e:
            logger.warning("checkpoint save failed: %s", e)

    def _mark_phase_checkpoint_done(self, agent_ids: set[str]) -> None:
        """Mark checkpoint done for completed agents."""
        try:
            from l3.services.fault_tolerance import get_service

            ft = get_service()
            for aid in agent_ids:
                try:
                    ft.mark_done(aid)
                except Exception as e:
                    logger.warning("checkpoint mark_done failed for %s: %s", aid, e)
        except Exception as e:
            logger.warning("checkpoint service unavailable: %s", e)

    def _run_phase(
        self, phase_name: str, phase_steps: list[PlanStep], mode: str, aggregated: dict, timeout: float
    ) -> None:
        """Execute all steps in a single phase. Delegates to execution_run.py."""
        return _run_phase(self, phase_name, phase_steps, mode, aggregated, timeout)

    def execute(self, timeout: float = SANDBOX_EXEC_TIMEOUT) -> dict:
        """Execute all steps. Delegates to execution_run.py."""
        return _execute(self, timeout=timeout)

    def _check_memory_and_compact(self, aggregated: dict) -> None:
        """Check memory pressure; if high, snapshot context → compact → resume.

        Called between sequential phases.  Never raises.
        """
        if time.time() - self._last_compact < MEMORY_PRESSURE_INTERVAL:
            return
        try:
            from .memory.memory import get_memory

            mem = get_memory()
            p = mem.pressure()
            if p["level"] != "high":
                return

            # 1. Snapshot: save context register snapshots for all agents
            from l3.agent_terminal import get_terminals

            snapshots = {}
            for aid, term in get_terminals().items():
                try:
                    snapshots[aid] = {
                        "context": term.context.recent(20),
                        "todo": term.todo.list(limit=20) if hasattr(term, "todo") else [],
                    }
                except Exception as e:
                    logger.warning("snapshot failed for %s: %s", aid, e)
                    snapshots[aid] = {}

            # 2. Compact: merge low-importance entries
            compact_r = mem.compact()
            self._last_compact = time.time()

            # 3. Resume: reload snapshots into context register
            for aid, snapshot in snapshots.items():
                try:
                    term = get_terminals().get(aid)
                    if term and snapshot.get("context"):
                        for item in snapshot["context"]:
                            term.context.store(
                                key=f"restored:{item.get('key', '')}",
                                value=item.get("value", ""),
                                agent_id=aid,
                                entry_type="restored",
                            )
                except Exception as e:
                    logger.warning("snapshot restore failed: %s", e)

            aggregated.setdefault("_memory_compactions", []).append(
                {
                    "timestamp": time.time(),
                    "pressure": p,
                    "merged": compact_r.get("merged", 0),
                    "saved_tokens": compact_r.get("saved_tokens", 0),
                }
            )
            logger.info(
                "memory compact between phases: merged=%d saved=%d tokens",
                compact_r.get("merged", 0),
                compact_r.get("saved_tokens", 0),
            )
        except Exception as e:
            logger.warning("memory compaction skipped: %s", e)

    def _execute_step(self, ps: PlanStep, timeout: float) -> dict:
        """Execute a single plan step. Delegates to execution_run.py."""
        return _execute_step(self, ps, timeout)

    def _execute_scout_verify(self, ps: PlanStep, spec: dict, phase: str) -> dict:
        from .card.execution_verify import execute_scout_verify as _verify

        return _verify(ps, spec, phase)

    def _diff_verify(self, before: dict, after: dict) -> dict:
        from .card.execution_verify import diff_verify as _diff

        return _diff(before, after)

    def _execute_scout(self, ps: PlanStep) -> dict:
        from .card.execution_verify import execute_scout as _scout

        return _scout(ps)

    def _execute_agent(self, ps: PlanStep, timeout: float) -> dict:
        """Execute a step on an AgentTerminal. Delegates to execution_run.py."""
        return _run_execute_agent(self, ps, ps.agent, timeout)

    @staticmethod
    def _derive_action_scope(action: str) -> list[str]:
        """Derive allowed tool names from a step action.

        read-only actions → only read tools
        write actions     → only write tools
        shell actions     → only shell tools
        think actions     → all tools (general purpose)
        """
        try:
            from l1.kernel.params.kernel import RING_1

            from .tool_system.tool_config import ToolConfig as ToolConfigCls

            read_tools = {t.name for t in ToolConfigCls.by_ring(RING_1)}
            write_tools = ToolConfigCls.write_tool_names()
            shell_tools = ToolConfigCls.terminal_tool_names()
        except Exception:
            read_tools = _FALLBACK_READ_TOOLS
            write_tools = set()
            shell_tools = _FALLBACK_SHELL_TOOLS
        all_tools = read_tools | write_tools | shell_tools
        action_lower = action.lower()
        if action_lower in read_tools or action_lower in _ACTION_READ_KEYWORDS:
            return sorted(read_tools)
        if action_lower in write_tools or action_lower in _ACTION_WRITE_KEYWORDS:
            return sorted(write_tools)
        if action_lower in shell_tools or action_lower in _ACTION_SHELL_KEYWORDS:
            return sorted(shell_tools)
        if action_lower == _ACTION_THINK_KEYWORD:
            return sorted(all_tools)
        return sorted(all_tools)  # unknown action: full access (conservative)

    def cancel(self) -> None:
        """Mark the plan as cancelled."""
        self._cancelled = True

    def progress(self) -> dict:
        """Return execution progress counters and percentage."""
        done = sum(1 for s in self.steps if s.state == StepState.DONE)
        failed = sum(1 for s in self.steps if s.state == StepState.FAILED)
        running = sum(1 for s in self.steps if s.state == StepState.RUNNING)
        return {
            "total": len(self.steps),
            "done": done,
            "failed": failed,
            "running": running,
            "pct": round((done + failed) / max(len(self.steps), 1) * 100, 1),
            "elapsed": round(time.time() - self._started_at, 1) if self._started_at else 0,
        }

    def summary(self) -> dict:
        """Return a summary of the plan and its progress."""
        return {
            "card_id": self.card.id,
            "intent": self._card_intent()[:LOG_TRUNC_80],
            "domain": self._card_domain(),
            "mode": self._card_mode(),
            "total_steps": len(self.steps),
            **self.progress(),
            "agent_map": self.agent_map,
        }
