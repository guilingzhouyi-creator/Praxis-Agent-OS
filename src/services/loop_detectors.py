"""Loop detectors — exact fingerprint + coarse repeat detection for AgentLoop.

AtomCode-style fingerprinting with SHA256 for exact tool loop detection,
and name-based coarse repeat detection.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ToolLoopDetector:
    """Fingerprint-based exact tool loop detection.

    AtomCode-style: tracks consecutive identical (tool_name + args + result) calls.
    warn_threshold: log warning (default 3)
    stop_threshold: stop execution (default 4)
    """

    def __init__(self, warn_threshold: int = 3, stop_threshold: int = 4):
        self._fingerprints: list[str] = []
        self._warn = warn_threshold
        self._stop = stop_threshold

    def check(self, tool_name: str, args: dict, result: Any) -> str:
        """Check a tool call result. Returns 'continue', 'warn', or 'stop'."""
        fp = self._fingerprint(tool_name, args, result)
        self._fingerprints.append(fp)
        if len(self._fingerprints) < 2:
            return "continue"
        for n in (self._stop, self._warn):
            if len(self._fingerprints) >= n:
                recent = self._fingerprints[-n:]
                if len(set(recent)) == 1:
                    if n == self._stop:
                        logger.warning("tool loop STOP: %s repeated %d times", tool_name, n)
                        return "stop"
                    logger.warning("tool loop WARN: %s repeated %d times", tool_name, n)
                    return "warn"
        return "continue"

    def reset(self) -> None:
        self._fingerprints.clear()

    @staticmethod
    def _fingerprint(tool_name: str, args: dict, result: Any) -> str:
        arg_str = json.dumps(args, sort_keys=True, default=str)
        result_str = str(result)[:200] if result else ""
        raw = f"{tool_name}|{arg_str}|{result_str}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class CoarseRepeatDetector:
    """Detects repeated tool name regardless of args or results.

    AtomCode-style: MAX_REPEAT_ROUNDS=6 (stop), REPEAT_NUDGE_AT=3.
    Fires when the same tool_name appears consecutively.
    """

    def __init__(self, nudge_at: int = 3, stop_at: int = 6):
        self._nudge_at = nudge_at
        self._stop_at = stop_at
        self._names: list[str] = []

    def check(self, tool_name: str) -> str:
        self._names.append(tool_name)
        if len(self._names) < 2:
            return "continue"
        recent = self._names[-self._stop_at:]
        if len(recent) >= self._stop_at and len(set(recent)) == 1:
            logger.warning("coarse repeat STOP: %s repeated %d times", tool_name, self._stop_at)
            return "stop"
        if len(recent) >= self._nudge_at and len(set(recent)) == 1:
            logger.info("coarse repeat NUDGE: %s repeated %d times", tool_name, self._nudge_at)
            return "nudge"
        return "continue"

    def reset(self) -> None:
        self._names.clear()
