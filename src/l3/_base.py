"""Service base — common foundation for all services.

Provides:
  - Service Lifecycle (init → start → running → stop)
  - Health checks
  - Unified logging
  - Auto-generated service registry
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from enum import Enum, auto


class ServiceState(Enum):
    """ServiceState — enum of CREATED, STARTING, RUNNING, STOPPING...."""
    CREATED = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    ERROR = auto()


_registry: dict[str, BaseService] = {}


def get_registry() -> dict[str, BaseService]:
    """Get the service registry dict."""
    return dict(_registry)


class BaseService(ABC):
    """Base class for all IDE services."""

    def __init__(self, name: str):
        self.name = name
        self.state = ServiceState.CREATED
        self.logger = logging.getLogger(f"svc.{name}")
        self._lock = threading.RLock()
        self._started_at = 0.0
        _registry[name] = self

    def start(self) -> dict:
        with self._lock:
            if self.state == ServiceState.RUNNING:
                return {"success": True, "note": "already running"}
            self.state = ServiceState.STARTING
            self._started_at = time.time()
            try:
                result = self._on_start()
                self.state = ServiceState.RUNNING
                self.logger.info("started")
                return result or {"success": True}
            except Exception as e:
                self.state = ServiceState.ERROR
                self.logger.error("start failed: %s", e)
                return {"success": False, "error": str(e)}

    def stop(self) -> dict:
        with self._lock:
            if self.state == ServiceState.STOPPED:
                return {"success": True, "note": "already stopped"}
            self.state = ServiceState.STOPPING
            try:
                result = self._on_stop()
                self.state = ServiceState.STOPPED
                self.logger.info("stopped")
                return result or {"success": True}
            except Exception as e:
                self.state = ServiceState.ERROR
                self.logger.error("stop failed: %s", e)
                return {"success": False, "error": str(e)}

    def health(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.name,
                "uptime": time.time() - self._started_at if self._started_at else 0,
                "healthy": self.state == ServiceState.RUNNING,
            }

    @abstractmethod
    def _on_start(self) -> dict:
        """Initialize service resources."""

    @abstractmethod
    def _on_stop(self) -> dict:
        """Cleanup service resources."""
