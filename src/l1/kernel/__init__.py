"""Agent OS Kernel — fundamental primitives and syscall interface.

Every operation goes through syscall() which provides:
  - Unified dispatch
  - Audit trail (every call logged)
  - Error normalization (structured error codes)
  - Caller tracking (agent_id extracted from kwargs)

Architecture:
  caller → syscall() → [audit] → [dispatch] → kernel primitive → return
"""

import logging
import threading
import time
from collections import deque
from itertools import islice
from typing import Any

from . import discovery
from .allocator import get_allocator
from .constitution import get_constitution
from .device import DeviceHealth, DeviceType, get_device_manager
from .event import Signal, SignalType
from .event import get_bus as get_event_bus
from .gatechain import get_gatechain
from .interrupt import Interrupt, InterruptType, fire
from .interrupt import get_table as get_interrupt_table
from .params.agent import (
    EVENT_AGENT_BOOT,
    EVENT_ARCHIVE_ALERT,
    EVENT_CROSS_REVIEW,
    EVENT_REVIEW_REQUESTED,
    EVENT_TASK_ASSIGN,
    EVENT_TOKEN_USAGE,
)
from .params.kernel import (
    AUDIT_FLUSH_SIZE,
    BARRIER_DEFAULT_COUNT,
    SYSCALL_AUDIT_DETAIL_MAXLEN,
    SYSCALL_AUDIT_MAX,
    SYSCALL_AUDIT_QUERY_LIMIT,
    SYSCALL_DEFAULT_COST,
    SYSCALL_DEFAULT_FALLBACK,
    SYSCALL_DEFAULT_RESOURCE,
    SYSCALL_DEFAULT_RING,
    SYSCALL_DEFAULT_SIGNAL_TYPE,
    SYSCALL_REGISTER_DEFAULT_AGENT,
    GateStatus,
)
from .process import ProcessState, get_table
from .resource import ResourceProfile, get_limiter
from .skill import get_skill_manager
from .sync import get_barrier, get_condition, get_lock_bus, get_mutex, get_rwlock, get_semaphore
from .sync import registry_status as sync_status
from .tool_chain import get_tool_chain
from .vfs import get_vfs

logger = logging.getLogger(__name__)

# ── Audit trail (batch queue for reduced lock contention) ──

_audit_log: deque[dict] = deque(maxlen=SYSCALL_AUDIT_MAX)
_audit_lock = threading.Lock()
_thread_audit_buffer = threading.local()
_AUDIT_FLUSH_SIZE = AUDIT_FLUSH_SIZE


def _audit(op: str, agent_id: str, result: dict, detail: str = "") -> None:
    """Record a syscall in the audit trail.

    Uses a thread-local buffer to batch entries and reduce global lock contention.
    deque(maxlen=SYSCALL_AUDIT_MAX) handles O(1) pruning automatically.
    """
    entry = {
        "op": op,
        "agent_id": agent_id,
        "success": result.get("success", False),
        "error": result.get("error", ""),
        "detail": detail[:SYSCALL_AUDIT_DETAIL_MAXLEN],
        "timestamp": time.time(),
    }
    buf = getattr(_thread_audit_buffer, "entries", None)
    if buf is None:
        _thread_audit_buffer.entries = []
        buf = _thread_audit_buffer.entries
    buf.append(entry)
    if len(buf) >= _AUDIT_FLUSH_SIZE:
        with _audit_lock:
            _audit_log.extend(buf)
        _thread_audit_buffer.entries = []


def flush_audit_buffer() -> None:
    """Flush any remaining thread-local audit entries into the shared log.

    Called by the kernel shutdown sequence to ensure no entries are lost.
    """
    buf = getattr(_thread_audit_buffer, "entries", None)
    if buf:
        with _audit_lock:
            _audit_log.extend(buf)
        _thread_audit_buffer.entries = []


def record_audit(op: str, agent_id: str, success: bool = True,
                 error: str = "", detail: str = "") -> None:
    """Record an arbitrary event in the syscall audit trail."""
    result = {"success": success, "error": error}
    _audit(op, agent_id, result, detail)


def get_audit_log(limit: int = SYSCALL_AUDIT_QUERY_LIMIT, agent_id: str = "") -> list[dict]:
    """Query the syscall audit trail. Filter by agent_id if given.

    Optimization: islice copies only the tail portion (O(k) not O(N));
    avoids copying the full 5000-entry deque under lock.
    """
    with _audit_lock:
        total = len(_audit_log)
        if agent_id:
            # Agent filter needs full scan — keep lock brief by copying the whole deque once
            safe_slice = list(_audit_log)
        else:
            # Common case: only copy the tail we need (limit*4 entries, max ~400)
            n = min(total, limit * 4)
            safe_slice = list(islice(_audit_log, total - n, total))
    if agent_id:
        return [e for e in safe_slice if e["agent_id"] == agent_id][-limit:]
    return safe_slice[-limit:]


