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
import threading
import time
from collections.abc import Callable
from enum import Enum, auto

from .params.kernel import (
    SHUTDOWN_TIMEOUT,
    WATCHDOG_IDLE_LIMIT,
    WATCHDOG_INTERRUPT_LIMIT,
    WATCHDOG_INTERVAL,
    WATCHDOG_ZOMBIE_LIMIT,
)

logger = logging.getLogger(__name__)


class OSState(Enum):
    """OSState — enum of DOWN, STARTING, RUNNING, STOPPING...."""
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
        self._shutdown_hooks: list[Callable] = []
        self._boot_handler: Callable | None = None
        self._shutdown_handler: Callable | None = None
        self._terminal_reset_handler: Callable | None = None
        self._cell_reset_handler: Callable | None = None

    def register_boot_handler(self, handler: Callable) -> None:
        """Register a boot function from the services layer."""
        self._boot_handler = handler

    def register_shutdown_handler(self, handler: Callable) -> None:
        """Register a shutdown persistence function from the services layer."""
        self._shutdown_handler = handler

    def register_terminal_reset(self, handler: Callable) -> None:
        """Register a terminal reset function from the services layer."""
        self._terminal_reset_handler = handler

    def register_cell_reset(self, handler: Callable) -> None:
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
            if not self._boot_handler:
                return {"success": False, "error": "no boot handler registered — call register_boot_handler() first"}
            r = self._boot_handler(agent_config)
            if r.get("success"):
                with self._lock:
                    self.state = OSState.RUNNING
                self._boot_result = r
                logger.info("OS boot OK: %s agents in %.2fs", r.get("agent_count", 0), r.get("elapsed", 0))
                return r
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
        # Run shutdown hooks (with timeout per hook)
        for i, hook in enumerate(self._shutdown_hooks):
            try:
                t = threading.Thread(target=hook, daemon=True)
                t.start()
                t.join(timeout=SHUTDOWN_TIMEOUT)
                results[f"hook_{i}"] = "ok" if not t.is_alive() else "timeout"
            except Exception as e:
                results[f"hook_{i}"] = str(e)

        # Dump state to memories (with timeout, like shutdown hooks)
        try:
            if self._shutdown_handler:
                holder: dict = {}
                def _run() -> None:
                    holder["r"] = self._shutdown_handler()
                t = threading.Thread(target=_run, daemon=True)
                t.start()
                t.join(timeout=SHUTDOWN_TIMEOUT)
                if t.is_alive():
                    logger.warning("shutdown handler timed out after %.1fs", SHUTDOWN_TIMEOUT)
                    results["memories"] = "timeout"
                else:
                    r = holder.get("r") or {"results": {}}
                    results["memories"] = r.get("results", {})
            else:
                logger.warning("no shutdown_handler registered — memories not persisted")
                results["memories"] = {}
        except Exception as e:
            results["memories"] = f"error: {e}"

        # Stop watchdog
        self._watchdog_running = False

        # Reset Cells
        try:
            if self._terminal_reset_handler:
                t = threading.Thread(target=self._terminal_reset_handler, daemon=True)
                t.start()
                t.join(timeout=SHUTDOWN_TIMEOUT)
                results["reset_term"] = "ok" if not t.is_alive() else "timeout"
            else:
                logger.warning("no terminal_reset_handler registered — terminals not reset")
                results["reset_term"] = "skip"
            if self._cell_reset_handler:
                t = threading.Thread(target=self._cell_reset_handler, daemon=True)
                t.start()
                t.join(timeout=SHUTDOWN_TIMEOUT)
                results["reset_cell"] = "ok" if not t.is_alive() else "timeout"
            else:
                logger.warning("no cell_reset_handler registered — cells not reset")
                results["reset_cell"] = "skip"
            results.setdefault("reset", "ok")
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
        """Single watchdog check — process liveness, interrupt health (single pass)."""
        from .interrupt import get_table as int_table
        from .process import get_table

        pt = get_table()
        procs = pt.list()
        now = time.time()

        # Single pass: count zombies + check idle in one O(N)
        zombie_count = 0
        for p in procs:
            state = p.get("state", "")
            if state == "ZOMBIE":
                zombie_count += 1
            elif state in ("READY", "RUNNING"):
                idle = p.get("idle", 0)
                if idle > WATCHDOG_IDLE_LIMIT:
                    logger.info("watchdog: %s idle for %.0fs", p.get("name", ""), idle)

        if zombie_count > WATCHDOG_ZOMBIE_LIMIT:
            logger.warning("watchdog: %d zombie processes", zombie_count)

        # Check interrupt health (independent, no process data needed)
        it = int_table()
        for iname, count in it.counts().items():
            if count > WATCHDOG_INTERRUPT_LIMIT:
                logger.warning("watchdog: high interrupt %s = %d", iname, count)

    # ── Register shutdown hook ──

    def on_shutdown(self, hook: Callable) -> None:
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
_os_lock = threading.Lock()


def get_os() -> OS:
    global _os
    if _os is None:
        with _os_lock:
            if _os is None:
                _os = OS()
    return _os


def reset_os() -> None:
    global _os
    _os = None
