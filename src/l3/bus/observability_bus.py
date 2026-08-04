"""ObservabilityBus -- unified observability bus.

Wraps ops_console (alerts) + health (health checks) + counter (metrics)
+ audit (syscall log) into a single observe() interface.

Used by CentralController and other subsystems for unified monitoring.
"""

from __future__ import annotations

import logging
import threading

from l1.kernel.params.system import OBS_AUDIT_LIMIT

logger = logging.getLogger(__name__)


class ObservabilityBus:
    """Unified observability bus -- alerts + health + metrics + audit."""

    def __init__(self):
        self._lock = threading.Lock()
        self._initialized = False

    def _ensure(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._ops = None
                    self._counter = None
                    self._health = None
                    self._initialized = True

    # ── Unified observe point ──

    def observe(self, kind: str, source: str, data: dict) -> dict:
        """Single entry point for all observability data.

        Kind: alert | health | metric | audit
        Source: agent_id / cell_id / system
        Data: kind-specific payload
        """
        self._ensure()
        results = {}

        if kind == "alert":
            results["alert"] = self._alert(source, data.get("message", ""),
                                           data.get("level", "info"), data)
        elif kind == "health":
            results["health"] = self._health_report(source, data)
        elif kind == "metric":
            results["metric"] = self._metric(source, data)
        elif kind == "audit":
            results["audit"] = self._audit(source, data)
        else:
            results["error"] = f"unknown kind: {kind}"

        return results

    # ── Component methods (lazy load) ──

    def _alert(self, source: str, message: str, level: str = "info",
               data: dict | None = None) -> dict:
        try:
            from l3.ops_console import get_ops
            ops = get_ops()
            ops.add_alert(source, message, level, data)
            return {"success": True}
        except (ImportError, AttributeError) as e:
            logger.warning("observability alert: %s", e)
            return {"success": False, "error": str(e)}

    def _health_report(self, source: str, data: dict) -> dict:
        try:
            from l1.kernel import health
            return health()
        except (ImportError, AttributeError) as e:
            return {"success": False, "error": str(e)}

    def _metric(self, source: str, data: dict) -> dict:
        try:
            from l3.services.counter import get_counter
            counter = get_counter()
            metric = data.get("metric", "")
            value = data.get("value", 1)
            tags = data.get("tags", [source])
            counter.increment(metric, value, tags)
            return {"success": True, "metric": metric, "value": value}
        except (ImportError, AttributeError, KeyError) as e:
            return {"success": False, "error": str(e)}

    def _audit(self, source: str, data: dict) -> dict:
        try:
            from l1.kernel import record_audit
            record_audit(data.get("op", "unknown"), source,
                         success=data.get("success", True),
                         detail=data.get("detail", ""))
            return {"success": True}
        except (ImportError, AttributeError) as e:
            return {"success": False, "error": str(e)}

    # ── Convenience methods ──

    def summary(self) -> dict:
        """Get a unified summary of all observability dimensions."""
        self._ensure()
        result = {}

        try:
            from l3.ops_console import get_ops
            result["ops"] = get_ops().summary()
        except (ImportError, AttributeError):
            result["ops"] = {}

        try:
            from l1.kernel import health
            result["health"] = health()
        except (ImportError, AttributeError):
            result["health"] = {}

        try:
            from l3.services.counter import get_counter
            result["metrics"] = get_counter().dump()
        except (ImportError, AttributeError):
            result["metrics"] = {}

        try:
            from l1.kernel import get_audit_log
            result["audit"] = len(get_audit_log(limit=OBS_AUDIT_LIMIT))
        except (ImportError, AttributeError):
            result["audit"] = 0

        return result


_obs_bus: ObservabilityBus | None = None


def get_obs_bus() -> ObservabilityBus:
    global _obs_bus
    if _obs_bus is None:
        _obs_bus = ObservabilityBus()
    return _obs_bus


def reset_obs_bus() -> None:
    global _obs_bus
    _obs_bus = None