def clear_audit_log() -> None:
    """Clear the syscall audit trail entirely."""
    with _audit_lock:
        _audit_log.clear()


# ── Syscall dispatcher ──

_SYSCALL_REGISTRY: dict[str, Any] = {}


def register_syscall(name: str, handler: Any) -> None:
    """Register a custom syscall handler."""
    sub = name.split(".", 1)[1] if "." in name else ""
    _SYSCALL_REGISTRY[name] = (handler, sub)


def syscall(op: str, *args, **kwargs) -> dict:
    """Unified syscall interface — all kernel operations go through this.

    Every call is audited.  Structured error codes returned on failure.
    Handlers are loaded from _SYSCALL_REGISTRY (pre-registered at init).

    Examples:
      syscall("mutex.acquire", mutex="file:config.py", agent_id="my-agent")
      syscall("signal.emit", type="task_cancel", target="my-agent")
      syscall("resource.check", agent_id="my-agent", resource="workers")
    """
    agent_id = kwargs.get("agent_id", "unknown")

    entry = _SYSCALL_REGISTRY.get(op)
    if entry is None:
        return {"success": False, "error": f"EINVAL: unknown syscall '{op}'",
                "error_code": "EINVAL"}
    handler, precomputed_sub = entry
    try:
        if precomputed_sub:
            kwargs["_sub"] = precomputed_sub
        r = handler(agent_id, kwargs)
    except KeyError as e:
        r = {"success": False, "error": f"EINVAL: missing key {e}", "error_code": "EINVAL"}
    except AttributeError as e:
        r = {"success": False, "error": f"ENOSYS: {e}", "error_code": "ENOSYS"}
    except Exception as e:
        r = {"success": False, "error": f"EFAULT: {e}", "error_code": "EFAULT"}
    _audit(op, agent_id, r)
    return r


# ── Built-in syscall handlers ──

def _sys_mutex(agent_id: str, kw: dict) -> dict:
    sub = kw.get("_sub", "acquire")
    m = get_mutex(kw.get("mutex", SYSCALL_DEFAULT_FALLBACK))
    return getattr(m, sub)(agent_id, **{k: v for k, v in kw.items()
                                         if k not in ("mutex", "agent_id", "_sub")})


def _sys_semaphore(agent_id: str, kw: dict) -> dict:
    sub = kw.get("_sub", "acquire")
    s = get_semaphore(kw.get("sem", SYSCALL_DEFAULT_FALLBACK))
    return getattr(s, sub)(agent_id)


def _sys_barrier(agent_id: str, kw: dict) -> dict:
    sub = kw.get("_sub", "wait")
    b = get_barrier(kw.get("barrier", SYSCALL_DEFAULT_FALLBACK), kw.get("count", BARRIER_DEFAULT_COUNT))
    if sub == "wait":
        return b.wait(agent_id)
    if sub == "reset":
        return b.reset()
    return {"success": False, "error": f"unknown barrier op: {sub}"}


def _sys_condition(agent_id: str, kw: dict) -> dict:
    sub = kw.get("_sub", "wait")
    c = get_condition(kw.get("cv", SYSCALL_DEFAULT_FALLBACK))
    return getattr(c, sub)(agent_id)


def _sys_signal(agent_id: str, kw: dict) -> dict:
    sub = kw.get("_sub", "emit")
    bus = get_event_bus()
    sig = Signal(type=SignalType[kw.get("type", SYSCALL_DEFAULT_SIGNAL_TYPE).upper()],
                 sender=agent_id, target=kw.get("target", ""), data=kw.get("data", {}))
    return {"dispatched": getattr(bus, sub)(sig)}


def _sys_resource(agent_id: str, kw: dict) -> dict:
    sub = kw.get("_sub", "check")
    lm = get_limiter()
    return getattr(lm, sub)(agent_id, kw.get("resource", SYSCALL_DEFAULT_RESOURCE),
                            kw.get("cost", SYSCALL_DEFAULT_COST))


def _sys_process(agent_id: str, kw: dict) -> dict:
    sub = kw.get("_sub", "list")
    pt = get_table()
    if sub == "spawn":
        return {"success": True, "pid": pt.spawn(
            kw.get("name", ""), kw.get("role", ""),
            kw.get("parent_pid", 0), kw.get("ring", SYSCALL_DEFAULT_RING),
        ).pid}
    if sub == "exit":
        return {"success": pt.exit(kw.get("pid", 0), kw.get("exit_code", 0), kw.get("reason", ""))}
    if sub == "list":
        return {"success": True, "processes": pt.list()}
    return {"success": False, "error": f"unknown process op: {sub}"}


def _sys_alloc(agent_id: str, kw: dict) -> dict:
    sub = kw.get("_sub", "usage")
    al = get_allocator()
    if sub == "alloc":
        return al.alloc(agent_id, kw.get("resource", SYSCALL_DEFAULT_RESOURCE),
                        kw.get("amount", 1), kw.get("purpose", ""))
    if sub == "free":
        return al.free(agent_id, kw.get("resource", SYSCALL_DEFAULT_RESOURCE),
                       kw.get("amount", 1))
    if sub == "usage":
        return {"success": True, "usage": al.usage(agent_id)}
    return {"success": False, "error": f"unknown alloc op: {sub}"}


