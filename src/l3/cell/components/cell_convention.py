"""Cell convention operations — extracted from cell.py for modularity.
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l3.cell.components.cell_types import MessageType

logger = logging.getLogger(__name__)


def convene(cell: Any, issue_card: Any) -> dict:
    from .card.issue import IssueCard, IssueCardStatus, get_table

    if not isinstance(issue_card, IssueCard):
        return {"success": False, "error": "expected IssueCard"}

    iid = issue_card.id
    table = get_table()

    issue_card.agent_ids = list(cell._agents.keys())
    issue_card.cell_id = cell.cell_id
    table.set_status(iid, IssueCardStatus.DELIBERATING)

    domain = issue_card.domain or (cell.territory[0] if cell.territory else "")

    for it in issue_card.items:
        if not it.assigned_to:
            it.assigned_to = _match_agent(cell, it.domain or domain)

    from .card.convention import ConventionProtocol
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

    from .agent.convergence import converge as _converge, to_execution_card
    conv_r = _converge(issue_card_id)
    summary = conv_r.get("summary", "{}")

    from .card.issue import get_table
    table = get_table()
    issue_card = table.get(issue_card_id)
    if not issue_card:
        return {"success": False, "error": "issue card vanished"}

    exec_card = to_execution_card(issue_card, summary)

    cid = ""
    try:
        from .card.card_registry import get_registry
        registry = get_registry()
        cid = registry.submit(
            intent=exec_card.intent,
            domain=exec_card.domain,
            priority=exec_card.priority,
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
                         summary=conv_r.get("summary", "")[:200])
    except Exception:
        pass

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
    """Route a convention message to the ConventionProtocol."""
    card_id = payload.get("card_id", "")
    from .card.issue import get_table
    table = get_table()
    card = table.get(card_id)
    if not card:
        return {"success": False, "error": f"unknown convention: {card_id}"}

    conv = _get_convention(cell, card)
    if not conv:
        return {"success": False, "error": "no active convention"}

    if msg_type == MessageType.REBUT:
        return conv.rebut(agent_id, payload.get("statement", ""))
    elif msg_type == MessageType.PROPOSE_ISSUE:
        return conv.propose(agent_id, payload.get("question", ""), payload.get("domain", ""))
    elif msg_type == MessageType.CROSS_EXAMINE:
        return conv.cross_examine(agent_id, payload.get("target", ""),
                                  payload.get("statement", ""))
    return {"success": False, "error": f"unhandled convention message: {msg_type.name}"}


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
    from .card.convention import ConventionProtocol as ConvCls
    conv = ConvCls(issue_card, cell)
    cell._conventions[issue_card.id] = conv
    return conv
