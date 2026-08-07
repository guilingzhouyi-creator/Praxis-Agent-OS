"""Loop detectors — exact fingerprint + coarse repeat detection for AgentLoop.

AtomCode-style fingerprinting with SHA256 for exact tool loop detection,
and name-based coarse repeat detection.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from l1.kernel.params.system import HASH_TRUNC_LONG, LOG_TRUNC_200

logger = logging.getLogger(__name__)


def _read_cfg(key: str, default: int) -> int:
    """Read an integer from settings center, falling back to default."""
    try:
        from l3.config.settings_center import get_center

        return get_center().get_int(key, default)
    except Exception:
        return default


class ToolLoopDetector:
    """Fingerprint-based exact tool loop detection.

    AtomCode-style: tracks consecutive identical (tool_name + args + result) calls.
    Thresholds read from settings center (configurable via praxis.yaml or API).

    Supports cross-instance persistence: when cell_id is set, fingerprints
    are persisted to the Cell's L2 cache so that subsequent AgentLoop
    instances can detect loops across separate run() calls.
    """

    def __init__(
        self,
        warn_threshold: int | None = None,
        stop_threshold: int | None = None,
        cell_id: str = "",
        agent_id: str = "",
    ):
        self._fingerprints: list[str] = []
        self._warn = warn_threshold if warn_threshold is not None else _read_cfg("loop.tool_repeat_warn", 3)
        self._stop = stop_threshold if stop_threshold is not None else _read_cfg("loop.tool_repeat_stop", 4)
        self._cell_id = cell_id
        self._agent_id = agent_id
        # Load recent fingerprints from CellCache for cross-instance continuity
        if cell_id and agent_id:
            self._load_history()

    def check(self, tool_name: str, args: dict, result: Any) -> str:
        """Check a tool call result. Returns 'continue', 'warn', or 'stop'."""
        fp = self._fingerprint(tool_name, args, result)
        self._fingerprints.append(fp)
        # Persist fingerprint to CellCache for cross-instance detection
        if self._cell_id and len(self._fingerprints) > 0:
            self._persist_fingerprint(fp)
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
        """Clear recorded fingerprints."""
        self._fingerprints.clear()

    def _load_history(self) -> None:
        """Load recent tool fingerprints from CellCache."""
        try:
            from .cell import get_cell as _get_cell

            cell = _get_cell(self._cell_id)
            hits = cell.cache.search(f"fp:{self._agent_id}:", limit=10)
            for h in hits:
                try:
                    fp_data = json.loads(h.summary.split("|", 1)[1]) if "|" in h.summary else ""
                    if fp_data and isinstance(fp_data, str):
                        self._fingerprints.append(fp_data)
                except Exception:
                    continue
        except Exception:
            logger.debug("loop_detectors: loop detect failed")

    def _persist_fingerprint(self, fp: str) -> None:
        """Persist a fingerprint to CellCache so other instances can see it."""
        try:
            from .cell import get_cell as _get_cell

            cell = _get_cell(self._cell_id)
            key = f"fp:{self._agent_id}:{fp}"
            cell.cache.inject(
                key=key,
                value=fp,
                summary=f"fp|{fp}",
                agent_id=self._agent_id,
                entry_type="loop_fingerprint",
                importance=0.2,
            )
        except Exception:
            logger.debug("loop_detectors: fingerprint persist failed")

    @staticmethod
    def _fingerprint(tool_name: str, args: dict, result: Any) -> str:
        arg_str = json.dumps(args, sort_keys=True, default=str)
        result_str = str(result)[:LOG_TRUNC_200] if result else ""
        raw = f"{tool_name}|{arg_str}|{result_str}"
        return hashlib.sha256(raw.encode()).hexdigest()[:HASH_TRUNC_LONG]


class CoarseRepeatDetector:
    """Detects repeated tool name regardless of args or results.

    AtomCode-style: MAX_REPEAT_ROUNDS=6 (stop), REPEAT_NUDGE_AT=3.
    Fires when the same tool_name appears consecutively.

    Supports cross-instance persistence: when cell_id is set, tool name
    history is persisted to CellCache for cross-run detection.
    """

    def __init__(self, nudge_at: int | None = None, stop_at: int | None = None, cell_id: str = "", agent_id: str = ""):
        self._nudge_at = nudge_at if nudge_at is not None else _read_cfg("loop.coarse_repeat_nudge", 3)
        self._stop_at = stop_at if stop_at is not None else _read_cfg("loop.coarse_repeat_stop", 6)
        self._names: list[str] = []
        self._cell_id = cell_id
        self._agent_id = agent_id
        if cell_id and agent_id:
            self._load_history()

    def check(self, tool_name: str) -> str:
        """Check a tool name; returns 'continue', 'nudge', or 'stop'."""
        self._names.append(tool_name)
        if self._cell_id:
            self._persist_name(tool_name)
        if len(self._names) < 2:
            return "continue"
        recent = self._names[-self._stop_at :]
        if len(recent) >= self._stop_at and len(set(recent)) == 1:
            logger.warning("coarse repeat STOP: %s repeated %d times", tool_name, self._stop_at)
            return "stop"
        if len(recent) >= self._nudge_at and len(set(recent)) == 1:
            logger.info("coarse repeat NUDGE: %s repeated %d times", tool_name, self._nudge_at)
            return "nudge"
        return "continue"

    def reset(self) -> None:
        """Clear recorded tool name history."""
        self._names.clear()

    def _load_history(self) -> None:
        """Load recent tool name history from CellCache."""
        try:
            from .cell import get_cell as _get_cell

            cell = _get_cell(self._cell_id)
            hits = cell.cache.search(f"coarse:{self._agent_id}:", limit=10)
            for h in hits:
                try:
                    name = h.summary.split("|", 1)[1] if "|" in h.summary else ""
                    if name:
                        self._names.append(name)
                except Exception:
                    continue
        except Exception:
            logger.debug("loop_detectors: coarse detect failed")

    def _persist_name(self, tool_name: str) -> None:
        """Persist tool name to CellCache."""
        try:
            from .cell import get_cell as _get_cell

            cell = _get_cell(self._cell_id)
            cell.cache.inject(
                key=f"coarse:{self._agent_id}:{tool_name}",
                value=tool_name,
                summary=f"coarse|{tool_name}",
                agent_id=self._agent_id,
                entry_type="loop_coarse",
                importance=0.2,
            )
        except Exception:
            logger.debug("loop_detectors: coarse name persist failed")
