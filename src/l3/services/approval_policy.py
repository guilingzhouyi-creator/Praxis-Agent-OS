"""ApprovalPolicy — three-layer danger level overrides: Cell > Agent > Global.

Global danger levels come from GATECHAIN_DANGER_LEVELS in params/kernel.py.
Cell and Agent overrides can lower or raise the danger level for specific tools.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.kernel import GATECHAIN_DANGER_LEVELS

logger = logging.getLogger(__name__)


class ApprovalPolicy:
    """Three-layer danger level override: Cell > Agent > Global.

    resolve(cell_id, agent_id, tool_name) → effective danger level.

    set_cell_danger(cell_id, tool_name, level)     → Cell override
    set_agent_danger(cell_id, agent_id, tool, lvl)  → Agent override
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._cell_overrides: dict[str, dict[str, int]] = {}    # {cell_id: {tool: danger}}
        self._agent_overrides: dict[str, dict[str, int]] = {}   # {f"{cell}.{agent}": {tool: danger}}

    def resolve(self, cell_id: str, agent_id: str, tool_name: str) -> int:
        """Resolve effective danger level: Agent > Cell > Global."""
        agent_key = f"{cell_id}.{agent_id}"
        with self._lock:
            if agent_key in self._agent_overrides and tool_name in self._agent_overrides[agent_key]:
                return self._agent_overrides[agent_key][tool_name]
            if cell_id in self._cell_overrides and tool_name in self._cell_overrides[cell_id]:
                return self._cell_overrides[cell_id][tool_name]
        return GATECHAIN_DANGER_LEVELS.get(tool_name, 1)

    def set_cell_danger(self, cell_id: str, tool_name: str, level: int) -> None:
        with self._lock:
            self._cell_overrides.setdefault(cell_id, {})[tool_name] = level

    def set_agent_danger(self, cell_id: str, agent_id: str, tool_name: str, level: int) -> None:
        with self._lock:
            key = f"{cell_id}.{agent_id}"
            self._agent_overrides.setdefault(key, {})[tool_name] = level

    def get_cell_dangers(self, cell_id: str) -> dict[str, int]:
        with self._lock:
            return dict(self._cell_overrides.get(cell_id, {}))

    def get_agent_dangers(self, cell_id: str, agent_id: str) -> dict[str, int]:
        with self._lock:
            key = f"{cell_id}.{agent_id}"
            return dict(self._agent_overrides.get(key, {}))

    def stats(self) -> dict:
        with self._lock:
            return {
                "cell_overrides": {c: len(t) for c, t in self._cell_overrides.items()},
                "agent_overrides": {k: len(t) for k, t in self._agent_overrides.items()},
            }


_policy: ApprovalPolicy | None = None


def get_policy() -> ApprovalPolicy:
    global _policy
    if _policy is None:
        _policy = ApprovalPolicy()
    return _policy


def reset_policy() -> None:
    global _policy
    _policy = None
