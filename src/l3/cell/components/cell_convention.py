"""Cell convention operations — extracted from cell.py for modularity.
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.params.agent import SIGNAL_TARGET_L3
from l1.kernel.params.system import LOG_TRUNC_200, LOG_TRUNC_500
from l3.cell.components.cell_types import MessageType

logger = logging.getLogger(__name__)


def convene(cell: Any, issue_card: Any) -> dict:
    """Start a convention for an issue card within a cell.

    Returns a summary dict with the negotiation results.
    """
    from l3.card.issue import IssueCard, IssueCardStatus, get_table

    if not isinstance(issue_card, IssueCard):
        return {"success": False, "error": "expected IssueCard"}

    # Activate deliberation memory policy: Peer Agents share the Cell ring
    try:
        from l1.kernel.params.agent import CELL_MEMORY_POLICY_DELIBERATION
        cell.set_memory_policy(CELL_MEMORY_POLICY_DELIBERATION)
    except Exception:
        logger.debug("cell_convention: memory policy activation failed")

    iid = issue_card.id
    table = get_table()

    issue_card.agent_ids = list(cell._agents.keys())
    issue_card.cell_id = cell.cell_id
    table.set_status(iid, IssueCardStatus.DELIBERATING)

    domain = issue_card.domain or (cell.territory[0] if cell.territory else "")

    for it in issue_card.items:
        if not it.assigned_to:
            it.assigned_to = _match_agent(cell, it.domain or domain)

    from l3.card.convention import ConventionProtocol
    conv = ConventionProtocol(issue_card, cell)
    cell._conventions[iid] = conv
    result = conv.start()

    return {
        "success": True,
        "card_id": iid,
        "domain": domain,
        "participants": issue_card.agent_ids,
        "convention": result,
    }


def close_convention(cell: Any, issue_card_id: str) -> dict:
    """Close convention, trigger convergence, generate execution card."""
    conv = cell._conventions.get(issue_card_id)
    if not conv:
        return {"success": False, "error": f"no active convention: {issue_card_id}"}

    close_r = conv.close()
    if not close_r.get("success", True):
        return close_r

    # Restore isolated memory policy: shared ring no longer accessible
    try:
        from l1.kernel.params.agent import CELL_MEMORY_POLICY_ISOLATED
        cell.set_memory_policy(CELL_MEMORY_POLICY_ISOLATED)
    except Exception:
        logger.debug("cell_convention: memory policy restore failed")

    from l3.agent.convergence import converge as _converge
    from l3.agent.convergence import to_execution_card
    conv_r = _converge(issue_card_id)
    summary = conv_r.get("summary", "{}")

    from l3.card.issue import get_table
    table = get_table()
    issue_card = table.get(issue_card_id)
    if not issue_card:
        return {"success": False, "error": "issue card vanished"}

    exec_card = to_execution_card(issue_card, summary)

    # Complete the source card that routed to this convention (assembly mode)
    if issue_card.source_card_id:
        try:
            from l3.card.card_registry import get_registry
            registry = get_registry()
            registry._complete_convention_card(issue_card_id, summary)
        except Exception as e:
            logger.warning("convention source card complete failed: %s", e)

    cid = ""
    try:
        from l3.card.card_registry import get_registry
        registry = get_registry()
        exec_intent = (exec_card.summary.title if exec_card.summary else "")
        exec_domain = (exec_card.summary.columns.get("domain", "")
                       if exec_card.summary else "")
        cid = registry.submit(
            intent=exec_intent or "converged execution",
            domain=exec_domain,
            priority=getattr(exec_card, "priority", 5),
        )
    except Exception as e:
        logger.warning("convention exec card registry submit failed: %s", e)

    emit_signal(EVENT_TASK_ASSIGN, sender="convention", target=SIGNAL_TARGET_L3,
                 data={"card_id": issue_card_id, "event": "converged_exec_card",
                       "exec_card_id": cid,
                       "cache_ref": close_r.get("cache_ref", ""),
                       "archive_ref": close_r.get("archive_ref", "")})

    try:
        from l3.bus.reference_channel import get_rc as _rc
        _rc().convention(issue_card_id, "completed",
                         participants=list(conv._participants) if hasattr(conv, '_participants') else [],
                         summary=conv_r.get("summary", "")[:LOG_TRUNC_200])
    except Exception:
        logger.debug("cell_convention: reference channel convention event failed")

    return {
        "success": True,
        "issue_card_id": issue_card_id,
        "close": close_r,
        "convergence": conv_r,
        "exec_card_id": cid,
        "exec_card": exec_card.to_dict(),
    }


def handle_convention_message(cell: Any, agent_id: str,
                              msg_type: MessageType, payload: dict) -> dict:
    """Route a convention message to the ConventionProtocol.

    While the Cell is in deliberation policy, each statement is also
    mirrored into the Cell's shared deliberation memory ring (tagged with
    the issue id) — giving Peer Agents a shared negotiation context.
    """
    card_id = payload.get("card_id", "")
    from l3.card.issue import get_table
    table = get_table()
    card = table.get(card_id)
    if not card:
        return {"success": False, "error": f"unknown convention: {card_id}"}

    conv = _get_convention(cell, card)
    if not conv:
        return {"success": False, "error": "no active convention"}

    if msg_type in (MessageType.REBUT, MessageType.PROPOSE_ISSUE,
                    MessageType.CROSS_EXAMINE):
        _mirror_to_deliberation_ring(cell, card_id, agent_id, msg_type, payload)

    if msg_type == MessageType.REBUT:
        return conv.rebut(agent_id, payload.get("statement", ""))
    if msg_type == MessageType.PROPOSE_ISSUE:
        return conv.propose(agent_id, payload.get("question", ""), payload.get("domain", ""))
    if msg_type == MessageType.CROSS_EXAMINE:
        return conv.cross_examine(agent_id, payload.get("target", ""),
                                  payload.get("statement", ""))
    return {"success": False, "error": f"unhandled convention message: {msg_type.name}"}


def _mirror_to_deliberation_ring(cell: Any, card_id: str, agent_id: str,
                                 msg_type: MessageType, payload: dict) -> None:
    """Mirror a convention statement into the shared Cell ring (deliberation).

    Strategy-guarded: only writes when the Cell memory policy is
    deliberation (conference mode). In isolated (default) mode this is a
    no-op — Peer Agents keep their memory separate outside conventions.
    """
    try:
        mem = cell.convention_memory()
        if mem is None:
            return
        statement = payload.get("statement") or payload.get("question") or ""
        if not statement:
            return
        target = payload.get("target", "")
        entry_type = f"convention.{msg_type.name.lower()}"
        content = (f"[{card_id}] {agent_id}"
                   + (f" → {target}" if target else "")
                   + f": {statement[:LOG_TRUNC_500]}")
        mem.remember(
            agent_id=agent_id,
            entry_type=entry_type,
            content=content,
            tags=["convention", card_id, msg_type.name.lower()],
            importance=0.7,
            ring=1,
            cell_id=cell.cell_id,
        )
    except Exception as e:
        logger.debug("cell_convention: deliberation ring mirror failed: %s", e)


def _match_agent(cell: Any, domain: str) -> str:
    best = ""
    best_score = 0
    for aid, info in cell._agents.items():
        score = sum(1 for t in info.territory if domain.startswith(t))
        if score > best_score:
            best_score, best = score, aid
    return best or (next(iter(cell._agents.keys())) if cell._agents else "agent-1")


def _get_convention(cell: Any, issue_card: Any) -> Any:
    conv = cell._conventions.get(issue_card.id)
    if conv:
        return conv
    from l3.card.convention import ConventionProtocol as ConvCls
    conv = ConvCls(issue_card, cell)
    cell._conventions[issue_card.id] = conv
    return conv
