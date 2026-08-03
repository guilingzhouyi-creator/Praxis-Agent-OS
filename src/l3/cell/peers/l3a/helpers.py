"""Shared helpers — cardwrite handler, prompt builder, etc."""

from __future__ import annotations

import logging

from l1.kernel.params.system import LOG_TRUNC_60
from l3.card.card_unified import CardUnified, CardSummary, PhaseMode, list_card_types
from . import params as _p

from l3.error_bus import capture

logger = logging.getLogger(__name__)


def build_l3a_prompt() -> str:
    from l1.kernel.prompts import get_prompt as _gp
    types = list_card_types()
    types_block = "\n".join(
        f"  - {t['name']}: {t['display']} (phases: {', '.join(t.get('phases', []))})"
        for t in types
    )
    return _gp("l3a.agentloop_system").format(card_types=types_block)


def cardwrite_handler(args: dict, agent_id: str = "") -> dict:
    from l3.card.card_registry import get_registry
    nature = args.get("nature", "execution")
    title = args.get("title", args.get("intent", ""))
    description = args.get("description", "")
    columns = args.get("columns", {})
    priority = args.get("priority", 5)
    phases_data = args.get("phases", [])
    domain = columns.get("domain", "")

    card = CardUnified(nature=nature, priority=priority)
    card.summary = CardSummary(title=title, description=description, columns=columns)
    for pd in phases_data:
        mode_str = pd.get("mode", "single")
        mode = PhaseMode.MULTI if mode_str == "multi" else PhaseMode.SINGLE
        phase = card.add_phase(name=pd.get("name", ""), mode=mode,
                               agents=pd.get("agents", []),
                               review_prompt=pd.get("review_prompt", ""))
        for td in pd.get("tasks", []):
            card.add_task(phase_name=phase.name, action=td.get("action", ""),
                          target=td.get("target", ""), params=td.get("params", {}),
                          agent=td.get("agent", ""))
    card.submit()

    try:
        reg = get_registry()
        cid = reg.submit(intent=title, domain=domain, priority=priority, card_id=card.id)
        with reg._lock:
            reg._cards[cid] = card
        mode = _route_to_assembly(card)
        card.summary.columns["_assembly_mode"] = mode.value
        return {"success": True, "card_id": card.id, "nature": nature,
                "phases": len(phases_data), "message": f"Card {card.id} submitted"}
    except Exception as e:
        return {"success": False, "error": str(e), "card_id": card.id}


def wrapped_cardwrite(args: dict, agent_id: str = "") -> dict:
    return cardwrite_handler(args, agent_id)


def _route_to_assembly(card: CardUnified) -> "AssemblyMode":
    from .types import AssemblyMode
    try:
        from l3.card.card_gate import evaluate as _gate_evaluate
        r = _gate_evaluate(card_id=card.id,
                           intent=card.summary.title if card.summary else "",
                           domain=getattr(card, "domain", ""),
                           file_count=0, estimated_lines=0, has_conflict=False)
        size = r.get("size", "small")
        if r.get("auto_approve", False):
            return AssemblyMode.AUTO_APPROVE
        if size == "disputed":
            return AssemblyMode.CONFERENCE
        if size in ("large", "medium"):
            return AssemblyMode.DEFAULT
        return AssemblyMode.DEFAULT
    except Exception:
        return AssemblyMode.AUTO_APPROVE


def get_convergence_queue(cell_id: str) -> list[dict]:
    try:
        from l3.discussion.cell_answer_repo import CellAnswerRepo
        from l3.cell import get_cell
        cell = get_cell(cell_id)
        if not cell:
            return []
        repo = CellAnswerRepo(cell_id, "")
        answers = repo.get_all()
        return [{"agent_id": a.agent_id, "phase": a.phase, "type": a.answer_type,
                 "fingerprint": a.fingerprint, "created_at": a.created_at}
                for a in answers]
    except Exception:
        return []
