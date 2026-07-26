"""Agent API handlers — extracted from api_handlers.py."""
from __future__ import annotations
from typing import Any
from l1.kernel.params.agent import DEFAULT_CELL_ID


def agent_list(body: dict | None = None) -> dict:
    from .selector import preselect
    return preselect()


def agent_select(body: dict) -> dict:
    from .selector import preselect
    agent_id = body.get("agent_id", "")
    roster = preselect()
    for a in roster.get("agents", []):
        if a.get("agent_id") == agent_id:
            return a
    return {"error": f"agent not found: {agent_id}"}


def agent_select_by(body: dict) -> dict:
    from .selector import preselect
    role = body.get("role", "")
    domain = body.get("domain", "")
    roster = preselect()
    for a in roster.get("agents", []):
        if role and a.get("role") != role:
            continue
        if domain and domain not in a.get("territory", []):
            continue
        return a
    return {"error": "no agent matched"}


def agent_preconnect(body: dict) -> dict:
    from .selector import preconnect
    cell_id = body.get("cell_id", DEFAULT_CELL_ID)
    agent_id = body.get("agent_id", "")
    message = body.get("message", "")
    if not agent_id:
        return {"error": "agent_id required"}
    return preconnect(cell_id, agent_id, message)


def agent_reachable(body: dict) -> dict:
    from .cell import get_cell
    agent_id = body.get("agent_id", "")
    if not agent_id:
        return {"error": "agent_id required"}
    cell = get_cell(DEFAULT_CELL_ID)
    return cell.agent_reachable(agent_id)


def agent_direct(body: dict) -> dict:
    from .cell import get_cell
    agent_id = body.get("agent_id", "")
    message = body.get("message", "")
    if not agent_id or not message:
        return {"error": "agent_id and message required"}
    from .central_security import get_center as _sec
    sec = _sec().check_all(action="direct_session", agent_id=agent_id, tool_name="direct_message")
    if not sec.get("allowed"):
        return {"error": "blocked by security", "security": sec}
    cell = get_cell(DEFAULT_CELL_ID)
    return cell.send_direct_message(agent_id, message)


def agent_direct_close(body: dict) -> dict:
    return {"success": True, "message": "Direct session is auto-managed via stdin queue"}


def agent_review_message(body: dict) -> dict:
    from .selector import set_llm_reviewer
    callback_str = body.get("callback", "")
    if callback_str:
        import importlib
        parts = callback_str.rsplit(".", 1)
        mod = importlib.import_module(parts[0])
        fn = getattr(mod, parts[1])
        set_llm_reviewer(fn)
        return {"success": True}
    return {"error": "callback required"}
