"""L3A ASK clarification API handlers.

Endpoints:
  POST /api/l3a/ask/status — current pending clarification state of a session
  POST /api/l3a/ask/answer — submit answers (and free-form input), then resume
"""

from __future__ import annotations

from typing import Any


def _get_session(session_id: str):
    from l3.cell.peers.l3a import get_daemon

    return get_daemon().manager.get(session_id)


def handle_l3a_ask_status(body: dict | None = None) -> dict:
    """POST /api/l3a/ask/status — pending question state for a session."""
    b = body or {}
    session_id = (b.get("session_id") or "").strip()
    if not session_id:
        return {"success": False, "error": "session_id required"}
    s = _get_session(session_id)
    if not s:
        return {"success": False, "error": f"session not active: {session_id}"}
    return s.ask_status()


def handle_l3a_ask_answer(body: dict | None = None) -> dict:
    """POST /api/l3a/ask/answer — submit answers, then resume the loop."""
    b = body or {}
    session_id = (b.get("session_id") or "").strip()
    if not session_id:
        return {"success": False, "error": "session_id required"}
    s = _get_session(session_id)
    if not s:
        return {"success": False, "error": f"session not active: {session_id}"}
    answers: dict[str, Any] = b.get("answers") or {}
    free_form = str(b.get("free_form") or "")
    r = s.submit_answers(answers, free_form)
    if not r.get("success"):
        return r
    return s.resume_after_ask()
