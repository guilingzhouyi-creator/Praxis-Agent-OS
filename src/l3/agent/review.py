"""Peer review protocol — Agent-to-Agent review feedback loop.

Layer 2 of the feedback loop:
  - Agent A completes work
  - Agent B reviews it via config-driven prompts
  - Result: PASS / NEEDS_CHANGES / REJECT
  - Feedback routed back to Agent A for correction
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from l1.kernel.params.agent import REVIEW_MAX_ROUNDS
from l1.kernel.params.system import LOG_TRUNC_500, LOG_TRUNC_3000
from l1.kernel.prompts import get_prompt

logger = logging.getLogger(__name__)


def request_review(cell: Any, agent_id: str, reviewer_id: str, task: str, result: dict) -> dict:
    """Request a peer review from another agent.

    Returns:
        {"success": bool, "review_id": str, "verdict": str, "reason": str, ...}
    """
    review_id = f"review-{agent_id}-{int(time.time())}"

    from l3.cell.components.cell_types import MessageType

    cell.send_message(
        agent_id,
        reviewer_id,
        MessageType.REVIEW_REQUEST,
        {
            "review_id": review_id,
            "agent_id": agent_id,
            "reviewer_id": reviewer_id,
            "task": task,
            "result": result,
        },
    )

    return {"success": True, "review_id": review_id, "agent": agent_id, "reviewer": reviewer_id}


def perform_review(agent_id: str, reviewer_id: str, task: str, result: dict, llm_call: Any | None = None) -> dict:
    """Perform a review and return the verdict.

    Uses config-driven prompt from kernel.prompts.
    Returns dict with verdict/reason/suggestions.
    """
    result_str = json.dumps(result, indent=2, ensure_ascii=False, default=str)[:LOG_TRUNC_3000]
    prompt = get_prompt("review.request").format(
        agent=agent_id,
        task=task[:LOG_TRUNC_500],
        result=result_str,
    )

    if llm_call:
        try:
            raw = llm_call(prompt)
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            verdict = str(parsed.get("verdict", "NEEDS_CHANGES")).upper()
            if verdict not in ("PASS", "NEEDS_CHANGES", "REJECT"):
                verdict = "NEEDS_CHANGES"
            return {
                "reviewer": reviewer_id,
                "verdict": verdict,
                "reason": parsed.get("reason", ""),
                "suggestions": parsed.get("suggestions", []),
            }
        except Exception as e:
            logger.warning("review LLM failed: %s", e)

    return {
        "reviewer": reviewer_id,
        "verdict": "NEEDS_CHANGES",
        "reason": "Review unavailable (LLM or fallback)",
        "suggestions": [],
    }


def submit_review(cell: Any, reviewer_id: str, target_agent: str, review_id: str, verdict: dict) -> dict:
    """Submit a review result back to the original agent."""
    from l3.cell.components.cell_types import MessageType

    cell.send_message(
        reviewer_id,
        target_agent,
        MessageType.REVIEW_RESPONSE,
        {
            "review_id": review_id,
            "verdict": verdict.get("verdict", "NEEDS_CHANGES"),
            "reason": verdict.get("reason", ""),
            "suggestions": verdict.get("suggestions", []),
        },
    )
    return {"success": True, "review_id": review_id}


def handle_review_response(verdict: str, reason: str, suggestions: list[str], retry_count: int = 0) -> dict:
    """Process a review response and decide next action.

    Returns:
        {"action": "pass" | "retry" | "escalate",
         "correction_prompt": str, ...}
    """
    if verdict == "PASS":
        return {"action": "pass", "correction_prompt": ""}

    prompt = get_prompt("review.response.ack").format(
        agent="",
        verdict=verdict,
        reason=reason[:LOG_TRUNC_500],
    )

    if verdict == "REJECT" or retry_count >= REVIEW_MAX_ROUNDS:
        return {
            "action": "escalate",
            "correction_prompt": prompt,
            "reason": f"Review {verdict} after {retry_count} rounds",
        }

    return {
        "action": "retry",
        "correction_prompt": prompt,
        "round": retry_count + 1,
    }
