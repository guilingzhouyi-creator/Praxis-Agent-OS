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


# ── Stage ↔ TODO linkage (three-table closure: TODO verified → stage) ──
# The todowrite handler parses the ``[skill:<name>:<stage_id>]`` prefix out of
# a verified TODO and advances the skill's stage for the session. Materializing
# the completion criterion as a TODO is the quest-log step the loop tracks.

_STAGE_TODO_PREFIX = "[skill:"


def stage_todo_content(sm, skill_name: str, session_key: str = "") -> str:
    """Canonical TODO content for a staged skill's active stage.

    ``[skill:<name>:<stage_id>] <completion>`` — the prefix is the linkage key
    the todowrite bridge parses to advance the stage on 'verified'. Empty when
    the skill is unstaged or the stage has no completion criterion.
    """
    st = sm.current_stage(skill_name, session_key)
    if not st.get("staged"):
        return ""
    stage = st.get("stage") or {}
    completion = stage.get("completion") or ""
    stage_id = stage.get("id") or ""
    if not completion:
        return ""
    return f"[skill:{skill_name}:{stage_id}] {completion}"


def materialize_stage_todo(todo, sm, skill_name: str, session_key: str = "") -> dict:
    """Track a staged skill's active-stage completion as a TODO (quest-log).

    Idempotent: re-materializing the same stage is a no-op. Returns the
    tracked content (or a not-materialized marker for unstaged skills).
    """
    content = stage_todo_content(sm, skill_name, session_key)
    if not content:
        return {"materialized": False, "todo": ""}
    status = todo.status_of(content)
    if not status:
        todo.update(content, "add")
        status = "pending"
    return {"materialized": True, "todo": content, "status": status}


def advance_on_stage_todo_verified(todo, sm, content: str, session_key: str = "") -> dict:
    """Advance a staged skill when its stage TODO reaches 'verified'.

    Parses the ``[skill:<name>:<stage_id>]`` prefix out of a verified todo and
    advances the skill's stage for the session (three-table linkage). Only the
    CURRENT stage's verified TODO advances (stage-id must match, the skill
    must be staged, and the last stage has nothing to advance) — stale or
    future-stage confirmations are no-ops. Small mode (stages inert) never
    reports an advance.
    """
    if not content.startswith(_STAGE_TODO_PREFIX):
        return {"advanced": 0}
    parts = content[len(_STAGE_TODO_PREFIX) :].split("]", 1)[0].split(":")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return {"advanced": 0}
    if todo.status_of(content) != "verified":
        return {"advanced": 0}
    skill_name, stage_id = parts[0], parts[1]
    cur = sm.current_stage(skill_name, session_key)
    if not cur.get("staged"):
        return {"advanced": 0}  # small mode / unstaged: stages inert
    stage = cur.get("stage") or {}
    if stage.get("id") != stage_id:
        return {"advanced": 0}  # stale or future stage: chain integrity
    if cur.get("done"):
        return {"advanced": 0}  # last stage: nothing left to advance
    result = sm.advance_stage(skill_name, session_key)
    return {"advanced": 1 if result.get("success") else 0, "skill": skill_name, "result": result}
