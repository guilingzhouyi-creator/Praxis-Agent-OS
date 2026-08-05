"""L3A API handlers — ASK clarification + session contract endpoints.

Endpoints:
  POST /api/v2/l3a/ask/status        — pending clarification state of a session
  POST /api/v2/l3a/ask/answer        — submit answers, then resume
  POST /api/v2/l3a/sessions          — create a session
  GET  /api/v2/l3a/sessions          — list active sessions
  GET  /api/v2/l3a/sessions/{session_id}          — session detail (info + todos)
  GET  /api/v2/l3a/sessions/{session_id}/messages — cursor-paged message history
  POST /api/v2/l3a/sessions/{session_id}/send     — send intent / continue
  POST /api/v2/l3a/sessions/{session_id}/close    — close and archive
  POST /api/v2/l3a/sessions/{session_id}/compress — compress history
"""

from __future__ import annotations

from typing import Any

from l1.kernel.params.api import API_PAGE_MAX_LIMIT
from l1.kernel.params.system import LOG_TRUNC_100


def _get_daemon():
    from l3.cell.peers.l3a import get_daemon

    return get_daemon()


def _get_session(session_id: str):
    return _get_daemon().manager.get(session_id)


def _require_session(session_id: str):
    """Return (session, error_dict) — error_dict is None on success."""
    if not (session_id or "").strip():
        return None, {"success": False, "error": "session_id required"}
    s = _get_session(session_id)
    if not s:
        return None, {"success": False, "error": f"session not active: {session_id}"}
    return s, None


# ── ASK clarification (existing contract) ──


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


# ── Session contract ──


def handle_l3a_session_create(body: dict | None = None) -> dict:
    """POST /api/v2/l3a/sessions — create a new L3A session."""
    b = body or {}
    title = str(b.get("title") or "").strip()[:LOG_TRUNC_100]
    try:
        s = _get_daemon().manager.create(title=title)
    except Exception as e:
        return {"success": False, "error": f"session create failed: {e}"}
    return {"success": True, "session": s.info()}


def handle_l3a_session_list(body: dict | None = None) -> dict:
    """GET /api/v2/l3a/sessions — list active sessions."""
    try:
        sessions = _get_daemon().manager.list_active()
    except Exception as e:
        return {"success": False, "error": f"session list failed: {e}"}
    return {"success": True, "sessions": sessions, "count": len(sessions)}


def handle_l3a_session_get(body: dict | None = None, session_id: str = "") -> dict:
    """GET /api/v2/l3a/sessions/{session_id} — session detail."""
    s, err = _require_session(session_id)
    if err:
        return err
    try:
        todos = s.todos()
    except Exception:
        todos = {}
    info = s.info()
    info["todos"] = todos
    return {"success": True, "session": info}


def handle_l3a_session_messages(body: dict | None = None,
                                session_id: str = "") -> dict:
    """GET /api/v2/l3a/sessions/{session_id}/messages — cursor-paged history.

    Query params: cursor (last message id from previous page), limit
    (page size, capped at API_PAGE_MAX_LIMIT).
    """
    s, err = _require_session(session_id)
    if err:
        return err
    b = body or {}
    cursor = str(b.get("cursor") or "") or None
    try:
        limit = int(b.get("limit") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "limit must be an integer"}
    if limit <= 0:
        from l3.cell.peers.l3a.params import SESSION_PAGE_SIZE

        limit = SESSION_PAGE_SIZE
    limit = min(limit, API_PAGE_MAX_LIMIT)
    try:
        page = s.messages(cursor=cursor, limit=limit)
    except Exception as e:
        return {"success": False, "error": f"messages failed: {e}"}
    return {"success": True, "items": page.items, "next_cursor": page.cursor,
            "total": page.total}


def handle_l3a_session_send(body: dict | None = None,
                            session_id: str = "") -> dict:
    """POST /api/v2/l3a/sessions/{session_id}/send — send intent / continue."""
    s, err = _require_session(session_id)
    if err:
        return err
    b = body or {}
    text = str(b.get("text") or "").strip()
    if not text:
        return {"success": False, "error": "text required"}
    mode = str(b.get("mode") or "steer")
    try:
        r = s.prompt(text, mode=mode)
    except Exception as e:
        return {"success": False, "error": f"send failed: {e}"}
    if not r.get("success"):
        return r
    return {"success": True, "session_id": s.id, "result": r}


def handle_l3a_session_close(body: dict | None = None,
                             session_id: str = "") -> dict:
    """POST /api/v2/l3a/sessions/{session_id}/close — close and archive."""
    s, err = _require_session(session_id)
    if err:
        return err
    try:
        r = _get_daemon().manager.close(session_id)
    except Exception as e:
        return {"success": False, "error": f"close failed: {e}"}
    return {"success": True, "closed": r.get("success", True), "detail": r}


def handle_l3a_session_compress(body: dict | None = None,
                                session_id: str = "") -> dict:
    """POST /api/v2/l3a/sessions/{session_id}/compress — compress history.

    Body: keep (optional, number of trailing messages to keep).
    """
    s, err = _require_session(session_id)
    if err:
        return err
    b = body or {}
    try:
        keep = int(b.get("keep") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "keep must be an integer"}
    if keep <= 0:
        from l3.cell.peers.l3a.params import SESSION_COMPRESS_KEEP

        keep = SESSION_COMPRESS_KEEP
    try:
        r = s.compress(keep_last=keep)
    except Exception as e:
        return {"success": False, "error": f"compress failed: {e}"}
    return {"success": True, "compressed": r.get("success", True), "detail": r}
