"""Terminal session management — cross-platform subprocess sessions."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import IO

from kernel.params.system import BUFFER_MAX, POLL_INTERVAL_SLOW
from kernel.platform import IS_WINDOWS, create_interactive_shell, set_nonblocking

logger = logging.getLogger(__name__)


@dataclass
class TerminalSession:
    id: str
    pid: int
    process: subprocess.Popen | None = None
    output_buffer: deque[str] = field(default_factory=lambda: deque(maxlen=BUFFER_MAX))
    created_at: float = field(default_factory=time.time)

    def write(self, data: str) -> None:
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(data.encode("utf-8"))
                self.process.stdin.flush()
            except Exception as e:
                logger.warning("shell_session: %s", e)

    def resize(self, cols: int, rows: int) -> None:
        pass

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def kill(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class TerminalManager:
    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()
        self._next_id = 0

    def create(self, cwd: str | None = None) -> dict:
        sid = f"term-{self._next_id}"
        self._next_id += 1
        try:
            proc = create_interactive_shell(cwd=cwd or "")
        except FileNotFoundError:
            return {"success": False, "error": f"shell not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        session = TerminalSession(id=sid, pid=proc.pid, process=proc)
        with self._lock:
            self._sessions[sid] = session
        threading.Thread(target=self._reader, args=(sid,), daemon=True).start()
        logger.info("terminal: %s (pid=%d)", sid, proc.pid)
        return {"success": True, "id": sid}

    def get(self, sid: str) -> TerminalSession | None:
        with self._lock:
            return self._sessions.get(sid)

    def write(self, sid: str, data: str) -> dict:
        s = self.get(sid)
        if not s:
            return {"success": False, "error": "session not found"}
        if not s.is_alive():
            return {"success": False, "error": "process terminated"}
        s.write(data)
        return {"success": True}

    def list(self) -> list[str]:
        with self._lock:
            return list(self._sessions.keys())

    def kill(self, sid: str) -> bool:
        with self._lock:
            s = self._sessions.pop(sid, None)
        if s:
            s.kill()
            return True
        return False

    def killall(self) -> int:
        n = 0
        for sid in list(self.list()):
            if self.kill(sid):
                n += 1
        return n

    def _reader(self, sid: str) -> None:
        s = self.get(sid)
        if not s or not s.process or not s.process.stdout:
            return
        out: IO[bytes] = s.process.stdout
        set_nonblocking(out)
        buf = b""
        while s.is_alive():
            try:
                if IS_WINDOWS:
                    chunk = out.readline()
                    if not chunk:
                        break
                    s.output_buffer.append(chunk.decode("utf-8", errors="replace"))
                else:
                    chunk = out.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        s.output_buffer.append(line.decode("utf-8", errors="replace") + "\n")
            except (BlockingIOError, OSError):
                time.sleep(POLL_INTERVAL_SLOW)
            except Exception:
                break
        if buf:
            s.output_buffer.append(buf.decode("utf-8", errors="replace"))

    def get_output(self, sid: str) -> dict:
        s = self.get(sid)
        if not s:
            return {"success": False, "error": "session not found"}
        return {"success": True, "lines": list(s.output_buffer), "alive": s.is_alive()}


_manager: TerminalManager | None = None


def get_manager() -> TerminalManager:
    global _manager
    if _manager is None:
        _manager = TerminalManager()
    return _manager


def reset_manager() -> None:
    global _manager
    if _manager:
        _manager.killall()
    _manager = None
