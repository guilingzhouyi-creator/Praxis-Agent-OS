"""ModelStrategyEngine — three-layer think config + CapabilityDetector.

Global → Cell → Agent 三层配置覆盖。
CapabilityDetector 用旁路线程池异步探测 LLM provider 能力。
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from l1.kernel.params.system import THINK_BUDGET_GLOBAL_DEFAULT, THINK_REASONING_DEFAULT

logger = logging.getLogger(__name__)

# Keys used in config dicts for think configuration
ALL_KEYS = frozenset({
    "reasoning_effort",
    "thinking_budget",
    "max_tokens",
    "temperature",
    "model",
    "context_window",
})

DISTRIBUTION_MODES = frozenset({"inherit", "auto_balance", "manual"})


class CapabilityDetector:
    """Background probe pool — async capability detection for LLM providers.

    Maintains a cache of {(provider, model): capabilities_dict}.
    Probes are dispatched to a thread pool to avoid blocking agent execution.
    """

    def __init__(self, max_workers: int = 4, cache_ttl: float = 86400.0):
        self._pool = ThreadPoolExecutor(max_workers, thread_name_prefix="probe")
        self._cache: dict[tuple[str, str], Any] = {}
        self._cache_ttl = cache_ttl
        self._lock = threading.RLock()
        self._failures: dict[tuple[str, str], int] = {}

    def discover(self, provider_name: str, provider_instance: Any) -> None:
        """Submit a provider+model for async capability probing."""
        model = getattr(provider_instance, "model", "")
        key = (provider_name, model)
        with self._lock:
            # Check failure backoff: skip if failed 3+ times recently
            fails = self._failures.get(key, 0)
            if fails >= 3:
                logger.debug("probe skip %s/%s: %d failures", provider_name, model, fails)
                return
            future = self._pool.submit(self._probe_worker, provider_name, provider_instance)
            self._cache[key] = future

    def _probe_worker(self, provider_name: str, provider_instance: Any) -> dict:
        """Run probe() on a provider, with error handling."""
        try:
            result = provider_instance.probe()
            logger.info("probe %s/%s: supports=%s ctx=%d",
                        provider_name, getattr(provider_instance, "model", ""),
                        result.get("supports", set()), result.get("context_window", 0))
            return result
        except Exception as e:
            logger.warning("probe %s failed: %s", provider_name, e)
            key = (provider_name, getattr(provider_instance, "model", ""))
            with self._lock:
                self._failures[key] = self._failures.get(key, 0) + 1
            return {"supports": set(), "context_window": 0, "error": str(e)}

    def get_capabilities(self, provider_name: str, model: str) -> dict | None:
        """Get cached capabilities for a provider+model. Returns None if unknown."""
        key = (provider_name, model)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if isinstance(entry, Future):
                try:
                    result = entry.result(timeout=5)
                    self._cache[key] = result
                    logger.debug("probe %s/%s completed: supports=%s", provider_name, model,
                                 result.get("supports", set()))
                    return result
                except Exception as e:
                    logger.warning("probe %s/%s wait failed: %s", provider_name, model, e)
                    self._cache.pop(key, None)
                    return None
            if isinstance(entry, dict):
                if "detected_at" not in entry:
                    entry["detected_at"] = time.time()
                if time.time() - entry.get("detected_at", 0) > self._cache_ttl:
                    self._cache.pop(key, None)
                    return None
                return entry
            return None

    def probe_all_registered(self, registry: Any) -> int:
        """Batch probe all providers in a ModelRegistry. Returns count submitted."""
        count = 0
        try:
            for name, cls, config in registry.iter_instances():
                self.discover(name, cls)
                count += 1
        except Exception:
            pass
        return count

    def stats(self) -> dict:
        with self._lock:
            resolved = sum(1 for v in self._cache.values() if isinstance(v, dict))
            pending = sum(1 for v in self._cache.values() if isinstance(v, Future))
            return {
                "cached": resolved,
                "pending": pending,
                "failures": dict(self._failures),
            }


# ── Singleton ──

_detector: CapabilityDetector | None = None


def get_detector() -> CapabilityDetector:
    global _detector
    if _detector is None:
        _detector = CapabilityDetector()
    return _detector


def reset_detector() -> None:
    global _detector
    _detector = None


class ModelStrategyEngine:
    """Three-layer think configuration: Global → Cell → Agent.

    Merges config from all three layers and applies capability-based
    parameter filtering before passing to LLM.generate().
    """

    def __init__(self, detector: CapabilityDetector | None = None):
        self._detector = detector or get_detector()
        self._lock = threading.RLock()
        self._global: dict[str, Any] = {
            "reasoning_effort": THINK_REASONING_DEFAULT,
            "thinking_budget": THINK_BUDGET_GLOBAL_DEFAULT,
            "max_tokens": None,
            "temperature": None,
            "model": None,
            "context_window": None,
        }
        self._cells: dict[str, dict] = {}
        self._agents: dict[str, dict] = {}

    def set_global(self, **kwargs: Any) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if k in ALL_KEYS:
                    self._global[k] = v
                else:
                    logger.warning("strategy: unknown key %s", k)

    def get_global(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._global)

    def set_cell(self, cell_id: str, **config: Any) -> None:
        with self._lock:
            entry = self._cells.setdefault(cell_id, {})
            entry.update({k: v for k, v in config.items() if v is not None})

    def get_cell(self, cell_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._cells.get(cell_id, {}))

    def set_agent(self, cell_id: str, agent_id: str, **config: Any) -> None:
        key = f"{cell_id}.{agent_id}"
        with self._lock:
            entry = self._agents.setdefault(key, {})
            entry.update({k: v for k, v in config.items() if v is not None})

    def get_agent(self, cell_id: str, agent_id: str) -> dict[str, Any]:
        key = f"{cell_id}.{agent_id}"
        with self._lock:
            return dict(self._agents.get(key, {}))

    def resolve(self, cell_id: str, agent_id: str,
                provider_name: str = "", model: str = "") -> dict[str, Any]:
        """Three-layer merge: agent > cell > global, filtered by provider capabilities.

        Returns a config dict with only the parameters the provider supports.
        """
        with self._lock:
            merged = dict(self._global)
            cell_entry = self._cells.get(cell_id, {})
            merged.update({k: v for k, v in cell_entry.items() if v is not None})
            agent_key = f"{cell_id}.{agent_id}"
            agent_entry = self._agents.get(agent_key, {})
            merged.update({k: v for k, v in agent_entry.items() if v is not None})

        result = {k: v for k, v in merged.items() if v is not None}

        # Apply capability filtering if provider info is available
        if provider_name and model:
            caps = self._detector.get_capabilities(provider_name, model)
            if caps:
                supported = caps.get("supports", set())
                result = {k: v for k, v in result.items() if k in supported}
                if "context_window" in caps:
                    result["context_window"] = caps["context_window"]

        return result

    def reset(self) -> None:
        with self._lock:
            self._global = {k: None for k in ALL_KEYS}
            self._cells.clear()
            self._agents.clear()


# ── Singleton ──

_engine: ModelStrategyEngine | None = None


def get_engine() -> ModelStrategyEngine:
    global _engine
    if _engine is None:
        _engine = ModelStrategyEngine()
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None
