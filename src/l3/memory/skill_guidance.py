"""Card → skill stage linkage bridge (three-table integration).

CardRegistry fires completion listeners when a card finishes; this module
forwards those events to SkillManager stage state so staged skills bound to
the card's session advance to their next stage (quest-style progression).

Layer rule: L1 skill.py never imports L3 card_registry — the bridge lives
here in L3 and is registered lazily on first use (or explicitly at boot via
``wire_card_guidance``). Registration is best-effort: if the registry is not
available the bridge simply does nothing (stages still advance through the
API / L2 Shell or manual advance_stage calls).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_registered = False


def _ensure_listener() -> None:
    """Register the card-completion → skill-stage listener once (idempotent)."""
    global _registered
    if _registered:
        return
    try:
        from l3.card.card_registry import get_registry

        reg = get_registry()
        reg.register_completion_listener(_on_card_complete)
        _registered = True
        logger.debug("skill_guidance: card completion listener registered")
    except Exception as e:
        logger.debug("skill_guidance: card listener registration skipped: %s", e)


def _on_card_complete(card_id: str, state: str, result: dict | None) -> None:
    """Card finished → advance staged skills under the card session key."""
    try:
        from l1.kernel.skill import get_skill_manager

        get_skill_manager().on_card_complete(card_id, state, result)
    except Exception as e:
        logger.debug("skill_guidance: stage advance failed: %s", e)


def wire_card_guidance() -> dict:
    """Explicitly register the card→skill guidance bridge (idempotent)."""
    _ensure_listener()
    return {"success": True, "registered": _registered}


def reset_guidance() -> None:
    """Reset the registration flag (test isolation)."""
    global _registered
    _registered = False
