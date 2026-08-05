"""ThinkQuotaRegistry — central think-config registry with three-layer override.

Layers (higher priority wins):
  Global  —  defaults applied to all Cells and Agents
  Cell    —  overrides for all agents within a specific Cell
  Agent   —  per-agent override (highest priority)

Distribution modes:
  inherit     —  agent inherits Cell config; Cell inherits Global
  auto_balance —  Cell's total budget ÷ active agents, evenly split
  manual      —  each agent configured independently

Usage:
    from l3.scheduler.think_registry import get_think_registry
    reg = get_think_registry()
    reg.set_global(reasoning_effort="medium", thinking_budget=4096)
    reg.set_cell("cell-1", thinking_budget=8192, distribution="auto_balance")
    reg.set_agent("cell-1", "agent-1", reasoning_effort="high")
    cfg = reg.resolve("cell-1", "agent-1", active_agents=3)
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.api import THINK_MAX_BUDGET
from l1.kernel.params.system import (
    THINK_BUDGET_GLOBAL_DEFAULT,
    THINK_REASONING_DEFAULT,
)

logger = logging.getLogger(__name__)


# ── Keys used in config dicts ──

ALL_KEYS = frozenset({
    "reasoning_effort",   # "none" | "low" | "medium" | "high"
    "thinking_budget",    # int, tokens
    "max_tokens",         # int
    "temperature",        # float
    "model",              # str | None
})

DISTRIBUTION_MODES = frozenset({"inherit", "auto_balance", "manual"})


class ThinkQuotaRegistry:
    """Central think-config registry — thread-safe singleton."""

    def __init__(self):
        self._lock = threading.RLock()
        # Global defaults
        self._global: dict[str, Any] = {
            "reasoning_effort": THINK_REASONING_DEFAULT,
            "thinking_budget": THINK_BUDGET_GLOBAL_DEFAULT,
            "max_tokens": None,
            "temperature": None,
            "model": None,
        }
        # Per-Cell overrides: {cell_id: {config_dict, distribution}}
        self._cells: dict[str, dict] = {}
        # Per-Agent overrides: {f"{cell_id}.{agent_id}": config_dict}
        self._agents: dict[str, dict] = {}

    # ── Global layer ──────────────────────────────────────────────────────

    def set_global(self, **kwargs: Any) -> None:
        """Set global default think config keys."""
        with self._lock:
            for k, v in kwargs.items():
                if k in ALL_KEYS:
                    self._global[k] = v
                else:
                    logger.warning("think_registry: unknown key %s", k)

    def get_global(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._global)

    # ── Cell layer ────────────────────────────────────────────────────────

    def set_cell(self, cell_id: str, distribution: str = "inherit",
                 **config: Any) -> None:
        """Set Cell-level think config and distribution mode."""
        if distribution not in DISTRIBUTION_MODES:
            raise ValueError(f"invalid distribution mode: {distribution}, "
                             f"must be one of {DISTRIBUTION_MODES}")
        with self._lock:
            entry = self._cells.setdefault(cell_id, {})
            entry.update({k: v for k, v in config.items() if v is not None})
            entry["distribution"] = distribution

    def get_cell(self, cell_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._cells.get(cell_id, {}))

    def remove_cell(self, cell_id: str) -> bool:
        with self._lock:
            if cell_id in self._cells:
                del self._cells[cell_id]
                return True
            return False

    # ── Agent layer ───────────────────────────────────────────────────────

    def set_agent(self, cell_id: str, agent_id: str, **config: Any) -> None:
        """Set per-agent think config override (highest priority)."""
        key = f"{cell_id}.{agent_id}"
        with self._lock:
            entry = self._agents.setdefault(key, {})
            entry.update({k: v for k, v in config.items() if v is not None})

    def get_agent(self, cell_id: str, agent_id: str) -> dict[str, Any]:
        key = f"{cell_id}.{agent_id}"
        with self._lock:
            return dict(self._agents.get(key, {}))

    def remove_agent(self, cell_id: str, agent_id: str) -> bool:
        key = f"{cell_id}.{agent_id}"
        with self._lock:
            if key in self._agents:
                del self._agents[key]
                return True
            return False

    # ── Named strategy packs (shared with model_spec.strategies) ─────────

    def apply_strategy(self, scope: str, name: str, strategy_name: str) -> dict:
        """Apply a named model_spec strategy pack to a think scope.

        Scopes: "global", "cell" (name=cell_id), "agent" (name=cell.agent).
        Only reasoning_effort / thinking_budget keys are applied.
        """
        try:
            from l3.services.model_service import get_service as _ms
            defn = _ms().resolve_strategy_pack(strategy_name)
        except Exception:
            defn = None
        if not defn:
            return {"success": False,
                    "error": f"unknown or disabled strategy: {strategy_name}"}
        keys = {k: v for k, v in defn.items()
                if k in ("reasoning_effort", "thinking_budget")}
        if scope == "global":
            self.set_global(**keys)
        elif scope == "cell":
            self.set_cell(name, **keys)
        elif scope == "agent":
            cell_id, _, agent_id = name.partition(".")
            self.set_agent(cell_id, agent_id, **keys)
        else:
            return {"success": False, "error": f"unknown scope: {scope}"}
        return {"success": True, "scope": scope, "name": name,
                "strategy": strategy_name, "applied": list(keys)}

    def clear_strategy(self, scope: str, name: str = "") -> dict:
        """Remove a strategy override from a think scope (restore defaults)."""
        if scope == "global":
            self.set_global(reasoning_effort=THINK_REASONING_DEFAULT,
                            thinking_budget=THINK_BUDGET_GLOBAL_DEFAULT)
        elif scope == "cell":
            with self._lock:
                self._cells.pop(name, None)
        elif scope == "agent":
            cell_id, _, agent_id = name.partition(".")
            self.remove_agent(cell_id, agent_id)
        else:
            return {"success": False, "error": f"unknown scope: {scope}"}
        return {"success": True, "scope": scope, "name": name,
                "restored": "defaults"}

    # ── Resolve ───────────────────────────────────────────────────────────

    def resolve(self, cell_id: str, agent_id: str,
                active_agents: int = 1,
                agent_model_config: dict | None = None) -> dict[str, Any]:
        """Merge three layers: agent > cell > global, clamped to [0, max_budget].

        In *auto_balance* mode, if the Cell has a ``thinking_budget``, it
        is divided by *active_agents* before applying any agent override.

        Clamping:
          - ``thinking_budget``  clamped to ``[0, think.max_budget]``
          - ``reasoning_effort`` clamped to ``think.max_reasoning`` rank

        Args:
            cell_id: The Cell identifier.
            agent_id: The Agent identifier.
            active_agents: Number of active agents in the Cell (for auto_balance).
            agent_model_config: Runtime AgentInfo.model_config (highest priority).

        Returns:
            Effective config dict with only non-None values.
        """
        # Read upper bounds from settings_center
        try:
            from l3.config.settings_center import get_center
            center = get_center()
            max_budget = center.get("think.max_budget", THINK_MAX_BUDGET)
            max_reasoning = center.get("think.max_reasoning", "high")
        except Exception:
            max_budget = THINK_MAX_BUDGET
            max_reasoning = "high"

        _EFFORT_RANK = {"none": 0, "low": 1, "medium": 2,
                        "high": 3, "xhigh": 4, "max": 5}
        max_rank = _EFFORT_RANK.get(max_reasoning, 5)

        with self._lock:
            # Start with global
            merged = dict(self._global)

            # Cell layer
            cell_entry = self._cells.get(cell_id, {})
            dist = cell_entry.get("distribution", "inherit")
            cell_cfg = {k: v for k, v in cell_entry.items()
                        if k != "distribution" and v is not None}
            merged.update(cell_cfg)

            # Handle auto_balance: split Cell's thinking_budget
            if dist == "auto_balance" and active_agents > 1:
                budget = merged.get("thinking_budget", 0)
                if budget > 0:
                    merged["thinking_budget"] = max(1, budget // active_agents)

            # Agent layer from registry
            agent_key = f"{cell_id}.{agent_id}"
            agent_entry = self._agents.get(agent_key, {})
            merged.update({k: v for k, v in agent_entry.items() if v is not None})

            # Agent layer from runtime (Info.model_config) — highest
            if agent_model_config:
                merged.update(agent_model_config)

        # Strip None values
        result = {k: v for k, v in merged.items() if v is not None}

        # ── Clamp: lower bound ──
        if "thinking_budget" in result:
            result["thinking_budget"] = max(0, result["thinking_budget"])

        # ── Clamp: upper bound ──
        if result.get("thinking_budget", 0) > max_budget:
            result["thinking_budget"] = max_budget

        # ── Clamp: reasoning_effort rank ──
        if "reasoning_effort" in result:
            current_rank = _EFFORT_RANK.get(result["reasoning_effort"], 0)
            if current_rank > max_rank:
                result["reasoning_effort"] = max_reasoning

        return result

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            return {
                "global": dict(self._global),
                "cells": {cid: dict(entry)
                          for cid, entry in self._cells.items()},
                "agents": {key: dict(cfg)
                           for key, cfg in self._agents.items()},
                "cell_count": len(self._cells),
                "agent_overrides": len(self._agents),
            }

    def reset(self) -> None:
        """Reset all overrides (keeps global defaults)."""
        with self._lock:
            self._cells.clear()
            self._agents.clear()


# ── Singleton ────────────────────────────────────────────────────────────────

_registry: ThinkQuotaRegistry | None = None


def get_think_registry() -> ThinkQuotaRegistry:
    global _registry
    if _registry is None:
        _registry = ThinkQuotaRegistry()
    return _registry


def reset_think_registry() -> None:
    global _registry
    if _registry:
        _registry.reset()
    _registry = None
