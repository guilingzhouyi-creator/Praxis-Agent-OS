"""Logging tool handlers."""

import logging

_logger = logging.getLogger("praxis.tool")


def log_info(args: dict, agent_id: str) -> dict:
    """Log an info message attributed to the agent; returns success dict."""
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    _logger.info("[%s] %s", agent_id, message)
    return {"success": True}


def log_error(args: dict, agent_id: str) -> dict:
    """Log an error message attributed to the agent; returns success dict."""
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    _logger.error("[%s] %s", agent_id, message)
    return {"success": True}
