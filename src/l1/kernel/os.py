"""OS Lifecycle Coordinator — unified boot/shutdown/restart/watchdog.

Bridges the gap between kernel primitives and OS behavior:
  - boot:     load constitution → init kernel → create Cells → start services
  - shutdown: stop all Cells → persist state → flush events → stop kernel
  - restart:  shutdown → boot (preserving memories)
  - watchdog: periodic health checks, process liveness, crash detection

Usage:
  from l1.kernel.os import OS
  os = OS()
  os.boot()
  os.watchdog_start()
  # ... runtime ...
  os.shutdown()
"""

from __future__ import annotations

import logging
import os as _os
import signal
import threading
import time
from enum import Enum, auto
from typing import Any

from .params.kernel import (
    WATCHDOG_INTERVAL,
    WATCHDOG_ZOMBIE_LIMIT,
    WATCHDOG_IDLE_LIMIT,
    WATCHDOG_INTERRUPT_LIMIT,
)

logger = logging.getLogger(__name__)


class OSState(Enum):
    DOWN = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    CRASHED = auto()


class OS:
    """Central OS lifecycle manager — boot, shutdown, restart, watchdog.

    Services layer registers callbacks via ``register_boot_handler``
    and ``register_shutdown_handler`` to avoid kernel→services imports.
    """

    def __init__(self):
        self.state = OSState.DOWN
        self.boot_time = 0.0
        self.uptime = 0.0
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_running = False
        self._lock = threading.Lock()
        self._boot_result: dict = {}
        self._shutdown_hooks: list[callable] = []
        self._boot_handler: callable | None = None
        self._shutdown_handler: callable | None = None
        self._terminal_reset_handler: callable | None = None
        self._cell_reset_handler: callable | None = None

    def register_boot_handler(self, handler: callable) -> None:
        """Register a boot function from the services layer."""
        self._boot_handler = handler

    def register_shutdown_handler(self, handler: callable) -> None:
        """Register a shutdown persistence function from the services layer."""
        self._shutdown_handler = handler

    def register_terminal_reset(self, handler: callable) -> None:
        """Register a terminal reset function from the services layer."""
        self._terminal_reset_handler = handler

    def register_cell_reset(self, handler: callable) -> None:
        """Register a cell reset function from the services layer."""
        self._cell_reset_handler = handler

    # ── Boot ──

    def boot(self, agent_config: list[tuple[str, str, list[str]]] | None = None) -> dict:
        """Full OS boot sequence."""
        with self._lock:
            if self.state in (OSState.RUNNING, OSState.STARTING):
                return {"success": False, "error": f"already {self.state.name}"}
            self.state = OSState.STARTING
            self.boot_time = time.time()

        try:
            if self._boot_handler:
                r = self._boot_handler(agent_config)
            else:
                from ..services.boot import boot as _boot
                r = _boot(agent_config)
            if r.get("success"):
                with self._lock:
                    self.state = OSState.RUNNING
                self._boot_result = r
                logger.info("OS boot OK: %s agents in %.2fs", r.get("agent_count", 0), r.get("elapsed", 0))
                return r
            else:
                with self._lock:
                    self.state = OSState.CRASHED
                return r
        except Exception as e:
            with self._lock:
                self.state = OSState.CRASHED
            return {"success": False, "error": str(e)}

    # ── Shutdown ──

    def shutdown(self) -> dict:
        """Graceful OS shutdown."""
        with self._lock:
            if self.state == OSState.STOPPING:
                return {"success": True, "reason": "already stopping"}
            was = self.state
            self.state = OSState.STOPPING

        results = {}

        # Run shutdown hooks
        for hook in self._shutdown_hooks:
            try:
                hook()
                results["hook"] = "ok"
            except Exception as e:
                results["hook"] = str(e)

        # Dump state to memories
        try:
            if self._shutdown_handler:
                r = self._shutdown_handler()
            else:
                from ..services.memory_init import shutdown_to_memories
                r = shutdown_to_memories()
            results["memories"] = r.get("results", {})
        except Exception as e:
            results["memories"] = f"error: {e}"

        # Stop watchdog
        self._watchdog_running = False

        # Reset Cells
        try:
            if self._terminal_reset_handler:
                self._terminal_reset_handler()
            else:
                from ..services.agent_terminal import reset_terminals
                reset_terminals()
            if self._cell_reset_handler:
                self._cell_reset_handler()
            else:
                from ..services.cell import reset_cells
                reset_cells()
            results["reset"] = "ok"
        except Exception as e:
            results["reset"] = f"error: {e}"

        with self._lock:
            self.uptime = time.time() - self.boot_time
            self.state = OSState.DOWN

        logger.info("OS shutdown: state=%s uptime=%.1fs results=%s", was.name, self.uptime, results)
        return {"success": True, "uptime": round(self.uptime, 1), "results": results}

    # ── Restart ──

    def restart(self, agent_config: list[tuple[str, str, list[str]]] | None = None) -> dict:
        """Shutdown then boot. Preserves memories."""
        sd = self.shutdown()
        if not sd.get("success"):
            return {"success": False, "error": f"shutdown failed: {sd.get('error', '')}"}
        return self.boot(agent_config)

    # ── Watchdog ──

    def watchdog_start(self, interval: float = WATCHDOG_INTERVAL) -> None:
        """Start background watchdog that monitors process health."""
        if self._watchdog_running:
            return
        self._watchdog_running = True
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, args=(interval,), daemon=True,
        )
        self._watchdog_thread.start()
        logger.info("watchdog started (every %.0fs)", interval)

    def _watchdog_loop(self, interval: float) -> None:
        while self._watchdog_running:
            time.sleep(interval)
            try:
                self._watchdog_tick()
            except Exception as e:
                logger.warning("watchdog error: %s", e)

    def _watchdog_tick(self) -> None:
        """Single watchdog check — process liveness, interrupt health."""
        from .process import get_table, ProcessState
        from .interrupt import get_table as int_table

        pt = get_table()
        procs = pt.list()

        # Check for excess ZOMBIE processes
        zombies = [p for p in procs if p.get("state") == "ZOMBIE"]
        if len(zombies) > WATCHDOG_ZOMBIE_LIMIT:
            logger.warning("watchdog: %d zombie processes", len(zombies))

        # Check for idle agents that haven't processed cards recently
        now = time.time()
        for p in procs:
            idle = p.get("idle", 0)
            name = p.get("name", "")
            if idle > WATCHDOG_IDLE_LIMIT and p.get("state") in ("READY", "RUNNING"):
                logger.info("watchdog: %s idle for %.0fs", name, idle)

        # Check interrupt health
        it = int_table()
        counts = it.counts()
        for iname, count in counts.items():
            if count > WATCHDOG_INTERRUPT_LIMIT:
                logger.warning("watchdog: high interrupt %s = %d", iname, count)

    # ── Register shutdown hook ──

    def on_shutdown(self, hook: callable) -> None:
        """Register a function to be called during shutdown."""
        self._shutdown_hooks.append(hook)

    # ── Status ──

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self.state.name,
                "uptime": round(time.time() - self.boot_time, 1) if self.state == OSState.RUNNING else 0,
                "watchdog": self._watchdog_running,
                "hooks": len(self._shutdown_hooks),
            }


_os: OS | None = None


def get_os() -> OS:
    global _os
    if _os is None:
        _os = OS()
    return _os


def reset_os() -> None:
    global _os
    _os = None
