"""Settings center — unified key-value config aggregating three layers.

Layer priority (higher wins):
  L1 — Default:  kernel/params.py compile-time constants
  L2 — Config:   praxis.yaml boot-time configuration
  L3 — Runtime:  .praxis_settings.json API-written overrides

Read path:     L3 > L2 > L1
Write path:    L3 only (never writes to params.py or praxis.yaml)

Usage:
  from l3.config.settings_center import get_center
  center = get_center()
  center.get("approval.danger_threshold")   # → 3 (from L3 or L2 or L1)
  center.set("approval.danger_threshold", 5) # → writes to L3, immediate effect
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from l1.kernel.params.agent import (
    LOOP_MAX_ATTEMPTS,
    LOOP_TOOL_REPEAT_WARN,
    LOOP_COARSE_REPEAT_NUDGE,
    AGENT_LOOP_DEFAULT_TIMEOUT,
)
from l1.kernel.params.kernel import GATECHAIN_REPEAT_THRESHOLD, GATECHAIN_HIGH_FREQ_THRESHOLD
from l1.kernel.params.system import PMU_SNAPSHOT_INTERVAL, LOG_TRUNC_500, CACHE_DEFAULT_TTL
from l1.kernel.paths import get_paths as _gp

logger = logging.getLogger(__name__)

# Default L1 values (mirrored from kernel/params.py for runtime-overridable keys)
# These are the "factory defaults" — params.py is the authoritative source at boot.
_L1_DEFAULTS: dict[str, Any] = {
    # ── Approval gate ──
    "approval.danger_threshold": 3,

    # ── Memory budgets ──
    "memory.working_budget": 8192,
    "memory.short_budget": 32768,
    "memory.long_budget": 131072,
    "memory.working_ttl": 1800,
    "memory.short_ttl": 86400,

    # ── Scout pool ──
    "scout.max_total": 16,
    "scout.max_per_agent": 4,

    # ── Agent terminal ──
    "terminal.max_workers": 4,

    # ── Scheduler ──
    "scheduler.default_quantum": 15.0,
    "scheduler.max_preempt": PMU_SNAPSHOT_INTERVAL,

    # ── Cache ──
    "cache.max_entries": LOG_TRUNC_500,
    "cache.ttl": CACHE_DEFAULT_TTL,

    # ── LLM ──
    "llm.max_tokens": 2048,
    "llm.temperature": 0.3,
    "llm.reasoning_effort": "none",
    "llm.thinking_budget": 0,

    # ── Think quota (ThinkQuotaRegistry cap clamp) ──
    "think.max_budget": 32768,
    "think.max_reasoning": "high",
    "think.profiles": {},

    # ── GateChain ──
    "gatechain.risk_warn_threshold": 6.0,
    "gatechain.escalation_danger": 4,
    "gatechain.repeat_threshold": GATECHAIN_REPEAT_THRESHOLD,
    "gatechain.high_freq_threshold": GATECHAIN_HIGH_FREQ_THRESHOLD,

    # ── TaskBus (webhook dispatch) ──
    "task_bus.webhook_retries": LOOP_MAX_ATTEMPTS,
    "task_bus.webhook_timeout": 15,
    "task_bus.webhook_backoff": "1.0,4.0,10.0",

    # ── CronScheduler ──
    "cron.check_interval": PMU_SNAPSHOT_INTERVAL,
    "cron.max_entries": 50,

    # ── Loop control (AgentLoop self-correction) ──
    "loop.max_steps": 10,
    "loop.timeout": AGENT_LOOP_DEFAULT_TIMEOUT,
    "loop.max_iterations": 50,
    "loop.max_attempts": LOOP_MAX_ATTEMPTS,
    "loop.continuation_nudge": True,
    "loop.tool_repeat_warn": LOOP_TOOL_REPEAT_WARN,
    "loop.tool_repeat_stop": 4,
    "loop.coarse_repeat_nudge": LOOP_COARSE_REPEAT_NUDGE,
    "loop.coarse_repeat_stop": 6,
    "loop.verify_cadence": True,
}


class SettingsCenter:
    """Three-layer settings aggregator.

    Thread-safe. L3 writes are persisted to .praxis_settings.json.
    """

    def __init__(self, persist_path: str = ""):
        self._lock = threading.RLock()
        self._l1: dict[str, Any] = dict(_L1_DEFAULTS)
        self._l2: dict[str, Any] = {}   # loaded from praxis.yaml at boot
        self._l3: dict[str, Any] = {}    # loaded/saved to .praxis_settings.json
        self._persist_path = persist_path or (
            _gp().settings_file
        )

    # ── Three-layer load ──

    def load_l2(self, config: dict[str, Any]) -> None:
        """Load L2 config (called by boot.py after reading praxis.yaml)."""
        flat = self._flatten(config)
        with self._lock:
            self._l2.update(flat)

    def load_l3(self) -> None:
        """Load L3 runtime settings from .praxis_settings.json."""
        path = Path(self._persist_path)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                with self._lock:
                    self._l3.update(data)
            except Exception as e:
                logger.warning("settings_center: failed to load L3: %s", e)

    def _save_l3(self) -> None:
        """Persist L3 to disk."""
        try:
            path = Path(self._persist_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = dict(self._l3)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("settings_center: failed to save L3: %s", e)

    # ── Read (L3 > L2 > L1) ──

    def get(self, key: str, default: Any = None) -> Any:
        """Read a setting with L3 > L2 > L1 priority."""
        with self._lock:
            if key in self._l3:
                return self._l3[key]
            if key in self._l2:
                return self._l2[key]
            return self._l1.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        val = self.get(key, default)
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        val = self.get(key, default)
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    # ── Write (L3 only) ──

    def set(self, key: str, value: Any) -> dict:
        """Write a runtime override. Persists to .praxis_settings.json."""
        with self._lock:
            self._l3[key] = value
            self._save_l3()
        logger.info("settings_center: set %s = %s", key, value)
        return {"success": True, "key": key, "value": value}

    def set_many(self, pairs: dict[str, Any]) -> dict:
        """Batch write runtime overrides."""
        with self._lock:
            self._l3.update(pairs)
            self._save_l3()
        logger.info("settings_center: batch set %d keys", len(pairs))
        return {"success": True, "count": len(pairs)}

    # ── Query ──

    def all(self) -> dict[str, Any]:
        """Return all resolved settings (L3 > L2 > L1 merged)."""
        result = dict(self._l1)
        with self._lock:
            result.update(self._l2)
            result.update(self._l3)
        return result

    def diff(self) -> dict:
        """Show which settings deviate from L1 defaults."""
        overrides = {}
        with self._lock:
            for k, v in self._l3.items():
                if k in self._l1 and v != self._l1[k]:
                    overrides[k] = {"default": self._l1[k], "current": v}
                elif k not in self._l1:
                    overrides[k] = {"default": None, "current": v}
        return overrides

    def reset(self, key: str) -> dict:
        """Remove a runtime override, falling back to L2/L1."""
        with self._lock:
            self._l3.pop(key, None)
            self._save_l3()
        return {"success": True, "key": key}

    def reset_all(self) -> dict:
        """Clear all runtime overrides."""
        with self._lock:
            self._l3.clear()
            self._save_l3()
        return {"success": True}

    @staticmethod
    def _flatten(d: dict, prefix: str = "") -> dict:
        """Recursively flatten a nested dict into dotted keys.

        {"memory": {"working_budget": 8192}} → {"memory.working_budget": 8192}
        """
        result = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(SettingsCenter._flatten(v, key))
            else:
                result[key] = v
        return result


_center: SettingsCenter | None = None


def get_center() -> SettingsCenter:
    global _center
    if _center is None:
        _center = SettingsCenter()
        _center.load_l3()
    return _center


def reset_center() -> None:
    global _center
    _center = None
