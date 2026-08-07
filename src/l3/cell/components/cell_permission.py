"""CellPermission — state-gated delegation permission for Cell.

Two-level state machine:
  Level 1 - Global  : _params.system.GLOBAL_SUBAGENT_ENABLED (system-wide on/off)
  Level 2 - Cell     : per-Spec state machine for each SubAgent:
      DISABLED      — spec invisible to all agents (default for all)
      CELL_ENABLED  — spec visible to agents whose ring >= spec.min_ring
      AGENT_GRANTED — spec visible to specific agents only (override)

Visibility semantics (state machine):
  DISABLED       → list_visible() excludes it, commission() blocks
  CELL_ENABLED   → list_visible() includes it for agent.ring >= min_ring
  AGENT_GRANTED  → list_visible() includes it only for granted agents

Global gate:
  _params.system.GLOBAL_SUBAGENT_ENABLED = False → all specs behave as DISABLED
  regardless of Cell-level state.  Emergency kill switch.

Usage:
  reg = SubAgentRegistry(cell_id="cell-1")
  reg.set_spec_state("security-auditor", SpecState.CELL_ENABLED, min_ring=2)
  reg.agent_grant("agent-writer", "security-auditor")
  reg.list_visible_specs("agent-reader")   # → [] (ring 1 < min_ring 2)
  reg.list_visible_specs("agent-writer")   # → ["security-auditor"]
"""

from __future__ import annotations

import logging
import threading
from enum import Enum, auto
from typing import Any

from l1.kernel import params as _params

logger = logging.getLogger(__name__)


class SpecState(Enum):
    """Per-Spec gate state in the Cell."""

    DISABLED = auto()  # Invisible to all agents.  Default.
    CELL_ENABLED = auto()  # Visible to agents with ring >= min_ring.
    AGENT_GRANTED = auto()  # Visible only to explicitly granted agents.


class SubAgentRegistry:
    """Per-Cell SubAgent delegation registry — state-gated visibility."""

    def __init__(self, cell_id: str):
        self.cell_id = cell_id
        self._specs: dict[str, dict] = {}
        """spec_name → {"state": SpecState, "min_ring": int, "granted_agents": set[str]}"""
        self._lock = threading.RLock()

    # ── Spec registration ─────────────────────────────────────────

    def register_spec(self, spec_name: str, min_ring: int = 1) -> None:
        """Register a spec with default DISABLED state."""
        with self._lock:
            if spec_name not in self._specs:
                self._specs[spec_name] = {
                    "state": SpecState.DISABLED,
                    "min_ring": min_ring,
                    "granted_agents": set(),
                }

    def set_spec_state(self, spec_name: str, state: SpecState, min_ring: int | None = None) -> dict:
        """Set gate state for a spec.  Returns {"success": bool}."""
        with self._lock:
            if spec_name not in self._specs:
                return {"success": False, "error": f"unknown spec: {spec_name}"}
            self._specs[spec_name]["state"] = state
            if min_ring is not None:
                self._specs[spec_name]["min_ring"] = min_ring
            logger.info("permission: %s → %s (min_ring=%s)", spec_name, state.name, self._specs[spec_name]["min_ring"])
            return {"success": True}

    def agent_grant(self, agent_id: str, spec_name: str) -> dict:
        """Grant a specific agent access to a spec (AGENT_GRANTED override).

        Also sets the spec state to AGENT_GRANTED automatically.
        """
        with self._lock:
            if spec_name not in self._specs:
                return {"success": False, "error": f"unknown spec: {spec_name}"}
            self._specs[spec_name]["granted_agents"].add(agent_id)
            self._specs[spec_name]["state"] = SpecState.AGENT_GRANTED
            logger.info("permission: %s granted %s", agent_id, spec_name)
            return {"success": True}

    def agent_revoke(self, agent_id: str, spec_name: str) -> dict:
        """Revoke a per-agent grant."""
        with self._lock:
            if spec_name not in self._specs:
                return {"success": False, "error": f"unknown spec: {spec_name}"}
            self._specs[spec_name]["granted_agents"].discard(agent_id)
            return {"success": True}

    # ── Visibility queries ────────────────────────────────────────

    def is_visible(self, spec_name: str, agent_id: str, agent_ring: int = 1) -> bool:
        """Check if a spec is visible to an agent (stateless query).

        Gate hierarchy:
          1. Global gate Off → False (emergency kill)
          2. Spec DISABLED → False
          3. Spec CELL_ENABLED → agent_ring >= min_ring
          4. Spec AGENT_GRANTED → agent_id in granted_agents
        """
        if not _params.system.GLOBAL_SUBAGENT_ENABLED:
            return False

        with self._lock:
            spec = self._specs.get(spec_name)
            if spec is None:
                return False
            state = spec["state"]
            if state == SpecState.DISABLED:
                return False
            if state == SpecState.CELL_ENABLED:
                return agent_ring >= spec["min_ring"]
            if state == SpecState.AGENT_GRANTED:
                return agent_id in spec["granted_agents"]
            return False

    def list_visible_specs(self, agent_id: str, agent_ring: int = 1) -> list[str]:
        """Return all spec names visible to an agent."""
        if not _params.system.GLOBAL_SUBAGENT_ENABLED:
            return []
        visible: list[str] = []
        with self._lock:
            for name, _spec in self._specs.items():
                if self.is_visible(name, agent_id, agent_ring):
                    visible.append(name)
        return sorted(visible)

    # ── Bulk load ─────────────────────────────────────────────────

    def load_from_config(self, config: dict[str, Any]) -> None:
        """Load spec states from a config dict.

        Config format:
            {"security-auditor": {"state": "CELL_ENABLED", "min_ring": 2},
             "fixer": {"state": "AGENT_GRANTED", "agents": ["agent-writer"]}}
        """
        for spec_name, rules in config.items():
            self.register_spec(spec_name, min_ring=rules.get("min_ring", 1))
            state_str = rules.get("state", "DISABLED")
            if state_str == "CELL_ENABLED":
                self.set_spec_state(spec_name, SpecState.CELL_ENABLED)
            elif state_str == "AGENT_GRANTED":
                for aid in rules.get("agents", []):
                    self.agent_grant(aid, spec_name)
            # DISABLED is the default — leave as-is

    # ── Stats ──────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return permission controller statistics as a dict."""
        with self._lock:
            return {
                "cell_id": self.cell_id,
                "global_enabled": _params.system.GLOBAL_SUBAGENT_ENABLED,
                "specs": {
                    name: {
                        "state": info["state"].name,
                        "min_ring": info["min_ring"],
                        "granted": len(info["granted_agents"]),
                    }
                    for name, info in self._specs.items()
                },
            }
