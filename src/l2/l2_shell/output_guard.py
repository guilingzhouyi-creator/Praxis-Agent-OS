"""Output guard — intercept dangerous responses before showing to user."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_output_guard_callback = None


def set_output_guard(callback: Any) -> None:
    global _output_guard_callback
    _output_guard_callback = callback


def guard_output(agent_id: str, response: str) -> dict:
    if _output_guard_callback:
        try:
            return _output_guard_callback(agent_id, response)
        except Exception as e:
            logger.warning("output_guard: %s", e)
    return {"allowed": True, "response": response}
