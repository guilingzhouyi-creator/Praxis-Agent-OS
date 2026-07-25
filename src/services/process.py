"""Process manager — background process lifecycle.

Manages dev servers, build watchers, file watchers, etc.
Unlike TerminalService (interactive), these are headless daemon processes.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import IO, Any

from kernel.params import PROCESS_WAIT_TIMEOUT

logger = logging.getLogger(__name__)


@dataclass
class ProcessHandle:
    id: str
    name: str
    process: subprocess.Popen | None = None
    output: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def exit_code(self) -> int | None:
        return self.process.poll() if self.process else None

    def kill(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=PROCESS_WAIT_TIMEOUT)
            except subprocess.TimeoutExpired:
                self.process.kill()


class ProcessManager:
    def __init__(self):
        self._processes: dict[str, ProcessHandle] = {}
        self._lock = threading.Lock()
        self._next_id = 0

    def start(self, name: str, cmd: list[str], cwd: str | None = None,
              env: dict[str, str] | None = None) -> dict:
        pid = f"proc-{self._next_id}"
        self._next_id += 1
        try:
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except FileNotFoundError:
            return {"success": False, "error": f"command not found: {cmd[0]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        handle = ProcessHandle(id=pid, name=name, process=proc)
        with self._lock:
            self._processes[pid] = handle
        threading.Thread(target=self._reader, args=(pid,), daemon=True).start()
        logger.info("process started: %s (%s)", pid, " ".join(cmd))
        return {"success": True, "id": pid, "pid": proc.pid}

    def get(self, pid: str) -> dict:
        with self._lock:
            h = self._processes.get(pid)
        if not h:
            return {"success": False, "error": "process not found"}
        return {
            "success": True, "id": h.id, "name": h.name,
            "alive": h.is_alive, "exit_code": h.exit_code,
            "output": h.output[-50:],
            "uptime": time.time() - h.started_at,
        }

    def list(self) -> dict:
        with self._lock:
            procs = [{"id": h.id, "name": h.name, "alive": h.is_alive}
                     for h in self._processes.values()]
        return {"success": True, "processes": procs, "count": len(procs)}

    def kill(self, pid: str) -> dict:
        with self._lock:
            h = self._processes.pop(pid, None)
        if not h:
            return {"success": False, "error": "process not found"}
        h.kill()
        return {"success": True, "id": pid, "name": h.name}

    def killall(self) -> dict:
        killed = []
        with self._lock:
            pids = list(self._processes.keys())
        for pid in pids:
            r = self.kill(pid)
            if r["success"]:
                killed.append(pid)
        return {"success": True, "killed": len(killed)}

    def _reader(self, pid: str) -> None:
        h = self._processes.get(pid)
        if not h or not h.process or not h.process.stdout:
            return
        out: IO[bytes] = h.process.stdout
        while h.is_alive:
            try:
                line = out.readline()
                if not line:
                    break
                h.output.append(line.decode("utf-8", errors="replace").rstrip())
            except Exception:
                break
        logger.info("process reader ended: %s", pid)


_manager: ProcessManager | None = None


def get_manager() -> ProcessManager:
    global _manager
    if _manager is None:
        _manager = ProcessManager()
    return _manager


def reset_manager() -> None:
    global _manager
    if _manager:
        _manager.killall()
    _manager = None
