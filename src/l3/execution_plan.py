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
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel.params.agent import AGENT_LOOP_DEFAULT_TIMEOUT, EVENT_REVIEW_REQUESTED
from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from .card import Card, CardMode, PhaseMode, Step
from .agent_terminal import AgentTerminal, TerminalCard, TerminalStatus, get_terminal, get_terminals, CardMode as TermCardMode
from .plan_step_types import StepState, PlanStep

logger = logging.getLogger(__name__)


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
        self.card = card
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
        # Detect if card is CardUnified (new model) or old Card
        self._is_unified = type(card).__name__ == "CardUnified"
        # Dynamic step budget via ScopeScheduler
        if self._is_unified:
            n_phases = len(card.phases)
            n_steps = sum(len(p.tasks) for p in card.phases)
        else:
            n_phases = len(card.phases)
            n_steps = sum(len(p.steps) for p in card.phases)
        from .scheduler_scope import get_scope_scheduler
        self._step_budget = get_scope_scheduler().calc_step_budget(
            n_phases, n_steps,
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
        from .card import CardMode
        return {CardMode.EXECUTE: "execution", CardMode.ISSUE: "issue",
                CardMode.PARALLEL_ALL: "parallel_all"}.get(mode, "execution")

    def _phase_mode(self, phase) -> str:
        """Return normalized phase mode string: 'sequential' | 'parallel'."""
        if self._is_unified:
            from .card_unified import PhaseMode as NewPM
            return "parallel" if phase.mode == NewPM.MULTI else "sequential"
        from .card import PhaseMode as OldPM
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
            from .fault_tolerance import get_service
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
            from .fault_tolerance import get_service
            ft = get_service()
            for aid in agent_ids:
                try:
                    ft.mark_done(aid)
                except Exception as e:
                    logger.warning("checkpoint mark_done failed for %s: %s", aid, e)
        except Exception as e:
            logger.warning("checkpoint service unavailable: %s", e)

    def _run_phase(self, phase_name: str, phase_steps: list[PlanStep],
                   mode: str, aggregated: dict, timeout: float) -> None:
        """Execute all steps in a single phase. Modifies aggregated in place.

        *mode* is a string: ``"sequential"`` or ``"parallel"``.
        """
        involved_agents: set[str] = set()
        if mode == "sequential":
            for ps in phase_steps:
                if self._cancelled:
                    return
                involved_agents.add(ps.agent)
                self._save_step_checkpoint(ps)
                r = self._execute_step(ps, timeout)
                aggregated["steps"].append(r)
                if not r["success"]:
                    aggregated["success"] = False
                    aggregated["error"] = r.get("error", "")
                    break
        elif mode == "parallel":
            # Group steps by agent → same-agent steps get batch dispatched
            from collections import defaultdict
            agent_groups: dict[str, list[dict]] = defaultdict(list)
            for ps in phase_steps:
                agent_groups[ps.agent].append({
                    "name": ps.action, "input": {"path": ps.target, **ps.params}
                })

            threads = []
            results = [None] * len(phase_steps)
            result_idx = 0

            def _run_single(i, ps):
                involved_agents.add(ps.agent)
                self._save_step_checkpoint(ps)
                results[i] = self._execute_step(ps, timeout)

            def _run_batch(agent: str, batch_items: list[dict], start_idx: int):
                involved_agents.add(agent)
                from ._term_types import TerminalCard as _BatchCard
                from .agent_terminal import get_terminal
                try:
                    term = get_terminal(agent)
                    bc = _BatchCard(action="batch", target=phase_steps[start_idx].target or "",
                                    batch=batch_items)
                    term.dispatch(bc)
                    # Mark all steps in batch as done
                    for j, _ in enumerate(batch_items):
                        results[start_idx + j] = {"success": True, "action": "batch", "agent": agent}
                except Exception as e:
                    for j, _ in enumerate(batch_items):
                        results[start_idx + j] = {"success": False, "error": str(e)}

            for agent, items in agent_groups.items():
                if len(items) > 1:
                    t = threading.Thread(target=_run_batch, args=(agent, items, result_idx),
                                         daemon=True)
                    t.start()
                    threads.append(t)
                    result_idx += len(items)
                else:
                    ps = phase_steps[result_idx]
                    t = threading.Thread(target=_run_single, args=(result_idx, ps), daemon=True)
                    t.start()
                    threads.append(t)
                    result_idx += 1

            for t in threads:
                t.join(timeout=timeout)
            for r in results:
                if r:
                    aggregated["steps"].append(r)
                    if not r["success"]:
                        aggregated["success"] = False
                        aggregated["error"] = r.get("error", "")
        # Phase complete — mark checkpoints done
        self._mark_phase_checkpoint_done(involved_agents)

    def execute(self, timeout: float = 300.0) -> dict:
        """Execute all steps, respecting dependencies and card mode.

        CardMode.EXECUTE:     phases run sequentially, steps within follow PhaseMode
        CardMode.ISSUE:       creates proposals, doesn't execute
        CardMode.PARALLEL_ALL: all phases run concurrently in their own threads
        """
        self._started_at = time.time()
        aggregated: dict = {"steps": [], "success": True, "error": ""}

        if self._card_mode() == "issue":
            emit_signal(EVENT_REVIEW_REQUESTED, sender="execution_plan", target=self.card.cell_id or "cell",
                        data={"card_id": self.card.id, "event": "issue_created"})
            aggregated["issue"] = True
            aggregated["total_steps"] = len(self.steps)
            self._completed_at = time.time()
            return aggregated

        # Group steps by phase
        phases: dict[str, list[PlanStep]] = {}
        phase_order: list[str] = []
        for ps in self.steps:
            phases.setdefault(ps.phase, []).append(ps)
            if ps.phase not in phase_order:
                phase_order.append(ps.phase)

        phase_modes = {p.name: self._phase_mode(p) for p in self.card.phases}

        if self._card_mode() == "parallel_all":
            # All phases run concurrently
            phase_threads = []
            phase_results: list[dict] = []

            def _run_phase_wrapper(pname: str, psteps: list[PlanStep], pmode: PhaseMode) -> None:
                local_agg: dict = {"steps": [], "success": True, "error": ""}
                self._run_phase(pname, psteps, pmode, local_agg, timeout)
                phase_results.append(local_agg)

            for pname in phase_order:
                if self._cancelled:
                    break
                psteps = phases[pname]
                pmode = phase_modes.get(pname, PhaseMode.SEQUENTIAL)
                t = threading.Thread(target=_run_phase_wrapper, args=(pname, psteps, pmode),
                                     daemon=True)
                t.start()
                phase_threads.append(t)

            for t in phase_threads:
                t.join(timeout=timeout)

            for pr in phase_results:
                aggregated["steps"].extend(pr["steps"])
                if not pr["success"]:
                    aggregated["success"] = False
                    aggregated["error"] = pr.get("error", "")
        else:
            # Sequential phases (default EXECUTE mode)
            for phase_idx, phase_name in enumerate(phase_order):
                if self._cancelled:
                    break
                psteps = phases[phase_name]
                pmode = phase_modes.get(phase_name, PhaseMode.SEQUENTIAL)
                self._run_phase(phase_name, psteps, pmode, aggregated, timeout)
                if not aggregated.get("success", True):
                    break

                # ── Memory pressure check + auto-compaction between phases ──
                if phase_idx < len(phase_order) - 1:
                    self._check_memory_and_compact(aggregated)

        self._completed_at = time.time()
        aggregated["total_elapsed"] = round(self._completed_at - self._started_at, 3)
        aggregated["total_steps"] = len(self.steps)
        aggregated["completed"] = sum(1 for s in self.steps if s.state == StepState.DONE)
        aggregated["failed"] = sum(1 for s in self.steps if s.state == StepState.FAILED)

        emit_signal(EVENT_TASK_ASSIGN, sender="execution_plan", target=self.card.cell_id or "cell",
                    data={"card_id": self.card.id, "event": "plan_complete", **aggregated})
        return aggregated

    MEMORY_PRESSURE_INTERVAL: float = 30.0  # min seconds between compactions
    _last_compact: float = 0.0

    def _check_memory_and_compact(self, aggregated: dict) -> None:
        """Check memory pressure; if high, snapshot context → compact → resume.

        Called between sequential phases.  Never raises.
        """
        if time.time() - self._last_compact < self.MEMORY_PRESSURE_INTERVAL:
            return
        try:
            from .memory import get_memory
            mem = get_memory()
            p = mem.pressure()
            if p["level"] != "high":
                return

            # 1. Snapshot: save context register snapshots for all agents
            from .agent_terminal import get_terminals
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

            aggregated.setdefault("_memory_compactions", []).append({
                "timestamp": time.time(),
                "pressure": p,
                "merged": compact_r.get("merged", 0),
                "saved_tokens": compact_r.get("saved_tokens", 0),
            })
            logger.info("memory compact between phases: merged=%d saved=%d tokens",
                        compact_r.get("merged", 0), compact_r.get("saved_tokens", 0))
        except Exception as e:
            logger.warning("memory compaction skipped: %s", e)

    def _execute_step(self, ps: PlanStep, timeout: float) -> dict:
        """Execute a single plan step through the appropriate backend.

        If the step has verify spec, auto-runs scout before and after the step,
        and includes a diff in the result.
        """
        ps.state = StepState.RUNNING
        ps.started_at = time.time()
        emit_signal(EVENT_TASK_ASSIGN, sender="execution_plan", target=ps.agent,
                    data={"card_id": self.card.id, "step_id": ps.step_id, "event": "step_start"})

        # Find verify spec from the original Card step
        # (match by action + target, since agent is resolved differently)
        verify_spec = None
        for phase in self.card.phases:
            for item in self._card_phases_items(phase):
                if item.action == ps.action and item.target == ps.target:
                    verify_spec = item.verify if not self._is_unified else None
                    break

        verify_result = None

        try:
            # ── Pre-execution scout (before state) ──
            if verify_spec:
                before = self._execute_scout_verify(ps, verify_spec, "before")

            # ── Human approval gate (dangerous tools) ──
            if ps.agent != "scout_pool" and ps.action != "think":
                try:
                    from l3.tool_spec import get_tool
                    spec = get_tool(ps.action)
                    from l3.approval_gate import get_gate, _get_threshold
                    threshold = _get_threshold()
                    if spec and threshold > 0 and spec.danger >= threshold:
                        gate = get_gate()
                        ar = gate.request(
                            tool_name=ps.action, agent_id=ps.agent,
                            args=ps.params,
                            reason=f"danger={spec.danger} >= threshold={threshold}",
                        )
                        self._approval_requests.append(ar)
                        status = ar.wait(timeout=AGENT_LOOP_DEFAULT_TIMEOUT)
                        if status != "approved":
                            ps.state = StepState.FAILED
                            ps.error = f"rejected by human approval ({status})"
                            ps.completed_at = time.time()
                            return {"step_id": ps.step_id, "phase": ps.phase,
                                    "action": ps.action, "target": ps.target,
                                    "agent": ps.agent, "success": False,
                                    "error": ps.error, "elapsed": 0.0}
                except Exception as e:
                    logger.warning("approval check skipped: %s", e)

            # ── Main execution ──
            if ps.agent == "scout_pool":
                result = self._execute_scout(ps)
            else:
                result = self._execute_agent(ps, timeout)

            ps.state = StepState.DONE if result.get("success") else StepState.FAILED
            ps.result = result
            if not result.get("success"):
                ps.error = result.get("error", "unknown error")
            ps.completed_at = time.time()

            # ── Post-execution scout (after state, auto-verify) ──
            if verify_spec and result.get("success"):
                after = self._execute_scout_verify(ps, verify_spec, "after")
                if before.get("success") and after.get("success"):
                    verify_result = self._diff_verify(before, after)

            # Store in shared context
            self._context[ps.step_id] = result

            # Turn-level datalog: structured per-step record
            turn_entry = {
                "turn": len(self._turn_log) + 1,
                "step_id": ps.step_id,
                "phase": ps.phase,
                "action": ps.action,
                "target": ps.target,
                "agent": ps.agent,
                "success": result.get("success", False),
                "error": result.get("error", ""),
                "elapsed": round(ps.elapsed, 3),
                "verify": bool(verify_result),
                "danger": result.get("danger", 0),
                "gate_result": result.get("gate_result", ""),
            }
            self._turn_log.append(turn_entry)

            return {
                "step_id": ps.step_id,
                "phase": ps.phase,
                "action": ps.action,
                "target": ps.target,
                "agent": ps.agent,
                "success": result.get("success", False),
                "output": result.get("output", result.get("findings", "")),
                "error": result.get("error", ""),
                "elapsed": round(ps.elapsed, 3),
                "verify": verify_result,
            }
        except Exception as e:
            ps.state = StepState.FAILED
            ps.error = str(e)
            ps.completed_at = time.time()
            return {"step_id": ps.step_id, "phase": ps.phase, "action": ps.action,
                    "target": ps.target, "agent": ps.agent,
                    "success": False, "error": str(e),
                    "elapsed": round(ps.elapsed, 3), "verify": verify_result}

    def _execute_scout_verify(self, ps: PlanStep, spec: dict, phase: str) -> dict:
        from .execution_verify import execute_scout_verify as _verify
        return _verify(ps, spec, phase)

    def _diff_verify(self, before: dict, after: dict) -> dict:
        from .execution_verify import diff_verify as _diff
        return _diff(before, after)

    def _execute_scout(self, ps: PlanStep) -> dict:
        from .execution_verify import execute_scout as _scout
        return _scout(ps)

    def _execute_agent(self, ps: PlanStep, timeout: float) -> dict:
        """Execute a step through an AgentTerminal."""
        term = get_terminal(ps.agent)
        if term.status in (TerminalStatus.STOPPED, TerminalStatus.CRASHED):
            return {"success": False, "error": f"terminal {ps.agent} not running"}

        # If terminal hasn't booted, boot it
        if term.status == TerminalStatus.BOOTING:
            term.boot()

        params = dict(ps.params)
        if self.user_id:
            params["user_id"] = self.user_id

        # Inject context from previous steps so the next agent knows what was done
        if self._context:
            summaries = []
            for sid, ctx in self._context.items():
                if isinstance(ctx, dict):
                    act = ctx.get("action", "?")
                    tgt = ctx.get("target", "")
                    ok = ctx.get("success", False)
                    out = ctx.get("output", "")
                    agent = ctx.get("agent", "?")
                    summaries.append(
                        f"[{sid}] Agent {agent}: {act} {tgt} → {'✅' if ok else '❌'}"
                        f"{'  Output: ' + str(out)[:200] if out else ''}"
                    )
            if summaries:
                history_str = "Previous execution steps:\n" + "\n".join(summaries)
                params["context_history"] = history_str

        # Capability scoping: derive allowed tools from step action
        # A "read_file" step should not have write tools available.
        # The AgentLoop will receive _allowed_actions and restrict tool registration.
        action_scope = self._derive_action_scope(ps.action)
        params["_allowed_actions"] = action_scope

        card = TerminalCard(
            action=ps.action, target=ps.target,
            params=params, sender="execution_plan",
        )
        card_id = term.dispatch(card)
        result = term.wait_for_result(card_id, timeout=timeout)

        if result:
            return {"success": result.success, "output": result.output,
                    "findings": result.findings, "error": result.error,
                    "phases": result.phase}
        return {"success": False, "error": "timeout or no result"}

    @staticmethod
    def _derive_action_scope(action: str) -> list[str]:
        """Derive allowed tool names from a step action.

        read-only actions → only read tools
        write actions     → only write tools
        shell actions     → only shell tools
        think actions     → all tools (general purpose)
        """
        try:
            from .tool_config import ToolConfig as _TC
            from l1.kernel.params.kernel import RING_1
            read_tools = {t.name for t in _TC.by_ring(RING_1)}
            write_tools = _TC.write_tool_names()
            shell_tools = _TC.terminal_tool_names()
        except Exception:
            read_tools = {"read_file", "grep_search"}
            write_tools = set()
            shell_tools = set()
        all_tools = read_tools | write_tools | shell_tools
        action_lower = action.lower()
        if action_lower in read_tools or action_lower in ("read", "inspect", "scout"):
            return sorted(read_tools)
        if action_lower in write_tools or action_lower in ("write", "edit", "create", "replace"):
            return sorted(write_tools)
        if action_lower in shell_tools or action_lower in ("run", "execute", "build", "test"):
            return sorted(shell_tools)
        if action_lower == "think":
            return sorted(all_tools)
        return sorted(all_tools)  # unknown action: full access (conservative)

    def cancel(self) -> None:
        self._cancelled = True

    def progress(self) -> dict:
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
        return {
            "card_id": self.card.id,
            "intent": self._card_intent()[:80],
            "domain": self._card_domain(),
            "mode": self._card_mode(),
            "total_steps": len(self.steps),
            **self.progress(),
            "agent_map": self.agent_map,
        }
