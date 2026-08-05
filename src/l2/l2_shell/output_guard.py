"""Output guard — intercept dangerous responses before showing to user."""

import logging
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_100

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
    """Pass agent output through the registered guard, or allow if none set.

    Returns ``{"safe": bool, "output": str, ...}``:
      - no guard / guard exception  → safe, original response
      - guard allows               → original response
      - guard blocks w/ replacement → replacement text
      - guard blocks w/o replacement → first 100 chars of original
    """
    if _output_guard_callback:
        try:
            result = _output_guard_callback(agent_id, response)
            if isinstance(result, dict):
                merged = dict(result)
                merged["safe"] = bool(result.get("safe", True))
                if not merged["safe"]:
                    replacement = result.get("replacement", "")
                    merged["output"] = replacement or response[:LOG_TRUNC_100]
                else:
                    merged["output"] = response
                return merged
        except Exception as e:
            logger.warning("output_guard: %s", e)
    return {"safe": True, "output": response}
