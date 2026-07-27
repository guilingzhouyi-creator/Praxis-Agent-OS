"""ToolMode — global read/write mode switch.

Modes:
  write (default): full tool access — all rings enabled
  read:            constrain to Ring 1 (read-only) — mutes Ring 2.5 + Ring 3

Uses the existing mute system (mute_ring/unmute_ring) so that every
is_muted() check automatically reflects the current mode.

Shell: /mode [read|write|toggle]
API:   GET /api/mode  PUT /api/mode {"mode": "read"|"write"}
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from l1.kernel.paths import get_paths as _gp
from l1.kernel.params.kernel import RING_2_5, RING_3

logger = logging.getLogger(__name__)

_MODE_PATH: str = ""
_MODE_LOCK = threading.Lock()
_MODE: str = "write"  # default: full access

_WRITE_RINGS = (RING_2_5, RING_3)


def _mode_path() -> str:
    global _MODE_PATH
    if not _MODE_PATH:
        _MODE_PATH = os.environ.get("PRAXIS_MODE_PATH", _gp().mode_state)
    return _MODE_PATH


def _save_mode() -> None:
    try:
        data = {"mode": _MODE}
        path = _mode_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning("tool_mode: save failed: %s", e)


def _load_mode() -> None:
    global _MODE
    path = _mode_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        mode = data.get("mode", "write")
        if mode in ("read", "write"):
            _MODE = mode
    except Exception as e:
        logger.warning("tool_mode: load failed: %s", e)


def _apply_mode() -> None:
    from .tool_system.tool_spec import mute_ring, unmute_ring
    if _MODE == "read":
        for r in _WRITE_RINGS:
            mute_ring(r)
    else:
        for r in _WRITE_RINGS:
            unmute_ring(r)


def get_mode() -> str:
    return _MODE


def set_mode(mode: str) -> dict:
    mode = mode.lower().strip()
    if mode not in ("read", "write", "toggle"):
        return {"success": False, "error": f"invalid mode: {mode}, expected read|write|toggle"}
    with _MODE_LOCK:
        global _MODE
        old = _MODE
        if mode == "toggle":
            mode = "read" if _MODE == "write" else "write"
        _MODE = mode
        _apply_mode()
        _save_mode()
    logger.info("tool_mode: %s → %s", old, _MODE)
    return {"success": True, "old": old, "new": _MODE}


def init_tool_mode() -> dict:
    _load_mode()
    _apply_mode()
    logger.info("tool_mode: initialized as '%s'", _MODE)
    return {"mode": _MODE}
