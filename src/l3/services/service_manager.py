"""Service Manager — OS-level service lifecycle management (systemctl equivalent).

Manages start/stop/restart/status of all kernel services.
Supports service dependencies, health checks, and unified status reporting.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from l1.kernel.params.system import POLL_INTERVAL_PAUSED
from l3._base import BaseService, get_registry

logger = logging.getLogger(__name__)


class ServiceState:
    """ServiceState — service state."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    """ServiceInfo — service info record (name, state, uptime, started_at, healthy)."""

    name: str
    state: str = ServiceState.UNKNOWN
    uptime: float = 0.0
    started_at: float = 0.0
    healthy: bool = False
    depends_on: list[str] = field(default_factory=list)
    error: str = ""


class ServiceManager(BaseService):
    """OS-level service manager — systemctl equivalent for Agent OS."""

    def __init__(self):
        super().__init__("service_manager")
        self._services: dict[str, ServiceInfo] = {}
        self._lock = threading.RLock()
        self._start_order: list[str] = []

    def _on_start(self) -> dict:
        self._discover_services()
        return {"success": True, "services": len(self._services)}

    def _on_stop(self) -> dict:
        with self._lock:
            self._services.clear()
        return {"success": True}

    def _discover_services(self) -> None:
        """Discover all registered BaseService instances."""
        registry = get_registry()
        for name, svc in registry.items():
            info = ServiceInfo(name=name)
            info.state = ServiceState.RUNNING if svc.state.name == "RUNNING" else ServiceState.UNKNOWN
            info.healthy = svc.health().get("healthy", False)
            info.started_at = svc.health().get("uptime", 0)
            self._services[name] = info

    def register(self, name: str, depends_on: list[str] | None = None) -> dict:
        """Register a service with the manager."""
        with self._lock:
            self._services[name] = ServiceInfo(
                name=name,
                state=ServiceState.STOPPED,
                depends_on=depends_on or [],
            )
        return {"success": True, "service": name}

    # ── Lifecycle ──

    def start_service(self, name: str) -> dict:
        """Start a service by name."""
        with self._lock:
            info = self._services.get(name)
            if not info:
                return {"success": False, "error": f"unknown service: {name}"}
            if info.state == ServiceState.RUNNING:
                return {"success": True, "note": "already running"}

        # Check dependencies
        for dep in info.depends_on:
            dep_info = self._services.get(dep)
            if dep_info and dep_info.state != ServiceState.RUNNING:
                self.start(dep)

        # Start the service
        try:
            registry = get_registry()
            svc = registry.get(name)
            if svc and hasattr(svc, "start"):
                r = svc.start()
                if r.get("success"):
                    with self._lock:
                        info.state = ServiceState.RUNNING
                        info.started_at = time.time()
                        info.healthy = True
                        info.error = ""
                    return {"success": True, "service": name, "state": "running"}
                with self._lock:
                    info.state = ServiceState.ERROR
                    info.error = r.get("error", "start failed")
                return {"success": False, "error": info.error}
            return {"success": False, "error": f"service {name} not found in registry"}
        except Exception as e:
            with self._lock:
                info.state = ServiceState.ERROR
                info.error = str(e)
            return {"success": False, "error": str(e)}

    def stop(self, name: str) -> dict:
        """Stop a service by name."""
        with self._lock:
            info = self._services.get(name)
            if not info:
                return {"success": False, "error": f"unknown service: {name}"}
        try:
            registry = get_registry()
            svc = registry.get(name)
            if svc and hasattr(svc, "stop"):
                svc.stop()
            with self._lock:
                info.state = ServiceState.STOPPED
                info.healthy = False
            return {"success": True, "service": name, "state": "stopped"}
        except Exception as e:
            with self._lock:
                info.state = ServiceState.ERROR
                info.error = str(e)
            return {"success": False, "error": str(e)}

    def restart(self, name: str) -> dict:
        """Restart a service."""
        self.stop(name)
        time.sleep(POLL_INTERVAL_PAUSED)
        return self.start(name)

    # ── Status ──

    def status(self, name: str = "") -> dict:
        """Get status of a service or all services."""
        with self._lock:
            if name:
                info = self._services.get(name)
                if not info:
                    return {"success": False, "error": f"unknown service: {name}"}
                return {
                    "success": True,
                    "service": {
                        "name": info.name,
                        "state": info.state,
                        "uptime": round(time.time() - info.started_at, 1) if info.started_at else 0,
                        "healthy": info.healthy,
                        "error": info.error,
                        "depends_on": info.depends_on,
                    },
                }

            services = {}
            for n, info in self._services.items():
                services[n] = {
                    "state": info.state,
                    "healthy": info.healthy,
                    "uptime": round(time.time() - info.started_at, 1) if info.started_at else 0,
                    "error": info.error,
                }
            return {"success": True, "services": services, "count": len(services)}

    def list_services(self) -> dict:
        """List all registered services."""
        with self._lock:
            return {
                "success": True,
                "services": [
                    {"name": n, "state": info.state, "healthy": info.healthy} for n, info in self._services.items()
                ],
                "count": len(self._services),
            }

    def health_check(self, name: str = "") -> dict:
        """Health check for a service or all services."""
        with self._lock:
            if name:
                info = self._services.get(name)
                if not info:
                    return {"success": False, "error": f"unknown service: {name}"}
                return {"success": True, "name": name, "healthy": info.healthy, "state": info.state}
            healthy = sum(1 for info in self._services.values() if info.healthy)
            total = len(self._services)
            return {"success": True, "healthy": healthy, "total": total, "all_healthy": healthy == total}

    def stats(self) -> dict:
        """Return service count, state distribution, and healthy count."""
        with self._lock:
            states: dict[str, int] = {}
            for info in self._services.values():
                states[info.state] = states.get(info.state, 0) + 1
            return {
                "total": len(self._services),
                "states": states,
                "healthy": sum(1 for info in self._services.values() if info.healthy),
            }


_service: ServiceManager | None = None


def get_service() -> ServiceManager:
    """Return the shared ServiceManager singleton, creating it on first use."""
    global _service
    if _service is None:
        _service = ServiceManager()
    return _service


def reset_service() -> None:
    """Stop all services and drop the ServiceManager singleton."""
    global _service
    if _service:
        for name in list(_service._services.keys()):
            _service.stop(name)
    _service = None
