"""Output guard — intercept dangerous responses before showing to user."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_output_guard_callback = None


def set_output_guard(callback: Any) -> None:
    """Register a callback that intercepts agent responses before display.

    The callback receives ``(agent_id: str, response: str)`` and should return
    ``{"allowed": bool, "response": str}``.  If no callback is registered,
    all responses pass through unchanged.
    """
    global _output_guard_callback
    _output_guard_callback = callback


def guard_output(agent_id: str, response: str) -> dict:
    """Pass agent output through the registered guard, or allow if none set."""
    if _output_guard_callback:
        try:
            return _output_guard_callback(agent_id, response)
        except Exception as e:
            logger.warning("output_guard: %s", e)
    return {"allowed": True, "response": response}
