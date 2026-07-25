"""Convergence — L3A convergence summary + execution card conversion.

After ConventionProtocol.close() completes, L3A:
  1. Reads discussion document from CacheDocument
  2. LLM convergence summary (or rule-based fallback)
  3. Human review of convergence report
  4. Generates ExecutionCard → CardRegistry
"""

from __future__ import annotations

import json
import logging
from typing import Any

from services.card import Card, CardMode, Phase, Step
from services.cache_doc import get_store
from services.issue import IssueCardStatus

logger = logging.getLogger(__name__)


def converge(card_id: str, llm_call: callable | None = None) -> dict:
    """L3A convergence summary - reads discussion doc from CacheDocument, LLM summarizes.

    Args:
        card_id: IssueCard ID
        llm_call: optional LLM callable fn(prompt) -> str.
                  Uses rule fallback when None.

    Returns:
        {"success", "summary", "cache_ref", "archive_ref"}
    """
    from .issue import get_table
    table = get_table()
    issue_card = table.get(card_id)
    if not issue_card:
        return {"success": False, "error": f"unknown issue card: {card_id}"}
    if issue_card.status != IssueCardStatus.CONVERGED:
        return {"success": False, "error": f"card not converged: {issue_card.status.name}"}

    # 从 CacheDocument 读讨论文档
    doc_text = ""
    store = get_store()
    if issue_card.cache_ref:
        doc_text = store.get_content(issue_card.cache_ref) or ""
    if not doc_text:
        doc_text = _build_fallback_doc(issue_card)

    # LLM convergence summary
    if llm_call:
        summary = _llm_converge(doc_text, llm_call)
    else:
        summary = _rule_converge(issue_card, doc_text)

    issue_card.metadata["summary"] = summary

    logger.info("convergence complete: %s", card_id)
    return {
        "success": True,
        "card_id": card_id,
        "summary": summary,
        "cache_ref": issue_card.cache_ref,
        "archive_ref": issue_card.archive_ref,
    }


def to_execution_card(issue_card: IssueCard, summary: str) -> Card:
    """Convergence report → execution card.

    Convert issue_card items to Card phases/steps:
      - Each resolved issue → one Phase
      - Each Phase contains corresponding steps
    """
    phases = []

    # Issue execution phase
    work_steps = []
    for it in issue_card.items:
        if it.answer:
            action = "think" if it.assigned_to == "thinker" else "write_file"
            work_steps.append(Step(
                action=action,
                target=it.domain or it.question,
                params={"question": it.question, "answer": it.answer[:500]},
                agent=it.assigned_to or "default",
            ))

    if work_steps:
        phases.append(Phase(name="execute_issues", steps=work_steps))

    # Gap-filling phase
    phases.append(Phase(name="verify", steps=[
        Step(action="scout", target=issue_card.domain, agent="scout"),
    ]))

    if not phases:
        phases.append(Phase(name="default", steps=[
            Step(action="think", target=issue_card.intent, params={}),
        ]))

    return Card(
        id=f"exec-{issue_card.id}",
        intent=issue_card.intent,
        domain=issue_card.domain,
        mode=CardMode.EXECUTE,
        phases=phases,
    )


def _llm_converge(doc_text: str, llm_call: callable) -> str:
    from kernel.prompts import get_prompt
    base = get_prompt("convergence.summary")
    prompt = (
        base + "\n\n--- Discussion Document ---\n" + doc_text[:8000]
    )
    try:
        raw = llm_call(prompt)
        parsed = json.loads(raw)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except Exception:
        return _rule_converge_from_text()


def _rule_converge(issue_card: IssueCard, doc_text: str = "") -> str:
    resolved = [it for it in issue_card.items if it.status.name == "RESOLVED"]
    unresolved = [it for it in issue_card.items if it.status.name != "RESOLVED"]
    return json.dumps({
        "summary": f"Converged {len(resolved)}/{len(issue_card.items)} issues",
        "decisions": [f"{it.question}: {it.answer[:200]}" for it in resolved if it.answer],
        "unresolved": [it.question for it in unresolved],
        "recommendations": [],
        "confidence": round(len(resolved) / max(len(issue_card.items), 1), 2),
    }, indent=2, ensure_ascii=False)


def _rule_converge_from_text(doc_text: str = "") -> str:
    return json.dumps({
        "summary": "Rule-based convergence (LLM unavailable)",
        "decisions": [],
        "unresolved": [],
        "recommendations": [],
        "confidence": 0.0,
    }, indent=2)


def _build_fallback_doc(issue_card: IssueCard) -> str:
    lines = [f"# Convention: {issue_card.title}", ""]
    for it in issue_card.items:
        lines.append(f"- [{it.status.name}] {it.question} → {it.assigned_to}")
        if it.answer:
            lines.append(f"  Answer: {it.answer[:200]}")
    return "\n".join(lines)
