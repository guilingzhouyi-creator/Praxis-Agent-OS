"""Communication and interaction tools - 6 kinds.

ask_user, confirm, notify, show_message, show_diff, show_progress
"""

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R

# Simulated user interaction queue
_pending_questions: list[dict] = []


def _cmd_ask_user(args: dict, agent_id: str) -> dict:
    """Ask user a question, wait for answer."""
    question = args.get("question", "")
    if not question:
        return {"success": False, "error": "question is required"}
    q = {
        "id": f"q-{int(time.time())}",
        "agent_id": agent_id,
        "question": question,
        "type": args.get("type", "text"),
        "options": args.get("options", []),
        "created_at": time.time(),
        "answered": False,
    }
    _pending_questions.append(q)
    # Push via SSE to UI
    try:
        from kernel import push_event
        push_event("ask_user", q)
    except Exception as e:
            logger.warning("tools_comm: %s", e)
    return {
        "success": True,
        "data": {
            "question_id": q["id"],
            "question": question,
            "status": "pending",
            "note": "等待用户在 UI 中回答",
        },
    }


def _cmd_confirm(args: dict, agent_id: str) -> dict:
    """Request user confirmation."""
    action = args.get("action", "")
    detail = args.get("detail", "")
    if not action:
        return {"success": False, "error": "action is required"}
    q = {
        "id": f"cf-{int(time.time())}",
        "agent_id": agent_id,
        "action": action,
        "detail": detail,
        "type": "confirm",
        "created_at": time.time(),
        "answered": False,
    }
    _pending_questions.append(q)
    try:
        from kernel import push_event
        push_event("ask_user", q)
    except Exception as e:
            logger.warning("tools_comm: %s", e)
    return {"success": True, "data": {"confirm_id": q["id"], "action": action, "status": "pending"}}


def _cmd_notify(args: dict, agent_id: str) -> dict:
    """Send notification to user."""
    message = args.get("message", "")
    level = args.get("level", "info")
    if not message:
        return {"success": False, "error": "message is required"}
    try:
        from kernel import push_event
        push_event("notification", {
            "agent_id": agent_id, "message": message, "level": level, "ts": time.time(),
        })
    except Exception as e:
            logger.warning("tools_comm: %s", e)
    return {"success": True, "data": {"message": message, "level": level, "sent": True}}


def _cmd_show_message(args: dict, agent_id: str) -> dict:
    """Display message in UI."""
    message = args.get("message", "")
    title = args.get("title", "Agent OS")
    level = args.get("level", "info")
    if not message:
        return {"success": False, "error": "message is required"}
    try:
        from kernel import push_event
        push_event("show_message", {
            "agent_id": agent_id, "title": title, "message": message, "level": level,
        })
    except Exception as e:
            logger.warning("tools_comm: %s", e)
    return {"success": True, "data": {"title": title, "message": message, "level": level}}


def _cmd_show_diff(args: dict, agent_id: str) -> dict:
    """Show file diff in UI."""
    path = args.get("path", "")
    old_content = args.get("old_content", "")
    new_content = args.get("new_content", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        from kernel import push_event
        push_event("show_diff", {
            "agent_id": agent_id, "path": path,
            "old": old_content[:500], "new": new_content[:500],
        })
    except Exception as e:
            logger.warning("tools_comm: %s", e)
    return {"success": True, "data": {"path": path, "diff_shown": True}}


def _cmd_show_progress(args: dict, agent_id: str) -> dict:
    """Show progress bar in UI."""
    percent = args.get("percent", 0)
    message = args.get("message", "")
    percent = max(0, min(100, percent))
    try:
        from kernel import push_event
        push_event("show_progress", {
            "agent_id": agent_id, "percent": percent, "message": message,
        })
    except Exception as e:
            logger.warning("tools_comm: %s", e)
    return {"success": True, "data": {"percent": percent, "message": message}}


def register_tools() -> None:
    register(ToolSpec(name="ask_user", description="Ask user a question and wait for reply",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("question", "string", required=True),
                                  ParamSpec("type", "string", default="text"),
                                  ParamSpec("options", "list", default=[])],
                      handler=_cmd_ask_user))
    register(ToolSpec(name="confirm", description="Request user confirmation for an action",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("action", "string", required=True),
                                  ParamSpec("detail", "string", default="")],
                      handler=_cmd_confirm))
    register(ToolSpec(name="notify", description="Send notification to user",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("message", "string", required=True),
                                  ParamSpec("level", "string", default="info")],
                      handler=_cmd_notify))
    register(ToolSpec(name="show_message", description="Show message in the UI",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("message", "string", required=True),
                                  ParamSpec("title", "string", default="Agent OS"),
                                  ParamSpec("level", "string", default="info")],
                      handler=_cmd_show_message))
    register(ToolSpec(name="show_diff", description="Show file diff in the UI",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True),
                                  ParamSpec("old_content", "string", default=""),
                                  ParamSpec("new_content", "string", default="")],
                      handler=_cmd_show_diff))
    register(ToolSpec(name="show_progress", description="Show progress bar in the UI",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("percent", "int", default=0),
                                  ParamSpec("message", "string", default="")],
                      handler=_cmd_show_progress))