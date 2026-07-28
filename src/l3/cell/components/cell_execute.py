"""Card execution — extracted from cell/__init__.py for modularity.

Contains Cell.execute_card() and its direct helpers:
  _raw_to_card, _execute_decomposed, _snapshot_and_inject
"""

from __future__ import annotations

import logging
import time
import uuid

from l1.kernel.params.agent import CELL_SNAPSHOT_MAX
from l1.kernel.params.api import SUBAGENT_RUN_TIMEOUT
from l3.cell.components.cell_decompose import auto_agent_map as _auto_agent_map

logger = logging.getLogger(__name__)


def execute_card(
    cell,
    card,
    agent_map: dict[str, str] | None = None,
    domain: str = "",
    user_id: str = "",
) -> dict:
    """Execute a Card through the Cell.

    Delegates to ExecutionPlan for multi-agent execution.
    Handles IssueCard routing, raw intents, decomposed cards.
    """
    from l3.card.issue import IssueCard as _IssueCard
    if isinstance(card, _IssueCard):
        # Check if there's an active orchestrated discussion for this issue
        try:
            from l3.discussion.issue_orchestrator import get_orchestrator
            sessions = get_orchestrator().list_sessions(status="in_progress")
            for s in sessions:
                if s.get("issue_card_id") == card.id:
                    # Already handled by orchestrator → AnswerSession will pick it up
                    return {"success": True, "action": "orchestrated", "session_id": s.get("id")}
        except Exception:
            pass
        return cell.convene(card, agent_map)

    cell._current_user_id = user_id
    try:
        from l3.scheduler.scheduler import get_scheduler as get_sched
        sched = get_sched()
        for aid, info in cell._agents.items():
            sched.router.register(aid, cell.territory, info.ring / 3.0)
    except Exception as e:
        logger.warning("scheduler register failed: %s", e)

    if isinstance(card, str):
        card = _raw_to_card(cell, card, domain)

    domain = domain or card.domain
    if domain and agent_map is None:
        from l3.cell.components.cell_decompose import decompose_card as _dc
        slices = _dc(domain, card, cell.cell_id, ensure_terminal_fn=cell._ensure_terminal)
        if len(slices) > 1:
            result = _execute_decomposed(cell, slices)
            result["card_id"] = card.id
            result["intent"] = card.intent[:80]
            return result

    if agent_map is None:
        agent_map = _auto_agent_map(card, cell.cell_id,
                                    ensure_terminal_fn=lambda a, r, t: cell._ensure_terminal(a, r, t or cell.territory))

    from l3.agent_terminal import get_terminals, TerminalStatus
    all_terms = get_terminals()
    for _, aid in agent_map.items():
        term = all_terms.get(aid)
        if term and term.status in (TerminalStatus.BOOTING, TerminalStatus.STOPPED):
            term.boot()

    if cell._emergency:
        return {"success": False, "error": "Cell emergency stopped", "cell_id": cell.cell_id}

    card_id = card.id if hasattr(card, "id") else f"card-{uuid.uuid4().hex[:8]}"
    _snapshot_and_inject(cell, card_id, card)

    from l3.card.execution_plan import ExecutionPlan
    plan = ExecutionPlan(card, agent_map, user_id=cell._current_user_id)
    try:
        result = plan.execute()
    finally:
        snap_wrapper = cell._card_snapshots.pop(card_id, None)
        if snap_wrapper and isinstance(snap_wrapper, dict):
            _cleanup_snapshot(cell, snap_wrapper.get("files", {}))

    result["card_id"] = card_id
    cell._card_history.push({
        "card_id": card_id,
        "intent": card.intent[:60] if hasattr(card, "intent") else str(card)[:60],
        "completed_at": time.time(),
        "success": result.get("success", False),
    })
    result["intent"] = card.intent[:80] if hasattr(card, "intent") else str(card)[:80]
    result["agent_map"] = agent_map
    # PMU counters
    if result.get("success"):
        cell._pmu.increment("cards.completed")
    else:
        cell._pmu.increment("cards.failed")
    return result


def _raw_to_card(cell, raw_intent: str, domain: str, skip_htn: bool = False):
    """Convert raw intent string to a structured Card via HTN or CardBuilder."""
    raw_domain = domain or (cell.territory[0] if cell.territory else "")
    if not skip_htn:
        try:
            from l3.bus.htn_planner import get_service as get_htn
            htn = get_htn()
            htn_task = htn.decompose(raw_intent, raw_domain)
            if htn_task.sub_tasks:
                return htn.to_card(htn_task, domain=raw_domain)
        except Exception as e:
            logger.warning("HTN decompose failed: %s", e)
    from l3.card.card_builder import build_card as _build_structured_card
    return _build_structured_card(
        task_id=f"auto-{uuid.uuid4().hex[:8]}",
        intent=raw_intent,
        domain=raw_domain,
    )


