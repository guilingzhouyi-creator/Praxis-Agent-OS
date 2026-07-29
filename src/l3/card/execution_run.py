"""Execution run — extracted from execution_plan.py for modularity.

Contains the main execution flow: execute, _run_phase, _execute_step, _execute_agent.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel import EVENT_REVIEW_REQUESTED, emit_signal
from l1.kernel.params.agent import AGENT_LOOP_DEFAULT_TIMEOUT, EVENT_REVIEW_REQUESTED as _EVT_REV
from l1.kernel.params.system import SANDBOX_EXEC_TIMEOUT
from l3.card.plan_step_types import StepState
from l3.card.models import PhaseMode

logger = logging.getLogger(__name__)


def execute(plan, timeout: float = SANDBOX_EXEC_TIMEOUT) -> dict:
    """Execute all steps, respecting dependencies and card mode."""
    plan._started_at = time.time()
    aggregated: dict = {"steps": [], "success": True, "error": ""}

    if plan._card_mode() == "issue":
        emit_signal(EVENT_REVIEW_REQUESTED, sender="execution_plan", target=plan.card.cell_id or "cell",
                    data={"card_id": plan.card.id, "event": "issue_created"})
        aggregated["issue"] = True
        aggregated["total_steps"] = len(plan.steps)
        plan._completed_at = time.time()
        return aggregated

    phases: dict[str, list[Any]] = {}
    phase_order: list[str] = []
    for ps in plan.steps:
        phases.setdefault(ps.phase, []).append(ps)
        if ps.phase not in phase_order:
            phase_order.append(ps.phase)

    phase_modes = {p.name: plan._phase_mode(p) for p in plan.card.phases}

    if plan._card_mode() == "parallel_all":
        phase_threads = []
        phase_results: list[dict] = []

        def _run_phase_wrapper(pname, psteps, pmode):
            local_agg: dict = {"steps": [], "success": True, "error": ""}
            _run_phase(plan, pname, psteps, pmode, local_agg, timeout)
            phase_results.append(local_agg)

        for pname in phase_order:
            if plan._cancelled:
                break
            psteps = phases[pname]
            pmode = phase_modes.get(pname, PhaseMode.SEQUENTIAL)
            t = threading.Thread(target=_run_phase_wrapper, args=(pname, psteps, pmode), daemon=True)
            t.start()
            phase_threads.append(t)

        for t in phase_threads:
            t.join(timeout=timeout)

        final_success = all(pr.get("success", False) for pr in phase_results)
        for pr in phase_results:
            aggregated["steps"].extend(pr.get("steps", []))
            if not pr.get("success"):
                aggregated["error"] = pr.get("error", "")
        aggregated["success"] = final_success
    else:
        for pname in phase_order:
            if plan._cancelled:
                break
            psteps = phases[pname]
            pmode = phase_modes.get(pname, PhaseMode.SEQUENTIAL)
            _run_phase(plan, pname, psteps, pmode, aggregated, timeout)

    aggregated["total_steps"] = len(aggregated["steps"])
    plan._completed_at = time.time()
    return aggregated


def _run_phase(plan, pname: str, psteps: list[Any], pmode: Any, aggregated: dict, timeout: float) -> None:
    """Run a single phase."""
    from l3.agent_terminal import get_terminal
    for ps in psteps:
        if plan._cancelled:
            break
        ps.state = StepState.RUNNING
        plan._save_step_checkpoint(ps)

        if pmode == PhaseMode.SEQUENTIAL:
            result = _execute_step(plan, ps, timeout)
            aggregated["steps"].append(result)
            if not result.get("success") and result.get("blocking", True):
                aggregated["success"] = False
                aggregated["error"] = result.get("error", "step failed")
                break
        elif pmode == PhaseMode.PARALLEL:
            from l3.card.execution_verify import execute_scout_verify
            from l3.card.execution_plan import PlanStep
            step_count = len(psteps)
            if step_count <= 1:
                result = _execute_step(plan, ps, timeout)
                aggregated["steps"].append(result)
            else:
                scout_template = ps.params.get("_verify_template", "")
                if scout_template:
                    sv = execute_scout_verify(ps, {"template": scout_template}, "before")
                    aggregated.setdefault("scout_verifications", []).append(sv)
                results = []
                for sub_ps in psteps:
                    r = _execute_step(plan, sub_ps, timeout)
                    results.append(r)
                    if not r.get("success"):
                        break
                aggregated["steps"].extend(results)

        ps.state = StepState.DONE
        plan._mark_phase_checkpoint_done(ps)


def _execute_step(plan, ps, timeout: float) -> dict:
    """Execute a single PlanStep."""
    from l3.agent_terminal import get_terminal
    from l3.card.execution_verify import execute_scout, execute_scout_verify, diff_verify
    tool = ps.action
    agent_id = plan._resolve_agent(ps)

    if tool == "scout_delegate":
        return _execute_scout(ps)
    if tool == "verify":
        spec = ps.params.get("_verify_spec", {})
        phase = ps.params.get("_verify_phase", "before")
        return execute_scout_verify(ps, spec, phase)
    if tool in ("write_file", "create_file", "replace_string"):
        before = execute_scout_verify(ps, {}, "before") if ps.params.get("_verify_before") else None
        result = _execute_agent(plan, ps, agent_id, timeout)
        after = execute_scout_verify(ps, {}, "after") if ps.params.get("_verify_after") else None
        if before and after:
            diff = diff_verify(before, after)
            result["verification"] = diff
        return result

    return _execute_agent(plan, ps, agent_id, timeout)


def _execute_scout(ps) -> dict:
    """Execute a scout step via ScoutPool."""
    from l3.card.execution_verify import execute_scout as _es
    return _es(ps)


def _execute_agent(plan, ps, agent_id: str, timeout: float) -> dict:
    """Execute a step on an AgentTerminal."""
    from l3.agent_terminal import get_terminal, TerminalCard, CardMode as TermCardMode, TerminalStatus
    from l3.card.execution_verify import execute_scout_verify as _esv
    from l3.cell.components.cell_types import is_scout, is_subagent
    term = get_terminal(agent_id, role=ps.role, territory=ps.territory, cell_id=plan.card.cell_id or "")
    if term.status in (TerminalStatus.BOOTING, TerminalStatus.STOPPED):
        term.boot()

    tc = TerminalCard(
        action=ps.action,
        target=ps.target,
        params=dict(ps.params),
        mode=TermCardMode.EXECUTE,
    )
    # Inject card-level gate_scope for GateChain enforcement
    card_scope = getattr(plan.card, '_gate_scope', '') if hasattr(plan, 'card') else ''
    if card_scope:
        tc.params['_gate_scope'] = card_scope

    from l3.agent._term_handlers import get_action_handler
    handler = get_action_handler(term, ps.action)
    if handler:
        phases = []
        output, findings, ok = handler(term, tc, phases)
        return {"step": ps.action, "target": ps.target, "success": ok,
                "output": output, "findings": findings, "phase": ps.phase}

    r = term.dispatch(tc)
    if not r.get("success"):
        return {"step": ps.action, "target": ps.target, "success": False,
                "error": r.get("error", "dispatch failed"), "phase": ps.phase}
    result = term.wait_for_result(tc.card_id, timeout=timeout)
    if result:
        return {"step": ps.action, "target": ps.target,
                "output": result.output, "findings": result.findings,
                "success": result.success, "error": result.error, "phase": ps.phase,
                "card_id": tc.card_id}
    return {"step": ps.action, "target": ps.target, "success": False,
            "error": "timeout or no result", "phase": ps.phase}
