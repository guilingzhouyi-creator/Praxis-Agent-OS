"""Boot step registry — extensible, dependency-ordered boot step registration.

Extracted from boot/boot.py to reduce the 804-line file.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field

from l1.kernel.params.kernel import BOOT_STEP_TIMEOUT

logger = logging.getLogger(__name__)

# ── Boot step registry (extensible) ──

_boot_registry: dict[str, BootStep] = {}
_boot_registry_locked: bool = False


@dataclass
class BootStep:
    name: str = ""
    fn: Callable = lambda: {}
    depends_on: list[str] = field(default_factory=list)


def register_boot_step(name: str, fn: Callable,
                       depends_on: list[str] | None = None,
                       override: bool = False) -> None:
    """Register a boot step. Steps are ordered by dependency before execution.

    Args:
        name: Unique step name. Used as key in results dict.
        fn: Callable that returns a dict (at minimum {"success": True/False}).
        depends_on: List of step names that must complete first.
        override: If True, replace an existing step with the same name.
    """
    if _boot_registry_locked and not override:
        raise RuntimeError("boot registry is locked (already executed)")
    if name in _boot_registry and not override:
        raise ValueError(f"boot step '{name}' already registered; use override=True")
    _boot_registry[name] = BootStep(name=name, fn=fn, depends_on=depends_on or [])


def resolve_boot_order() -> list[str]:
    """Topological sort of registered boot steps by dependency."""
    names = list(_boot_registry.keys())
    ordered = []
    visited = set()
    in_stack = set()

    def _dfs(n: str) -> bool:
        if n in in_stack:
            cycle = " -> ".join(list(in_stack) + [n])
            raise RuntimeError(f"circular boot dependency: {cycle}")
        if n in visited:
            return True
        in_stack.add(n)
        step = _boot_registry.get(n)
        if step:
            for dep in step.depends_on:
                if dep in _boot_registry:
                    _dfs(dep)
            ordered.append(n)
        in_stack.discard(n)
        visited.add(n)
        return True

    for n in names:
        if n not in visited:
            _dfs(n)
    return ordered


_EXECUTOR: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="boot")
    return _EXECUTOR


def exec_step_with_timeout(fn: Callable, timeout: float = BOOT_STEP_TIMEOUT) -> dict:
    """Execute a boot step function with a timeout.  Returns step result dict."""
    ex = _get_executor()
    fut = ex.submit(fn)
    try:
        result = fut.result(timeout=timeout)
    except TimeoutError:
        logger.warning("boot step timed out after %.1fs", timeout)
        return {"success": False, "error": "timed out"}
    except Exception as e:
        logger.warning("boot step failed: %s", e)
        return {"success": False, "error": str(e)}
    if isinstance(result, dict):
        return result
    # Non-dict results are wrapped so callers always get a dict (boot steps
    # call .get("success", True) on the result).
    return {"success": True, "result": result}


def lock_registry() -> None:
    """Lock the boot registry — no new steps can be registered."""
    global _boot_registry_locked
    _boot_registry_locked = True


def reset_registry() -> None:
    """Reset the boot registry (for testing)."""
    global _boot_registry, _boot_registry_locked, _EXECUTOR
    _boot_registry.clear()
    _boot_registry_locked = False
    if _EXECUTOR:
        _EXECUTOR.shutdown(wait=False)
        _EXECUTOR = None
