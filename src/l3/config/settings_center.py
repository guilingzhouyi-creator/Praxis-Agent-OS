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
    AGENT_LOOP_DEFAULT_TIMEOUT,
    LOOP_COARSE_REPEAT_NUDGE,
    LOOP_MAX_ATTEMPTS,
    LOOP_MAX_ITERATIONS,
    LOOP_TOOL_REPEAT_WARN,
    TERMINAL_MAX_WORKERS,
)
from l1.kernel.params.api import DEFAULT_MODEL_OLLAMA_CODER, NOTIFY_WEBHOOK_TIMEOUT
from l1.kernel.params.kernel import GATECHAIN_HIGH_FREQ_THRESHOLD, GATECHAIN_REPEAT_THRESHOLD
from l1.kernel.params.system import (
    CACHE_DEFAULT_TTL,
    LOG_TRUNC_500,
    MEMORY_RING_LONG_BUDGET,
    MEMORY_RING_SHORT_BUDGET,
    MEMORY_RING_SHORT_TTL,
    MEMORY_RING_WORKING_BUDGET,
    MEMORY_RING_WORKING_TTL,
    PMU_SNAPSHOT_INTERVAL,
    SCOUT_CACHE_TTL,
    SCOUT_POOL_MAX_PER_AGENT,
    SCOUT_POOL_MAX_TOTAL,
)
from l1.kernel.paths import get_paths as _gp

logger = logging.getLogger(__name__)

# Default L1 values (mirrored from kernel/params.py for runtime-overridable keys)
# These are the "factory defaults" — params.py is the authoritative source at boot.
_L1_DEFAULTS: dict[str, Any] = {
    # ── Approval gate ──
    "approval.danger_threshold": 3,
    # ── Memory budgets ──
    "memory.working_budget": MEMORY_RING_WORKING_BUDGET,
    "memory.short_budget": MEMORY_RING_SHORT_BUDGET,
    "memory.long_budget": MEMORY_RING_LONG_BUDGET,
    "memory.working_ttl": MEMORY_RING_WORKING_TTL,
    "memory.short_ttl": MEMORY_RING_SHORT_TTL,
    # ── Scout pool ──
    "scout.max_total": SCOUT_POOL_MAX_TOTAL,
    "scout.max_per_agent": SCOUT_POOL_MAX_PER_AGENT,
    # ── Agent terminal ──
    "terminal.max_workers": TERMINAL_MAX_WORKERS,
    # ── Scheduler ──
    "scheduler.default_quantum": 15.0,
    "scheduler.max_preempt": PMU_SNAPSHOT_INTERVAL,
    # ── Scout cache ──
    "scout.cache_ttl": SCOUT_CACHE_TTL,
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
    "think.max_reasoning": "max",  # none|low|medium|high|xhigh|max; lower to cap reasoning
    "think.profiles": {},
    # ── GateChain ──
    "gatechain.risk_warn_threshold": 6.0,
    "gatechain.escalation_danger": 4,
    "gatechain.repeat_threshold": GATECHAIN_REPEAT_THRESHOLD,
    "gatechain.high_freq_threshold": GATECHAIN_HIGH_FREQ_THRESHOLD,
    # ── TaskBus (webhook dispatch) ──
    "task_bus.webhook_retries": LOOP_MAX_ATTEMPTS,
    "task_bus.webhook_timeout": NOTIFY_WEBHOOK_TIMEOUT,
    "task_bus.webhook_backoff": "1.0,4.0,10.0",
    # ── CronScheduler ──
    "cron.check_interval": PMU_SNAPSHOT_INTERVAL,
    "cron.max_entries": 50,
    # ── Lifecycle (persistent state tracking) ──
    "lifecycle.install_version": 0,
    "lifecycle.schema_version": "",
    # ── L3A session limits (0 = unlimited) ──
    "l3a.max_steps": 0,
    "l3a.max_turns": 0,
    "l3a.timeout": 0,
    "l3a.idle_timeout": 3600.0,
    "l3a.archive_importance": 0.7,
    "session.max_turns": 0,  # deprecated — use l3a.max_turns
    # ── L3A auto-compression (system-monitored context thresholds) ──
    "l3a.auto_compress": True,
    "l3a.auto_compress_threshold": 0.6,  # pressure_ratio to trigger
    "l3a.auto_compress_keep": 10,  # messages kept after auto-compress
    # ── Loop control (AgentLoop self-correction) ──
    "loop.max_steps": 0,  # 0 = unlimited by default; > 0 = step-limited mode
    "loop.timeout": AGENT_LOOP_DEFAULT_TIMEOUT,
    "loop.max_iterations": LOOP_MAX_ITERATIONS,
    "loop.max_attempts": LOOP_MAX_ATTEMPTS,
    "loop.continuation_nudge": True,
    "loop.tool_repeat_warn": LOOP_TOOL_REPEAT_WARN,
    "loop.tool_repeat_stop": 4,
    "loop.coarse_repeat_nudge": LOOP_COARSE_REPEAT_NUDGE,
    "loop.coarse_repeat_stop": 6,
    "loop.verify_cadence": True,
    # ── LLM global (model_service reads via SettingsCenter) ──
    "llm.provider": "ollama",
    "llm.model": DEFAULT_MODEL_OLLAMA_CODER,
    "llm.api_key": "",
    "llm.api_url": "",
    # ── Device ──
    "device.rate_limit_default": 10,
    # ── Diff API (mirrors config/praxis.yaml diff: section) ──
    "diff.heavy_api_enabled": False,
    "diff.colors": {
        "logic_change": "\033[31m",
        "reformat": "\033[34m",
        "comment_only": "\033[32m",
        "import_change": "\033[33m",
        "import_added": "\033[33m",
        "rename": "\033[36m",
        "structural": "\033[90m",
        "mixed": "\033[35m",
        "added": "\033[32m",
        "removed": "\033[31m",
    },
    # ── Constitution runtime rules (L3-persisted custom rules) ──
    "constitution.custom_rules": [],
    # ── Skills (developer-only write gate) ──
    "skill.write_min_ring": 3,  # min ring clearance to mutate skills
    "skill.write_roles": ["l3", "reviewer", "deployer"],
    "skill.evolve_scope": "project",  # "project" | "global" — evolution write target
    "skill.project_dirs": [],  # extra project skill discovery dirs
    # ── Per-Cell skill white-list (回灌到 Cell); empty → global pool ──
    "cell.skills": {},
    # ── R4 Agent ──
    "r4_agent.model_spec": "r4_agent",  # model spec name for skill evolution / archive ops
    # ── Per-executor model specs (model_service reads model_spec.{name}.defaults) ──
    # Mirrors the model_spec section of config/praxis.yaml; `model` inherits
    # from llm.model unless set per executor.
    "model_spec.scout.defaults.max_tokens": 2048,
    "model_spec.scout.defaults.temperature": 0.3,
    "model_spec.scout.defaults.reasoning_effort": "none",
    "model_spec.scout.defaults.thinking_budget": 0,
    "model_spec.l3a.defaults.max_tokens": 4096,
    "model_spec.l3a.defaults.temperature": 0.7,
    "model_spec.l3a.defaults.reasoning_effort": "none",
    "model_spec.l3a.defaults.thinking_budget": 0,
    "model_spec.l3a_subagent.defaults.max_tokens": 2048,
    "model_spec.l3a_subagent.defaults.temperature": 0.3,
    "model_spec.l3a_subagent.defaults.reasoning_effort": "none",
    "model_spec.l3a_subagent.defaults.thinking_budget": 0,
    "model_spec.subagent.defaults.max_tokens": 2048,
    "model_spec.subagent.defaults.temperature": 0.3,
    "model_spec.subagent.defaults.reasoning_effort": "none",
    "model_spec.subagent.defaults.thinking_budget": 0,
    "model_spec.r4_agent.defaults.max_tokens": 2048,
    "model_spec.r4_agent.defaults.temperature": 0.3,
    "model_spec.r4_agent.defaults.reasoning_effort": "none",
    "model_spec.r4_agent.defaults.thinking_budget": 0,
}


