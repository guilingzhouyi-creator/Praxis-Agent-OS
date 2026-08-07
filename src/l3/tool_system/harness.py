"""Harness mode runtime state — runtime override over the static config.

The pipeline reads ``get_harness_mode()`` on every execution. The value
resolves from the runtime override (set via API or L2 Shell) first, then
falls back to the ``harness.mode`` entry in ``config/praxis.yaml``, then to
the params default (governed). Switching to ``minimal`` requires an explicit
risk confirmation (``confirmed=True``) — the caller asserts user acceptance
of unguarded tool execution; the safety bottom line (constitution, gatechain,
sandbox, reference-channel recording) is enforced by the pipeline itself and
can never be disabled through this module.
"""

from __future__ import annotations

import threading
from typing import Any

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.tool import (
    HARNESS_MODE_DEFAULT,
    HARNESS_MODES,
)

_state: dict[str, Any] = {"mode": None}
_lock = threading.RLock()

BOTTOM_LINE = "constitution + gatechain + sandbox + reference-channel recording"


def get_harness_mode() -> str:
    """Return the effective harness mode (override → config → default)."""
    with _lock:
        override = _state["mode"]
    if override in HARNESS_MODES:
        return override
    static = str(get_tool_config("harness_mode", HARNESS_MODE_DEFAULT)).lower()
    return static if static in HARNESS_MODES else HARNESS_MODE_DEFAULT


def set_harness_mode(mode: str, confirmed: bool = False, source: str = "api") -> dict:
    """Switch the harness mode at runtime.

    Args:
        mode: one of HARNESS_MODES (governed / semi / minimal).
        confirmed: explicit user risk acceptance; REQUIRED for ``minimal``.
        source: caller identity ("api" / "shell" / ...) for the audit trail.

    Returns:
        dict with success flag, effective mode, and risk note when minimal.
    """
    mode = str(mode or "").lower()
    if mode not in HARNESS_MODES:
        return {"success": False, "error": f"invalid harness mode: {mode}", "modes": list(HARNESS_MODES)}
    if mode == "minimal" and not confirmed:
        return {
            "success": False,
            "error": "minimal mode requires explicit risk confirmation "
            "(confirm_risk=true): approval, rate limit and pool "
            "gates are disabled; constitution/gatechain/sandbox/"
            "recording stay enforced",
            "modes": list(HARNESS_MODES),
        }
    with _lock:
        _state["mode"] = mode
        _state["source"] = source
    return {
        "success": True,
        "mode": mode,
        "source": source,
        "note": None if mode != "minimal" else f"risk user-assumed; bottom line ({BOTTOM_LINE}) still enforced",
    }


def reset_harness_mode() -> dict:
    """Clear the runtime override; effective mode returns to static config."""
    with _lock:
        _state["mode"] = None
        _state["source"] = "config"
    return {"success": True, "mode": get_harness_mode(), "source": "config"}


def harness_status() -> dict:
    """Return the current mode plus the switchable matrix and bottom line."""
    with _lock:
        source = _state.get("source", "config")
    return {"mode": get_harness_mode(), "source": source, "modes": list(HARNESS_MODES), "bottom_line": BOTTOM_LINE}