def _execute_decomposed(cell, slices: list[dict]) -> dict:
    """Execute multiple decomposed card slices in sequence."""
    from l3.agent_terminal import get_terminal
    results = []
    all_passed = True
    t0 = time.time()
    for sl in slices:
        sub_card = sl["card"]
        agent_id = sl.get("agent_id", "")
        role = sl.get("role", "")
        territory = sl.get("territory", [])
        sub_agent_map = sl.get("agent_map", {})

        # ── SubAgent pool route (through card-type gate) ──
        subagent_spec = sl.get("subagent_spec", "") or (sub_card.subagent_spec if hasattr(sub_card, "subagent_spec") else "")
        if subagent_spec:
            from l3.agent.subagent_gate import classify_card, build_spec
            pool = cell._subagent_pool
            card_type = classify_card(sub_card)
            spec = build_spec(card_type, spec_name=subagent_spec)
            r = pool.commission(spec, prompt=sub_card.intent if hasattr(sub_card, "intent") else "",
                                card_type=card_type,
                                parent_agent_id=agent_id, cell=cell)
            if r.get("success"):
                result = pool.collect(r["task_id"], timeout=SUBAGENT_RUN_TIMEOUT)
                results.append(result)
            else:
                results.append(r)
                all_passed = False
                break
            continue

        if not agent_id and sub_agent_map:
            agent_id = list(sub_agent_map.values())[0]
        term = get_terminal(agent_id, role=role, territory=territory, cell_id=cell.cell_id)
        from l3.agent_terminal import CardMode as TermCardMode
        sc = term.dispatch(sub_card)
        if not sc.get("success"):
            return {"success": False, "error": sc.get("error", "dispatch failed"),
                    "results": results}
        r = term.wait_for_result(sub_card.id, timeout=SUBAGENT_RUN_TIMEOUT)
        if r:
            results.append(r.to_dict() if hasattr(r, "to_dict") else r.to_dict())
            if not r.success:
                all_passed = False
                break
    cell._pmu.increment("cards.decomposed", delta=len(slices))
    return {"success": all_passed, "results": results, "elapsed": round(_time.time() - t0, 2)}


def _snapshot_and_inject(cell, card_id: str, card) -> None:
    """Snapshot files + logical state for rollback recovery."""
    files = {}
    phases = getattr(card, "phases", []) or []
    for phase in phases:
        steps = getattr(phase, "steps", getattr(phase, "tasks", [])) or []
        for step in steps:
            path = getattr(step, "target", "") or (isinstance(step, dict) and step.get("target", ""))
            if path and path not in files:
                file_content = _take_snapshot(cell, path)
                if file_content is not None:
                    files[path] = file_content

    # Snapshot logical agent state from Cell._agents
    agent_snap = {}
    for aid, info in cell._agents.items():
        agent_snap[aid] = {
            "role": info.role, "ring": info.ring,
            "status": info.status.name,
            "active_scouts": info.active_scouts,
        }

    # Snapshot CellCache keys currently visible to agents
    try:
        cache_stats = cell._cache.stats() if cell._cache else {}
        cache_keys = (
            list(cell._cache._kv.keys())[:100]
            if hasattr(cell._cache, "_kv") else []
        )
    except Exception:
        cache_keys = []

    cell._card_snapshots[card_id] = {
        "files": files, "ts": time.time(),
        "agent_snap": agent_snap,
        "cache_keys": cache_keys,
    }
    logger.debug("snapshots taken for %s: %d files, %d agents, %d cache keys",
                 card_id, len(files), len(agent_snap), len(cache_keys))
    # Inject rollback context from previous rollbacks
    if cell._rollback_ring:
        from l3.cell.components.cell_buffer import CircularBuffer
        for item in list(cell._rollback_ring._data):
            if isinstance(item, str) and item.startswith("Card "):
                logger.info("rollback context injected for %s: %s", card_id, item[:80])
                break


def _take_snapshot(cell, path: str) -> str | None:
    """Snapshot a file by copying to temp dir. Returns tmp path or None."""
    import os, tempfile
    if not path or not os.path.exists(path) or os.path.isdir(path):
        return None
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".snap").name
        import shutil
        shutil.copy2(path, tmp)
        return tmp
    except Exception as e:
        logger.debug("snapshot failed for %s: %s", path, e)
        return None


def _cleanup_snapshot(cell, files: dict) -> None:
    """Clean up temporary snapshot files."""
    import os
    for tmp_path in files.values():
        if isinstance(tmp_path, str) and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