def _register_builtin_syscalls() -> None:
    """Register only valid sub-command combinations into _SYSCALL_REGISTRY.

    Each handler group registers only the sub-commands it actually implements,
    eliminating ~109 phantom entries (136 → 27) and returning EINVAL
    for unrecognized operations instead of ENOSYS/AttributeError.
    """
    _groups: dict[str, tuple[Any, list[str]]] = {
        "mutex":     (_sys_mutex,     ["acquire", "release", "status"]),
        "semaphore": (_sys_semaphore, ["acquire", "release", "status"]),
        "barrier":   (_sys_barrier,   ["wait", "reset"]),
        "condition": (_sys_condition, ["wait", "signal", "broadcast"]),
        "signal":    (_sys_signal,    ["emit", "on", "off"]),
        "resource":  (_sys_resource,  ["check", "release", "usage"]),
        "process":   (_sys_process,   ["spawn", "exit", "list"]),
        "alloc":     (_sys_alloc,     ["alloc", "free", "usage"]),
    }
    for group, (handler, subs) in _groups.items():
        for sub in subs:
            _SYSCALL_REGISTRY[f"{group}.{sub}"] = (handler, sub)


_register_builtin_syscalls()

def emit_signal(signal_type: str, sender: str = "system", target: str = "",
                data: dict | None = None) -> int:
    """Emit a typed signal onto the kernel event bus."""
    bus = get_event_bus()
    sig = Signal(type=SignalType[signal_type.upper()], sender=sender,
                 target=target, data=data or {})
    return bus.emit(sig)


def push_event(event_type: str, data: dict | None = None) -> None:
    """Push an event to the kernel event bus (migrated from server.py)."""
    from .params.agent import EVENT_TASK_ASSIGN
    emit_signal(EVENT_TASK_ASSIGN, sender="l1.kernel.push_event", target="cell",
                data={"type": event_type, **(data or {})})


def health() -> dict:
    """Kernel health check — probes all kernel modules."""
    import time as _t
    probes = [
        ("sync",  lambda: len(get_mutex("_h").status()) > 0),
        ("event", lambda: get_event_bus().stats() is not None),
        ("constitution", lambda: len(get_constitution().rules_list()) > 0),
        ("allocator", lambda: get_allocator().summary() is not None),
        ("resource", lambda: get_limiter().all_usage() is not None),
        ("gatechain", lambda: get_gatechain().ledger is not None),
        ("process", lambda: get_table().get(0) is not None),
        ("interrupt", lambda: get_interrupt_table().counts() is not None),
        ("device", lambda: bool(get_device_manager().stats())),
    ]
    results = {}
    all_ok = True
    for name, fn in probes:
        t0 = _t.time()
        try:
            ok = fn()
            results[name] = {"status": GateStatus.PASS if ok else "FAIL",
                             "elapsed_ms": round((_t.time() - t0) * 1000, 1)}
            if not ok:
                all_ok = False
        except Exception as e:
            results[name] = {"status": "FAIL", "error": str(e)}
            all_ok = False
    return {"status": GateStatus.PASS if all_ok else "FAIL",
            "modules": results, "module_count": len(probes)}


def register_process(name: str, role: str = "", ring: int = SYSCALL_DEFAULT_RING,
                     agent_id: str = SYSCALL_REGISTER_DEFAULT_AGENT) -> int:
    return syscall("process.spawn", agent_id=agent_id,
                   name=name, role=role, ring=ring).get("pid", 0)


__all__ = [
    "DeviceHealth",
    "DeviceType",
    "Interrupt",
    "InterruptType",
    "ProcessState",
    "ResourceProfile",
    "Signal",
    "SignalType",
    "clear_audit_log",
    "emit_signal",
    "fire",
    "get_allocator",
    "get_audit_log",
    "get_barrier",
    "get_condition",
    "get_constitution",
    "get_device_manager",
    "get_event_bus",
    "get_gatechain",
    "get_interrupt_table",
    "get_limiter",
    "get_lock_bus",
    "get_mutex",
    "get_rwlock",
    "get_semaphore",
    "get_skill_manager",
    "get_table",
    "get_tool_chain",
    "get_vfs",
    "health",
    "push_event",
    "register_process",
    "EVENT_TASK_ASSIGN",
    "EVENT_REVIEW_REQUESTED",
    "EVENT_TOKEN_USAGE",
    "EVENT_CROSS_REVIEW",
    "EVENT_AGENT_BOOT",
    "EVENT_ARCHIVE_ALERT",
    "register_syscall",
    "sync_status",
    "syscall",
    # ConfigDiscovery
    "discovery",
]
