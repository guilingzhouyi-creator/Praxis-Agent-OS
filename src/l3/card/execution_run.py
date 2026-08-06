"""Execution run 鈥?extracted from execution_plan.py for modularity.

Contains the main execution flow: execute, _run_phase, _execute_step, _execute_agent.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel import EVENT_REVIEW_REQUESTED, emit_signal
from l1.kernel.discovery import get_tool_config

_SANDBOX_EXEC_TIMEOUT = get_tool_config("exec_timeout", 300)
from l3.card.models import PhaseMode
from l3.card.plan_step_types import StepState

logger = logging.getLogger(__name__)


def _plan_cell_id(plan) -> str:
    """Extract the cell id from either card model (old Card: attribute,
    CardUnified: summary.columns)."""
    card = plan.card
    cid = getattr(card, "cell_id", "")
    if not cid and hasattr(card, "summary"):
        try:
            cid = card.summary.columns.get("cell_id", "")
        except Exception:
            pass
    return cid or ""


def execute(plan, timeout: float | None = None) -> dict:
    """Execute all steps, respecting dependencies and card mode."""
    if timeout is None:
        from l1.kernel.discovery import get_tool_config
        timeout = float(get_tool_config("exec_timeout", 300))
    plan._started_at = time.time()
    aggregated: dict = {"steps": [], "success": True, "error": ""}

    if plan._card_mode() == "issue":
        emit_signal(EVENT_REVIEW_REQUESTED, sender="execution_plan", target=_plan_cell_id(plan) or "cell",
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
    """Run a single phase.

    SEQUENTIAL: execute each step in order, stopping on blocking failure.
    PARALLEL:   execute the phase's steps once each (the outer per-step loop
                must not re-iterate the whole list 鈥?that would run every
                step N times).
    """
    is_parallel = pmode == PhaseMode.PARALLEL or pmode == "parallel"

    if is_parallel:
        from l3.card.execution_verify import execute_scout_verify
        results = []
        for ps in psteps:
            if plan._cancelled:
                break
            ps.state = StepState.RUNNING
            plan._save_step_checkpoint(ps)
            scout_template = ps.params.get("_verify_template", "")
            if scout_template:
                sv = execute_scout_verify(ps, {"template": scout_template}, "before")
                aggregated.setdefault("scout_verifications", []).append(sv)
            r = _execute_step(plan, ps, timeout)
            results.append(r)
            ps.state = StepState.DONE
            plan._mark_phase_checkpoint_done({ps.agent})
            if not r.get("success"):
                break
        aggregated["steps"].extend(results)
        return

    for ps in psteps:
        if plan._cancelled:
            break
        ps.state = StepState.RUNNING
        plan._save_step_checkpoint(ps)

        result = _execute_step(plan, ps, timeout)
        aggregated["steps"].append(result)
        ps.state = StepState.DONE
        plan._mark_phase_checkpoint_done({ps.agent})
        if not result.get("success") and result.get("blocking", True):
            aggregated["success"] = False
            aggregated["error"] = result.get("error", "step failed")
            break


def _execute_step(plan, ps, timeout: float) -> dict:
    """Execute a single PlanStep."""
    from l3.card.execution_verify import diff_verify, execute_scout_verify
    tool = ps.action
    agent_id = plan._resolve_agent(ps.agent)

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
    from l3.agent_terminal import CardMode as TermCardMode
    from l3.agent_terminal import TerminalCard, TerminalStatus, get_terminal
    t_step = time.time()
    term = get_terminal(agent_id, cell_id=_plan_cell_id(plan))
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
                "output": output, "findings": findings, "phase": ps.phase,
                "agent_id": agent_id, "cell_id": _plan_cell_id(plan),
                "elapsed": round(time.time() - t_step, 3)}

    card_id = term.dispatch(tc)
    result = term.wait_for_result(card_id, timeout=timeout)
    if result:
        return {"step": ps.action, "target": ps.target,
                "output": result.output, "findings": result.findings,
                "success": result.success, "error": result.error, "phase": ps.phase,
                "card_id": card_id,
                "agent_id": agent_id, "cell_id": _plan_cell_id(plan),
                "elapsed": round(time.time() - t_step, 3)}
    return {"step": ps.action, "target": ps.target, "success": False,
            "error": "timeout or no result", "phase": ps.phase,
            "agent_id": agent_id, "cell_id": _plan_cell_id(plan),
            "elapsed": round(time.time() - t_step, 3)}

