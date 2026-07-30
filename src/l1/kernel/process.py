"""Process table and Process Control Block (PCB) for Agent OS.

Each AgentTerminal registers itself as a process in the kernel process table.
The PCB holds identity, state, resource usage, parent/child relationships,
and lifecycle timestamps.

Architecture:
  ProcessTable (singleton)
  ├── PCB for agent-http (PID 1)
  │   ├── state: IDLE/RUNNING/BLOCKED/ZOMBIE
  │   ├── resources: tokens, workers, scouts
  │   ├── children: [PID 4, PID 5]  (scout sub-processes)
  │   └── parent: PID 0 (init)
  ├── PCB for agent-business (PID 2)
  └── PCB for scout-1 (PID 4)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .params.kernel import (
    PROCESS_AUDIT_MAX,
    PROCESS_INIT_NAME,
    PROCESS_INIT_ROLE,
    PROCESS_INIT_RING,
    PROCESS_DEFAULT_RING,
    PROCESS_AUDIT_LOG_LIMIT,
    ZOMBIE_REAPER_INTERVAL,
    ZOMBIE_MAX_AGE,
    PROCESS_TABLE_MAX,
)

logger = logging.getLogger(__name__)


class ProcessState(Enum):
    READY = auto()
    RUNNING = auto()
    BLOCKED = auto()
    ZOMBIE = auto()
    STOPPED = auto()


# ── PCB Finite State Machine (FSM) ──────────────────────────────────────────
# All state transitions must be declared here.  Illegal transitions are logged
# and rejected, making the state machine self-documenting and safe to extend.

_PCB_TRANSITIONS: dict[ProcessState, dict[str, ProcessState | None]] = {
    ProcessState.READY: {
        "run":    ProcessState.RUNNING,
        "crash":  ProcessState.ZOMBIE,  # killed before first run
        "stop":   ProcessState.STOPPED,
    },
    ProcessState.RUNNING: {
        "block":  ProcessState.BLOCKED,
        "yield":  ProcessState.READY,
        "stop":   ProcessState.STOPPED,
        "crash":  ProcessState.ZOMBIE,
    },
    ProcessState.BLOCKED: {
        "wake":   ProcessState.READY,
        "stop":   ProcessState.STOPPED,
        "crash":  ProcessState.ZOMBIE,
    },
    ProcessState.ZOMBIE: {
        "reap":   None,  # None → remove from table
    },
    ProcessState.STOPPED: {
        "resume": ProcessState.READY,
        "reap":   None,
    },
}


def _apply_transition(pcb: PCB, action: str) -> bool:
    """Apply an FSM transition to *pcb*.

    Returns *True* if the transition was valid and applied.
    ``action="reap"`` maps to *None* in the table, which signals
    the caller to remove the PCB from the table.
    """
    allowed = _PCB_TRANSITIONS.get(pcb.state, {})
    target = allowed.get(action)
    if target is None and action == "reap":
        # reap is always valid from ZOMBIE or STOPPED
        return True
    if target is None:
        logger.warning("illegal FSM transition: %s → %s (state=%s)",
                       pcb.name, action, pcb.state.name)
        return False
    pcb.state = target
    pcb.touch()
    return True


@dataclass
class ResourceUsage:
    tokens_allocated: int = 0
    tokens_used: int = 0
    workers_active: int = 0
    scouts_active: int = 0
    memory_entries: int = 0
    cards_processed: int = 0
    cpu_time: float = 0.0


class PCB:
    """Process Control Block — one per agent or scout."""

    def __init__(self, pid: int, name: str, role: str = "",
                 parent_pid: int = 0, ring: int = PROCESS_DEFAULT_RING):
        self.pid = pid
        self.name = name
        self.role = role
        self.parent_pid = parent_pid
        self.ring = ring
        self.state = ProcessState.READY
        self.resources = ResourceUsage()
        self.created_at = time.time()
        self.last_active = time.time()
        self.exit_code: int | None = None
        self.exit_reason: str = ""
        self.identity_verified: bool = False  # Ed25519 keypair generated (#P5)

    def touch(self) -> None:
        """Mark this PCB as recently active (update last_active timestamp)."""
        self.last_active = time.time()

    def record_tokens(self, allocated: int, used: int) -> None:
        """Record token allocation and usage stats."""
        self.resources.tokens_allocated += allocated
        self.resources.tokens_used += used
        self.touch()

    def record_card(self) -> None:
        """Increment the card processing counter."""
        self.resources.cards_processed += 1
        self.touch()

    def record_cpu(self, seconds: float) -> None:
        """Accumulate CPU time for this process."""
        self.resources.cpu_time += seconds
        self.touch()

    def record_alloc(self, tokens: int = 0) -> None:
        """Record a token allocation event."""
        self.resources.tokens_allocated += tokens

    def record_use(self, tokens: int = 0, cpu_ms: float = 0) -> None:
        """Record token usage and optional CPU time."""
        self.resources.tokens_used += tokens
        self.resources.cpu_time += cpu_ms
        self.touch()

    def record_scout(self, delta: int = 1) -> None:
        """Record a scout count delta."""
        self.resources.scouts_active = max(0, self.resources.scouts_active + delta)

    def snapshot(self) -> dict:
        """Return a dict snapshot of current PCB state."""
        return {
            "pid": self.pid,
            "name": self.name,
            "role": self.role,
            "state": self.state.name,
            "ring": self.ring,
            "parent_pid": self.parent_pid,
            "uptime": round(time.time() - self.created_at, 1),
            "idle": round(time.time() - self.last_active, 1),
            **self.resources.__dict__,
        }


class ProcessTable:
    """Kernel process table — singleton, thread-safe.

    All processes (agents, scouts) must register here.
    PID 0 is the init process (kernel itself).
    """

    def __init__(self, gc_interval: float = 60.0):
        self._lock = threading.Lock()
        self._processes: dict[int, PCB] = {}
        self._name_index: dict[str, int] = {}
        self._pid_to_name: dict[int, str] = {}  # reverse index: pid → name
        self._next_pid = 1
        self._audit_log: deque[dict] = deque(maxlen=PROCESS_AUDIT_MAX)

        # PID 0: kernel init
        init = PCB(pid=0, name=PROCESS_INIT_NAME, role=PROCESS_INIT_ROLE, ring=PROCESS_INIT_RING)
        init.state = ProcessState.RUNNING
        self._processes[0] = init

        # Background zombie reaper (daemon thread)
        self._gc_running = True
        threading.Thread(target=self._gc_loop, daemon=True,
                         name="zombie-reaper").start()

    def _gc_loop(self) -> None:
        """Background zombie reaper: reap zombies older than ZOMBIE_MAX_AGE, cap total processes."""
        while self._gc_running:
            time.sleep(ZOMBIE_REAPER_INTERVAL)
            try:
                with self._lock:
                    now = time.time()
                    zombies = [(pid, pcb) for pid, pcb in self._processes.items()
                               if pcb.state == ProcessState.ZOMBIE and now - pcb.last_active > ZOMBIE_MAX_AGE]
                    for pid, _ in zombies:
                        self._processes.pop(pid, None)
                        name = self._pid_to_name.pop(pid, None)
                        if name:
                            del self._name_index[name]
                    # Cap: if > PROCESS_TABLE_MAX processes, reap oldest STOPPED/ZOMBIE
                    if len(self._processes) > PROCESS_TABLE_MAX:
                        oldest = sorted(
                            [(pid, pcb) for pid, pcb in self._processes.items()
                             if pcb.state in (ProcessState.ZOMBIE, ProcessState.STOPPED)],
                            key=lambda x: x[1].last_active
                        )
                        # Build reverse index once to avoid O(N) dict comprehension per reap
                        pid_to_name = {p: n for n, p in self._name_index.items()}
                        for pid, _ in oldest[:len(self._processes) - 500]:
                            self._processes.pop(pid, None)
                            name = pid_to_name.pop(pid, None)
                            if name:
                                del self._name_index[name]
            except Exception as e:
                logger.warning("process gc: %s", e)

    def spawn(self, name: str, role: str = "", parent_pid: int = 0,
              ring: int = PROCESS_DEFAULT_RING) -> PCB:
        """Create a new process with the given identity, return the PCB."""
        with self._lock:
            pid = self._next_pid
            self._next_pid += 1
            pcb = PCB(pid=pid, name=name, role=role,
                      parent_pid=parent_pid, ring=ring)
            self._processes[pid] = pcb
            self._name_index[name] = pid
            self._pid_to_name[pid] = name
            self._audit("spawn", pid, name, role)
            return pcb

    def get(self, pid: int) -> PCB | None:
        """Look up a process by PID, return PCB or None."""
        with self._lock:
            return self._processes.get(pid)

    def get_by_name(self, name: str) -> PCB | None:
        """Look up a process by name, return PCB or None."""
        with self._lock:
            pid = self._name_index.get(name)
            return self._processes.get(pid) if pid else None

    def set_state(self, pid: int, state: ProcessState) -> bool:
        """Transition a process to the given state."""
        with self._lock:
            pcb = self._processes.get(pid)
            if not pcb:
                return False
            pcb.state = state
            pcb.touch()
            return True

    def mark_identity_verified(self, name: str) -> bool:
        """Mark an agent as having Ed25519 identity proof (called by IdentityService)."""
        with self._lock:
            pid = self._name_index.get(name)
            pcb = self._processes.get(pid) if pid else None
            if not pcb:
                return False
            pcb.identity_verified = True
            pcb.touch()
            return True

    def exit(self, pid: int, exit_code: int = 0, reason: str = "") -> bool:
        """Terminate a process — crash transition + record exit info."""
        with self._lock:
            pcb = self._processes.get(pid)
            if not pcb:
                return False
            if not _apply_transition(pcb, "crash"):
                return False
            pcb.exit_code = exit_code
            pcb.exit_reason = reason
            self._audit("exit", pid, pcb.name, reason or f"exit({exit_code})")
            return True

    def reap(self, pid: int) -> dict | None:
        """Remove a zombie process. Returns snapshot or None."""
        with self._lock:
            pcb = self._processes.pop(pid, None)
            if not pcb:
                return None
            self._name_index.pop(pcb.name, None)
            self._pid_to_name.pop(pid, None)
            self._audit("reap", pid, pcb.name, "")
            return pcb.snapshot()

    def list(self, state: ProcessState | None = None) -> list[dict]:
        """List all processes, optionally filtered by state."""
        with self._lock:
            result = [p.snapshot() for p in self._processes.values()
                      if state is None or p.state == state]
            return sorted(result, key=lambda x: x["pid"])

    def resource_summary(self) -> dict:
        """Return aggregated resource usage across all processes."""
        with self._lock:
            total = {"tokens": 0, "workers": 0, "scouts": 0, "cards": 0}
            for p in self._processes.values():
                total["tokens"] += p.resources.tokens_allocated
                total["workers"] += p.resources.workers_active
                total["scouts"] += p.resources.scouts_active
                total["cards"] += p.resources.cards_processed
            return total

    def _audit(self, op: str, pid: int, name: str, detail: str) -> None:
        self._audit_log.append({
            "op": op, "pid": pid, "name": name, "detail": detail,
            "timestamp": time.time(),
        })

    def audit_log(self, limit: int = PROCESS_AUDIT_LOG_LIMIT) -> list[dict]:
        """Return recent process audit log entries."""
        with self._lock:
            # deque does not support [-limit:] slicing; convert to list first
            return list(self._audit_log)[-limit:]


_table: ProcessTable | None = None
_table_lock = threading.Lock()


def get_table() -> ProcessTable:
    """Get the singleton ProcessTable instance."""
    global _table
    if _table is None:
        with _table_lock:
            if _table is None:
                _table = ProcessTable()
    return _table


def reset_table() -> None:
    """Reset the singleton ProcessTable instance (for testing)."""
    global _table
    _table = None
