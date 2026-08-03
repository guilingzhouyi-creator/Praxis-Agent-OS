"""Kernel Health Check — subsystem status verification.

Provides:
  safe_system_check() → dict  — non-destructive check of all kernel subsystems
  subsystem_status(name) → dict — check a single subsystem

Used by TUI health command and monitoring.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_120

logger = logging.getLogger(__name__)

# Known kernel modules (must be importable at runtime)
_KERNEL_MODULES = [
    "l1.kernel.allocator",
    "l1.kernel.constitution",
    "l1.kernel.device",
    "l1.kernel.event",
    "l1.kernel.gatechain",
    "l1.kernel.interrupt",
    "l1.kernel.ipc",
    "l1.kernel.net",
    "l1.kernel.os",
    "l1.kernel.params",
    "l1.kernel.persist",
    "l1.kernel.platform",
    "l1.kernel.process",
    "l1.kernel.registry",
    "l1.kernel.reputation",
    "l1.kernel.resource",
    "l1.kernel.settings",
    "l1.kernel.skill",
    "l1.kernel.swapper",
    "l1.kernel.sync",
    "l1.kernel.tool_chain",
    "l1.kernel.vfs",
]


def safe_system_check() -> dict[str, Any]:
    """Non-destructive check of all kernel subsystems.

    Returns:
        {
            "status": "OK" | "DEGRADED" | "DOWN",
            "module_count": int,
            "healthy": int,
            "degraded": int,
            "failed": int,
            "subsystems": {name: {"status": ..., "detail": ...}},
            "elapsed_ms": float,
        }
    """
    t0 = time.perf_counter()
    results: dict[str, dict] = {}
    healthy = degraded = failed = 0

    # 1. Module importability
    for mod_name in _KERNEL_MODULES:
        try:
            __import__(mod_name)
            results[mod_name] = {"status": "OK", "detail": "imported"}
            healthy += 1
        except Exception as e:
            results[mod_name] = {"status": "FAILED", "detail": str(e)[:LOG_TRUNC_120]}
            failed += 1
            logger.warning("health: %s failed: %s", mod_name, e)

    # 2. Runtime subsystem checks (non-destructive)
    for fn in (_check_process_table, _check_event_bus, _check_device_manager, _check_constitution):
        try:
            ok, msg = fn(results)
            if ok:
                healthy += 1
            else:
                degraded += 1
        except Exception as e:
            failed += 1
            logger.warning("health check failed: %s", e)

    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Determine overall status
    if failed > 0:
        overall = "DOWN"
    elif degraded > 0:
        overall = "DEGRADED"
    else:
        overall = "OK"

    return {
        "status": overall,
        "module_count": healthy + degraded + failed,
        "healthy": healthy,
        "degraded": degraded,
        "failed": failed,
        "subsystems": results,
        "elapsed_ms": round(elapsed_ms, 2),
    }


def _check_process_table(results: dict) -> tuple[bool, str]:
    try:
        from .process import get_table
        procs = get_table().list()
        cnt = len(procs) if procs else 0
        results["kernel.process[table]"] = {"status": "OK", "detail": f"{cnt} processes"}
        return True, f"{cnt} procs"
    except Exception as e:
        results["kernel.process[table]"] = {"status": "FAILED", "detail": str(e)[:LOG_TRUNC_120]}
        return False, str(e)


def _check_event_bus(results: dict) -> tuple[bool, str]:
    try:
        from .event import get_bus
        bus = get_bus()
        ok = hasattr(bus, "on") and hasattr(bus, "emit")
        results["kernel.event[bus]"] = {"status": "OK" if ok else "DEGRADED",
                                         "detail": "functional" if ok else "missing methods"}
        return ok, "functional" if ok else "degraded"
    except Exception as e:
        results["kernel.event[bus]"] = {"status": "FAILED", "detail": str(e)[:LOG_TRUNC_120]}
        return False, str(e)


def _check_device_manager(results: dict) -> tuple[bool, str]:
    try:
        from .device import get_device_manager
        dm = get_device_manager()
        results["kernel.device[manager]"] = {"status": "OK", "detail": type(dm).__name__}
        return True, type(dm).__name__
    except Exception as e:
        results["kernel.device[manager]"] = {"status": "FAILED", "detail": str(e)[:LOG_TRUNC_120]}
        return False, str(e)


def _check_constitution(results: dict) -> tuple[bool, str]:
    try:
        from .constitution import get_constitution
        c = get_constitution()
        ok = bool(c)
        results["kernel.constitution[loaded]"] = {"status": "OK" if ok else "DEGRADED",
                                                    "detail": "loaded" if ok else "empty/None"}
        return ok, "loaded" if ok else "empty"
    except Exception as e:
        results["kernel.constitution[loaded]"] = {"status": "FAILED", "detail": str(e)[:LOG_TRUNC_120]}
        return False, str(e)


def subsystem_status(name: str) -> dict:
    """Check a single kernel subsystem by name."""
    full = safe_system_check()
    for key, val in full["subsystems"].items():
        if name in key:
            return val
    return {"status": "UNKNOWN", "detail": f"no subsystem matching '{name}'"}
