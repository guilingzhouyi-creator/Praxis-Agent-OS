"""Supervisor — multi-process lifecycle manager for Praxis Agent OS.

Spawns and monitors: kernel, api, sandbox, llm-worker processes.
Health check + auto-restart + dynamic scaling.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time

from l1.kernel.params.system import (
    SUPERVISOR_DEFAULT_REPLICAS,
    SUPERVISOR_IDLE_INTERVAL,
    SUPERVISOR_LLM_REPLICAS,
    SUPERVISOR_MONITOR_INTERVAL,
    SUPERVISOR_SANDBOX_REPLICAS,
    SUPERVISOR_WAIT_TIMEOUT,
)

logger = logging.getLogger(__name__)


class Supervisor:
    """Four-process lifecycle manager."""

    ROLE_KERNEL = "kernel"
    ROLE_API = "api"
    ROLE_SANDBOX = "sandbox"
    ROLE_LLM = "llm"

    PROCESSES: dict[str, dict] = {
        ROLE_KERNEL: {
            "entry": "l4.supervisor",
            "restart": True,
            "depends": [],
            "replicas": SUPERVISOR_DEFAULT_REPLICAS,
            "health": "/api/health",
        },
        ROLE_API: {
            "entry": "l4.api.api_gateway",
            "restart": True,
            "depends": [ROLE_KERNEL],
            "replicas": SUPERVISOR_DEFAULT_REPLICAS,
            "health": "/api/health",
        },
        ROLE_SANDBOX: {
            "entry": "l4.sandbox.server",
            "restart": True,
            "depends": [ROLE_KERNEL],
            "replicas": SUPERVISOR_SANDBOX_REPLICAS,
            "health": "",
        },
        ROLE_LLM: {
            "entry": "l4.llm_worker.server",
            "restart": True,
            "depends": [],
            "replicas": SUPERVISOR_LLM_REPLICAS,
            "health": "",
        },
    }

    def __init__(self):
        self._procs: dict[str, list[subprocess.Popen]] = {}
        self._running = False

    def start(self) -> dict:
        """Start all child processes."""
        self._running = True
        order = self._resolve_deps()
        results = {}
        for role in order:
            cfg = self.PROCESSES[role]
            for i in range(cfg.get("replicas", 1)):
                try:
                    p = subprocess.Popen(
                        [sys.executable, "-m", cfg["entry"]],
                        env={**os.environ, "PRAXIS_ROLE": role,
                             "PRAXIS_REPLICA": str(i)},
                    )
                    self._procs.setdefault(role, []).append(p)
                except Exception as e:
                    logger.error("supervisor: failed to start %s[%d]: %s", role, i, e)
            results[role] = len(self._procs.get(role, []))
        # Start monitoring thread
        t = threading.Thread(target=self._monitor_loop, daemon=True)
        t.start()
        return {"success": True, "processes": results}

    def stop(self) -> dict:
        """Stop all child processes."""
        self._running = False
        for role, procs in self._procs.items():
            for p in procs:
                try:
                    p.terminate()
                except Exception:
                    logger.debug("supervisor: proc terminate failed")
            for p in procs:
                try:
                    p.wait(timeout=SUPERVISOR_WAIT_TIMEOUT)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        logger.debug("supervisor: proc kill failed")
        return {"success": True, "stopped": sum(len(v) for v in self._procs.values())}

    def scale(self, role: str, n: int) -> dict:
        """Dynamically scale processes."""
        if role not in self.PROCESSES:
            return {"success": False, "error": f"unknown role: {role}"}
        current = len(self._procs.get(role, []))
        if n > current:
            for _ in range(n - current):
                p = subprocess.Popen(
                    [sys.executable, "-m", self.PROCESSES[role]["entry"]],
                    env={**os.environ, "PRAXIS_ROLE": role},
                )
                self._procs.setdefault(role, []).append(p)
        elif n < current:
            for p in self._procs[role][n:]:
                try:
                    p.terminate()
                except Exception:
                    logger.debug("supervisor: proc terminate failed")
            self._procs[role] = self._procs[role][:n]
        return {"success": True, "role": role, "replicas": n}

    def status(self) -> dict:
        """Query process status."""
        result = {}
        for role, procs in self._procs.items():
            alive = sum(1 for p in procs if p.poll() is None)
            result[role] = {"alive": alive, "total": len(procs)}
        return {"success": True, "processes": result}

    def _resolve_deps(self) -> list[str]:
        """Topological sort: start processes without dependencies first."""
        ordered = []
        remaining = set(self.PROCESSES.keys())
        while remaining:
            ready = {r for r in remaining
                     if all(d not in remaining for d in self.PROCESSES[r]["depends"])}
            if not ready:
                logger.warning("supervisor: circular dependency detected: %s", remaining)
                ordered.extend(remaining)
                break
            for r in sorted(ready):
                ordered.append(r)
                remaining.remove(r)
        return ordered

    def _monitor_loop(self) -> None:
        """Health check + auto restart."""
        while self._running:
            time.sleep(SUPERVISOR_MONITOR_INTERVAL)
            for role, procs in list(self._procs.items()):
                if not self.PROCESSES[role]["restart"]:
                    continue
                for i, p in enumerate(procs):
                    if p.poll() is not None:
                        logger.warning("supervisor: %s[%d] crashed, restarting", role, i)
                        try:
                            new_p = subprocess.Popen(
                                [sys.executable, "-m", self.PROCESSES[role]["entry"]],
                                env={**os.environ, "PRAXIS_ROLE": role,
                                     "PRAXIS_REPLICA": str(i)},
                            )
                            procs[i] = new_p
                        except Exception as e:
                            logger.error("supervisor: restart %s[%d] failed: %s", role, i, e)


# ── Entry points ──

def main() -> None:
    """praxis-supervisor: start and monitor all child processes."""
    logging.basicConfig(level=logging.INFO)
    sv = get_supervisor()
    r = sv.start()
    logger.info("supervisor started: %s", r)
    try:
        while True:
            time.sleep(SUPERVISOR_IDLE_INTERVAL)
    except KeyboardInterrupt:
        sv.stop()


def start_kernel() -> None:
    """praxis-kernel: start the kernel process (Cell + AgentLoop + Memory)."""
    logging.basicConfig(level=logging.INFO)
    os.environ.setdefault("PRAXIS_ROLE", "kernel")
    from l3.boot.boot import boot
    r = boot(interactive=False)
    logger.info("kernel booted: %s", r.get("status", "?"))


def start_api() -> None:
    """praxis-api: start the API gateway process."""
    logging.basicConfig(level=logging.INFO)
    os.environ.setdefault("PRAXIS_ROLE", "api")
    from l4.api.api_gateway import start_api as _start_api
    _start_api(
        host=os.environ.get("PRAXIS_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("PRAXIS_API_PORT", "8080")),
        auth_token=os.environ.get("PRAXIS_API_TOKEN", ""),
    )


# ── Singleton ──

_supervisor: Supervisor | None = None
_supervisor_lock = threading.Lock()


def get_supervisor() -> Supervisor:
    global _supervisor
    if _supervisor is None:
        with _supervisor_lock:
            if _supervisor is None:
                _supervisor = Supervisor()
    return _supervisor


def reset_supervisor() -> None:
    global _supervisor
    _supervisor = None


if __name__ == "__main__":
    main()