class SettingsCenter:
    """Three-layer settings aggregator.

    Thread-safe. L3 writes are persisted to .praxis_settings.json.
    """

    def __init__(self, persist_path: str = ""):
        self._lock = threading.RLock()
        self._l1: dict[str, Any] = dict(_L1_DEFAULTS)
        self._l2: dict[str, Any] = {}  # loaded from praxis.yaml at boot
        self._l3: dict[str, Any] = {}  # loaded/saved to .praxis_settings.json
        self._persist_path = persist_path or (_gp().settings_file)

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
        """Read a setting coerced to int, falling back to the default."""
        val = self.get(key, default)
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Read a setting coerced to float, falling back to the default."""
        val = self.get(key, default)
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Read a setting coerced to bool, falling back to the default."""
        val = self.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    # ── Write (L2 = praxis.yaml layer, L3 = runtime overrides) ──

    def set_l2(self, key: str, value: Any) -> dict:
        """Write a value into the L2 (praxis.yaml) layer. Not persisted.

        L2 is the deployment-config layer loaded at boot; use for values that
        come from praxis.yaml so they never leak into the persisted L3
        runtime-override file.
        """
        with self._lock:
            self._l2[key] = value
        return {"success": True, "key": key, "value": value, "layer": "l2"}

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
    """Get the SettingsCenter singleton."""
    global _center
    if _center is None:
        _center = SettingsCenter()
        _center.load_l3()
    return _center


def reset_center() -> None:
    """Reset the SettingsCenter singleton (test/factory-reset path).

    Also removes the persisted L3 override file so a freshly created center
    does not reload stale runtime overrides from a previous test session.
    """
    global _center
    _center = None
    try:
        persist = _center_persist_path()
        if persist and os.path.exists(persist):
            os.remove(persist)
    except Exception as e:
        logger.debug("settings_center: persist cleanup failed: %s", e)


def _center_persist_path() -> str:
    """Resolve the settings persist path without constructing a center."""
    try:
        from l1.kernel.paths import get_paths as _gp

        return _gp().settings_file
    except Exception:
        return ""
