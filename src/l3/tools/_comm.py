"""Communication tool handlers.

ask_user / confirm are context-aware:
  - L3A session context (agent_id == L3A_AGENT_ID): full awaiting flow —
    the question is routed to the active session's AskState and the
    AgentLoop breaks on the awaiting_input marker; the user answers in the
    chat window/command/REST and execution resumes.
  - Cell peer agents (batch/headless): non-blocking degrade mode — the
    question is logged to the pending-question queue and the LLM is
    instructed to continue with best-effort defaults. Cell execution flow
    is never blocked waiting for a user that is not online.
"""

from __future__ import annotations

import json
import time

try:
    from l4.notify import send_notification
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

_DEGRADE_INSTRUCTION = (
    "No interactive user channel is available in this execution context. "
    "Do NOT wait or retry this call. Continue with best-effort defaults; "
    "the question has been logged for the user to answer later."
)


def _route_to_l3a(question: str, options: list, agent_id: str) -> dict | None:
    """Route a clarification question into the active L3A session's awaiting flow.

    Returns the awaiting response (AgentLoop breaks on it) or None when no
    L3A session context is available.
    """
    try:
        from l1.kernel.params.agent import L3A_AGENT_ID
        if agent_id != L3A_AGENT_ID:
            return None
        from l3.cell.peers.l3a import get_daemon
        mgr = get_daemon().manager
        best = None
        with mgr._lock:
            for s in mgr._sessions.values():
                if s.status == "active" and (
                    best is None or s.last_active_at > best.last_active_at
                ):
                    best = s
        if best is None:
            return None
        from l3.cell.peers.l3a.ask import ask_handler
        raw = {"question": question}
        if options:
            raw["options"] = [str(o) for o in options]
        return ask_handler(best, {"questions": [raw]})
    except Exception:
        return None


def _log_pending_question(question: str, agent_id: str) -> None:
    """Persist a pending clarification for a headless agent (degrade mode)."""
    try:
        from l1.kernel.params.agent import L3A_AGENT_ID
        from l3.memory.central_memory import get_l3a_memory
        mem = get_l3a_memory()
        mem.remember(
            agent_id=L3A_AGENT_ID,
            entry_type="user_pending_question",
            content=json.dumps({
                "agent_id": agent_id,
                "question": question,
                "asked_at": time.time(),
            }, default=str),
            tags=["l3a", "pending_question", agent_id],
            importance=0.7,
            ring=2,
        )
    except Exception:
        pass


def pending_questions(agent_id: str = "") -> list[dict]:
    """Query the pending-question queue (questions raised by headless agents)."""
    try:
        from l1.kernel.params.agent import L3A_AGENT_ID
        from l3.memory.central_memory import get_l3a_memory
        mem = get_l3a_memory()
        entries = mem.recall(
            agent_id=L3A_AGENT_ID,
            entry_type="user_pending_question",
            tag=agent_id or "",
            rings=[2],
            limit=50,
        )
        out = []
        for e in entries:
            try:
                data = json.loads(e.content)
                out.append(data)
            except Exception:
                continue
        return out
    except Exception:
        return []


def ask_user(args: dict, agent_id: str) -> dict:
    question = args.get("question", "")
    if not question:
        return {"success": False, "error": "question is required"}
    options = args.get("options", []) or []
    l3a_result = _route_to_l3a(question, options, agent_id)
    if l3a_result:
        return l3a_result
    _log_pending_question(question, agent_id)
    if HAS_NOTIFY:
        send_notification(agent_id, f"[ASK] {question}")
    return {
        "success": True,
        "mode": "notify_only",
        "question": question,
        "pending": True,
        "instruction": _DEGRADE_INSTRUCTION,
    }


def confirm(args: dict, agent_id: str) -> dict:
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    l3a_result = _route_to_l3a(message, [], agent_id)
    if l3a_result:
        return l3a_result
    _log_pending_question(message, agent_id)
    if HAS_NOTIFY:
        send_notification(agent_id, f"[CONFIRM] {message}")
    return {
        "success": True,
        "mode": "notify_only",
        "message": message,
        "pending": True,
        "instruction": _DEGRADE_INSTRUCTION,
    }


def notify(args: dict, agent_id: str) -> dict:
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    if HAS_NOTIFY:
        send_notification(agent_id, f"[NOTIFY] {message}")
    return {"success": True, "message": message}


def user_delete(args: dict, agent_id: str) -> dict:
    """RING_3: Delete a user account. Requires G5 witness approval."""
    user_id = args.get("user_id", "")
    if not user_id:
        return {"success": False, "error": "user_id is required"}
    return {"success": True, "message": f"user {user_id} deletion requested (approval gate)"}
