"""Logging tools - 4 kinds.

log_debug, log_info, log_warn, log_error
"""

import logging
import sys
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R

logger = logging.getLogger(__name__)


def _cmd_log_debug(args: dict, agent_id: str) -> dict:
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    logger.debug("[%s] %s", agent_id, message)
    return {"success": True, "data": {"level": "DEBUG", "message": message, "logged": True}}


def _cmd_log_info(args: dict, agent_id: str) -> dict:
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    logger.info("[%s] %s", agent_id, message)
    _push_log("info", agent_id, message)
    return {"success": True, "data": {"level": "INFO", "message": message, "logged": True}}


def _cmd_log_warn(args: dict, agent_id: str) -> dict:
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    logger.warning("[%s] %s", agent_id, message)
    _push_log("warn", agent_id, message)
    return {"success": True, "data": {"level": "WARN", "message": message, "logged": True}}


def _cmd_log_error(args: dict, agent_id: str) -> dict:
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    logger.error("[%s] %s", agent_id, message)
    _push_log("error", agent_id, message)
    return {"success": True, "data": {"level": "ERROR", "message": message, "logged": True}}


def _push_log(level: str, agent_id: str, message: str) -> None:
    try:
        from kernel import push_event
        push_event("terminal_output", {
            "stream": "stdout" if level in ("info", "debug") else "stderr",
            "line": f"[{level.upper()}] [{agent_id}] {message}",
        })
    except Exception as e:
            logger.warning("tools_logging: %s", e)


def register_tools() -> None:
    register(ToolSpec(name="log_debug", description="Write DEBUG level log",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("message", "string", required=True)],
                      handler=_cmd_log_debug))
    register(ToolSpec(name="log_info", description="Write INFO level log",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("message", "string", required=True)],
                      handler=_cmd_log_info))
    register(ToolSpec(name="log_warn", description="Write WARN level log",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("message", "string", required=True)],
                      handler=_cmd_log_warn))
    register(ToolSpec(name="log_error", description="Write ERROR level log",
                      category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("message", "string", required=True)],
                      handler=_cmd_log_error))