"""Central system registry — single source of truth for kernel state.

Queries:
  registry.modules()    → all 17 kernel modules + status
  registry.devices()    → all registered devices
  registry.processes()  → process table
  registry.interrupts() → interrupt counts
  registry.audit()      → recent audit log
  registry.syscall()    → syscall dispatch table
  registry.settings()   → all system settings
  registry.summary()    → unified system overview
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .params.kernel import REGISTRY_QUERY_LIMIT, GateStatus

logger = logging.getLogger(__name__)


class Registry:
    """Queries all kernel subsystems and aggregates their state."""

    def modules(self) -> dict[str, Any]:
        """Return the health status of all kernel modules."""
        from .__init__ import health as _health_fn
        return _health_fn().get("modules", {})

    def devices(self) -> list[dict]:
        """Return all registered devices."""
        from .device import get_device_manager
        return get_device_manager().list()

    def processes(self) -> list[dict]:
        """Return the current process table."""
        from .process import get_table
        return get_table().list_processes()

    def interrupts(self) -> dict[str, Any]:
        """Return interrupt counts and recent interrupt records."""
        from .interrupt import get_table
        t = get_table()
        return {"counts": t.counts(), "recent": t.recent(10)}

    def audit(self, limit: int = REGISTRY_QUERY_LIMIT) -> list[dict]:
        """Return the recent audit log, up to *limit* entries."""
        from . import get_audit_log
        return get_audit_log(limit=limit)

    def tool_chains(self) -> dict[str, Any]:
        """Return tool-chain statistics and recent executions."""
        from .tool_chain import get_tool_chain
        c = get_tool_chain()
        return {"stats": c.stats(), "recent": c.recent(10)}

    def settings(self) -> dict[str, Any]:
        """Return all system settings."""
        from .settings import get_settings
        return get_settings().all()

    def syscalls(self) -> list[str]:
        """Return the sorted list of known syscall names (builtin + custom)."""
        from . import _SYSCALL_REGISTRY
        base = ["mutex.acquire", "mutex.release", "mutex.status",
                "semaphore.acquire", "semaphore.release", "semaphore.status",
                "barrier.wait", "barrier.reset",
                "condition.wait", "condition.signal", "condition.broadcast",
                "signal.emit", "signal.on", "signal.off",
                "resource.check", "resource.release", "resource.usage",
                "process.spawn", "process.exit", "process.list",
                "alloc.alloc", "alloc.free", "alloc.usage"]
        custom = list(_SYSCALL_REGISTRY.keys())
        return sorted(base + custom)

    def summary(self) -> dict[str, Any]:
        """Return a unified system overview (modules, processes, devices, syscalls)."""
        m = self.modules()
        healthy = sum(1 for v in m.values() if v.get("status") == GateStatus.PASS)
        return {
            "modules": {"total": len(m), "healthy": healthy},
            "processes": len(self.processes()),
            "devices": len(self.devices()),
            "syscalls": len(self.syscalls()),
            "timestamp": time.time(),
        }


_registry: Registry | None = None
_registry_lock = threading.Lock()


def get_registry() -> Registry:
    """Get the system registry singleton (lazily created)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = Registry()
    return _registry
