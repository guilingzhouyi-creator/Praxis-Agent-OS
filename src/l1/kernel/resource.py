"""Resource limits — token budgets, concurrency caps, file descriptor limits.

Each agent has a resource profile:
  max_tokens:    Max LLM tokens per inference
  max_workers:   Max concurrent tool calls
  max_scouts:    Max active scouts
  max_memory:    Max Ring 1 entries
  priority:      Scheduling priority (1-10)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from .params.agent import DEFAULT_AGENT_CONFIGS
from .params.kernel import (
    RESOURCE_DEFAULT_COST,
    RESOURCE_FALLBACK_AGENT,
    RESOURCE_KEYS,
    RESOURCE_PROFILE_DEFAULTS,
)

logger = logging.getLogger(__name__)


@dataclass
class ResourceProfile:
    """ResourceProfile — resource profile record (max_tokens, max_workers, max_scouts, max_memory, priority)."""
    max_tokens: int = RESOURCE_PROFILE_DEFAULTS.max_tokens
    max_workers: int = RESOURCE_PROFILE_DEFAULTS.max_workers
    max_scouts: int = RESOURCE_PROFILE_DEFAULTS.max_scouts
    max_memory: int = RESOURCE_PROFILE_DEFAULTS.max_memory
    priority: int = RESOURCE_PROFILE_DEFAULTS.priority


def _build_default_profiles() -> dict[str, ResourceProfile]:
    """Build default profiles from DEFAULT_AGENT_CONFIGS (single source of truth)."""
    profiles: dict[str, ResourceProfile] = {}
    for role, cfg in DEFAULT_AGENT_CONFIGS.items():
        profiles[role] = ResourceProfile(
            max_tokens=cfg.max_tokens, max_workers=cfg.max_workers,
            max_scouts=cfg.max_scouts, priority=cfg.priority,
        )
    return profiles


DEFAULT_PROFILES = _build_default_profiles()


def _limits_dict(p: ResourceProfile) -> dict:
    return {
        "workers": p.max_workers,
        "scouts": p.max_scouts,
        "memory": p.max_memory,
        "tokens": p.max_tokens,
    }


class ResourceLimiter:
    """Enforces resource limits per agent."""

    def __init__(self):
        self._profiles: dict[str, ResourceProfile] = dict(DEFAULT_PROFILES)
        self._usage: dict[str, dict] = {}
        self._lock = threading.RLock()

    def get_profile(self, agent_id: str) -> dict:
        """Return the resource profile of *agent_id* as a dict (falls back to the default agent)."""
        with self._lock:
            p = self._profiles.get(agent_id, DEFAULT_PROFILES[RESOURCE_FALLBACK_AGENT])
            return {"max_tokens": p.max_tokens, "max_workers": p.max_workers,
                    "max_scouts": p.max_scouts, "max_memory": p.max_memory, "priority": p.priority}

    def set_profile(self, agent_id: str, **kwargs) -> dict:
        """Update known profile fields of *agent_id* with the given kwargs. Returns a success dict."""
        with self._lock:
            p = self._profiles.setdefault(agent_id, ResourceProfile())
            for k, v in kwargs.items():
                if hasattr(p, k):
                    setattr(p, k, v)
            return {"success": True}

    def check(self, agent_id: str, resource: str, cost: int = RESOURCE_DEFAULT_COST) -> dict:
        """Reserve *cost* units of *resource* for *agent_id* if within limits. Returns a result dict."""
        with self._lock:
            p = self._profiles.get(agent_id, DEFAULT_PROFILES[RESOURCE_FALLBACK_AGENT])
            usage = self._usage.setdefault(agent_id, {r: 0 for r in RESOURCE_KEYS})
            limits = _limits_dict(p)

            if resource not in limits:
                return {"success": False, "error": f"unknown resource: {resource}"}

            current = usage.get(resource, 0)
            if current + cost > limits[resource]:
                return {"success": False, "error": f"{resource} limit exceeded ({current + cost} > {limits[resource]})",
                        "current": current, "limit": limits[resource], "requested": cost}

            usage[resource] = current + cost
            return {"success": True, "current": usage[resource], "limit": limits[resource]}

    def release(self, agent_id: str, resource: str, cost: int = RESOURCE_DEFAULT_COST) -> dict:
        """Release *cost* units of *resource* back to *agent_id* (floored at zero). Returns a success dict."""
        with self._lock:
            if agent_id not in self._usage:
                self._usage[agent_id] = {r: 0 for r in RESOURCE_KEYS}
            u = self._usage[agent_id]
            u[resource] = max(0, u.get(resource, 0) - cost)
            return {"success": True, "current": u[resource]}

    def usage(self, agent_id: str) -> dict:
        """Return current vs max usage for every resource of *agent_id*."""
        with self._lock:
            p = self._profiles.get(agent_id, DEFAULT_PROFILES[RESOURCE_FALLBACK_AGENT])
            u = self._usage.get(agent_id, {})
            return {
                "workers": {"current": u.get("workers", 0), "max": p.max_workers},
                "scouts": {"current": u.get("scouts", 0), "max": p.max_scouts},
                "memory": {"current": u.get("memory", 0), "max": p.max_memory},
                "tokens": {"current": u.get("tokens", 0), "max": p.max_tokens},
            }

    def all_usage(self) -> dict:
        """Return usage snapshots for every known agent profile."""
        with self._lock:
            return {aid: self.usage(aid) for aid in self._profiles}


_limiter: ResourceLimiter | None = None
_limiter_lock = threading.Lock()


def get_limiter() -> ResourceLimiter:
    """Get the resource limiter singleton (lazily created)."""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = ResourceLimiter()
    return _limiter


def reset_limiter() -> None:
    """Reset the resource limiter singleton to None (for tests / hot reset)."""
    global _limiter
    _limiter = None
