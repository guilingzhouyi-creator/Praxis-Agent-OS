"""Terminal convention handlers — extracted from agent_terminal.py.

Convention message handlers for AgentTerminal.
Each function takes (term, card) and returns CardResult.
"""

from __future__ import annotations

import logging
from typing import Any

from l3.agent._term_types import TerminalCard, CardResult
from l3.services.model_service import get_service as _get_model_service
from l1.kernel.params.system import LOG_TRUNC_200
from l1.kernel.params.agent import (
    CONVENTION_MAX_ROUNDS,
    AGENT_LOOP_DEFAULT_TIMEOUT,
    CONVENTION_SESSION_MAX_STEPS,
    CONVENTION_SESSION_TIMEOUT,
    CONVENTION_SUB_MAX_STEPS,
    CONVENTION_SUB_TIMEOUT,
)

_MODEL_SPEC = "convention"

logger = logging.getLogger(__name__)


def convention_handler(term: Any, card: TerminalCard) -> CardResult:
    msg_type = card.params.get("msg_type", "")
    payload = card.params.get("payload", {})
    conv_id = card.target
    if msg_type == "CONVENE":
        return _convention_start(term, conv_id, payload)
    elif msg_type == "CROSS_EXAMINE":
        return _convention_turn(term, conv_id, payload, is_examine=True)
    elif msg_type == "REBUT":
        return _convention_turn(term, conv_id, payload, is_examine=False)
    elif msg_type == "PROPOSE_ISSUE":
        return _convention_propose(term, conv_id, payload)
    elif msg_type == "CONVENE_CLOSE":
        return _convention_close(term, conv_id, payload)
    return CardResult(card_id=card.card_id, action="convention",
                      success=False, error=f"unknown convention msg: {msg_type}")


def _convention_start(term: Any, conv_id: str, payload: dict) -> CardResult:
    from l3.card.issue import get_table
    from l3.agent.agent_loop import AgentLoop
    table = get_table()
    issue_card = table.get(conv_id)
    if not issue_card:
        return CardResult(card_id=conv_id, action="convention",
                          success=False, error=f"unknown convention: {conv_id}")
    my_issues = [it for it in issue_card.items if it.assigned_to == term.agent_id]
    if not my_issues:
        my_issues = list(issue_card.items)

    from l1.kernel.prompts import get_prompt as _get_prompt
    issues_text = "\n".join(f"- {it.question} [{it.domain}]" for it in my_issues)
    system = _get_prompt("convention.system").format(
        agent_id=term.agent_id, role=term.role,
        title=issue_card.title, intent=issue_card.intent,
        domain=issue_card.domain,
        participants=", ".join(issue_card.agent_ids),
        issues=issues_text,
    )

    loop = AgentLoop(
        task=f"Convention: {issue_card.title}",
        agent_id=term.agent_id,
        system=system,
    )
    loop.run(max_steps=CONVENTION_SESSION_MAX_STEPS, timeout=CONVENTION_SESSION_TIMEOUT,
             **_get_model_service().resolve_dict(_MODEL_SPEC))
    term._convention_loops[conv_id] = {"loop": loop, "turn_count": 1}
    logger.info("agent %s joined convention %s: %d issues",
                 term.agent_id, conv_id, len(my_issues))
    return CardResult(card_id=conv_id, action="convention",
                      success=True,
                      output=f"Joined convention, {len(my_issues)} issues assigned")


def _convention_turn(term: Any, conv_id: str, payload: dict,
                     is_examine: bool = True) -> CardResult:
    session = term._convention_loops.get(conv_id)
    if not session:
        return CardResult(card_id=conv_id, action="convention",
                          success=False, error="no active convention session")
    loop_obj = session.get("loop")
    if not loop_obj:
        return CardResult(card_id=conv_id, action="convention",
                          success=False, error="no AgentLoop session")

    statement = payload.get("statement", payload.get("question", ""))
    source = payload.get("from", payload.get("sender", "unknown"))
    if is_examine:
        prompt = f"Cross-examination from {source}: {statement}\n\nRespond with your position."
    else:
        prompt = f"{source} says: {statement}\n\nAcknowledge and respond."

    loop_obj.task = prompt
    loop_obj.run(max_steps=CONVENTION_MAX_ROUNDS, timeout=AGENT_LOOP_DEFAULT_TIMEOUT,
                 **_get_model_service().resolve_dict(_MODEL_SPEC))
    session["turn_count"] += 1
    return CardResult(card_id=conv_id, action="convention",
                      success=True, output=f"Turn {session['turn_count']} processed")


def _convention_propose(term: Any, conv_id: str, payload: dict) -> CardResult:
    session = term._convention_loops.get(conv_id)
    if session and session.get("loop"):
        question = payload.get("question", "")
        proposer = payload.get("sender", "unknown")
        session["loop"].task = f"Agent {proposer} proposes: {question}\n\nDo you support this? Any concerns?"
        session["loop"].run(max_steps=CONVENTION_SUB_MAX_STEPS, timeout=CONVENTION_SUB_TIMEOUT,
                            **_get_model_service().resolve_dict(_MODEL_SPEC))
    return CardResult(card_id=conv_id, action="convention",
                      success=True, output="Proposal acknowledged")


def _convention_close(term: Any, conv_id: str, payload: dict) -> CardResult:
    session = term._convention_loops.pop(conv_id, None)
    answer = ""
    if session and session.get("loop"):
        loop_obj = session["loop"]
        loop_obj.task = "The convention has concluded. Summarize your final position in 2-3 sentences."
        loop_obj.run(max_steps=CONVENTION_SUB_MAX_STEPS, timeout=CONVENTION_SUB_TIMEOUT,
                     **_get_model_service().resolve_dict(_MODEL_SPEC))
        answer = getattr(loop_obj, "result", {}).get("answer", "") if hasattr(loop_obj, "result") else ""
        logger.info("agent %s convention %s final: %s", term.agent_id, conv_id, answer[:LOG_TRUNC_200])
    term._convention_loops.pop(conv_id, None)
    return CardResult(card_id=conv_id, action="convention",
                      success=True, output=answer or "Convention closed")
