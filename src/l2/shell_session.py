"""Terminal session management — cross-platform subprocess sessions."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import IO

from l1.kernel.params.api import SHELL_SESSION_TIMEOUT
from l1.kernel.params.system import BUFFER_MAX, POLL_INTERVAL_SLOW
from l1.kernel.platform import IS_WINDOWS, create_interactive_shell, set_nonblocking

logger = logging.getLogger(__name__)


@dataclass
class TerminalSession:
    """A single interactive shell session — wraps a subprocess with output buffer."""

    id: str
    pid: int
    process: subprocess.Popen | None = None
    output_buffer: deque[str] = field(default_factory=lambda: deque(maxlen=BUFFER_MAX))
    created_at: float = field(default_factory=time.time)

    def write(self, data: str) -> None:
        """Write data to the session's stdin."""
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(data.encode("utf-8"))
                self.process.stdin.flush()
            except Exception as e:
                logger.warning("shell_session: %s", e)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal. No-op — PTY resize not yet implemented."""

    def is_alive(self) -> bool:
        """Check if the underlying subprocess is still running."""
        return self.process is not None and self.process.poll() is None

    def kill(self) -> None:
        """Terminate the session. Sends SIGTERM, escalates to SIGKILL on timeout.

        Closes stdout/stderr/stdin pipes afterward so the reader thread's
        blocking ``readline()`` (Windows) returns immediately.
        """
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=SHELL_SESSION_TIMEOUT)
            except subprocess.TimeoutExpired:
                self.process.kill()
            # Close pipes to unblock reader thread on all platforms
            for fd_name in ("stdout", "stderr", "stdin"):
                fd = getattr(self.process, fd_name, None)
                if fd:
                    try:
                        fd.close()
                    except OSError:
                        logger.debug("shell_session: pipe close failed (best-effort cleanup)")


class TerminalManager:
    """Manages multiple shell sessions — create, write, kill, list.

    Each session runs in a background daemon thread (``_reader``) that
    captures stdout into a bounded ``deque`` buffer.
    """
    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()
        self._next_id = 0

    def create(self, cwd: str | None = None) -> dict:
        """Create a new interactive shell session. Returns {"success": True, "id": sid}."""
        sid = f"term-{self._next_id}"
        self._next_id += 1
        try:
            proc = create_interactive_shell(cwd=cwd or "")
        except FileNotFoundError:
            return {"success": False, "error": "shell not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        session = TerminalSession(id=sid, pid=proc.pid, process=proc)
        with self._lock:
            self._sessions[sid] = session
        threading.Thread(target=self._reader, args=(sid,), daemon=True).start()
        logger.info("terminal: %s (pid=%d)", sid, proc.pid)
        return {"success": True, "id": sid}

    def get(self, sid: str) -> TerminalSession | None:
        """Get a session by ID. Returns None if not found."""
        with self._lock:
            return self._sessions.get(sid)

    def write(self, sid: str, data: str) -> dict:
        """Write data to a session's stdin."""
        s = self.get(sid)
        if not s:
            return {"success": False, "error": "session not found"}
        if not s.is_alive():
            return {"success": False, "error": "process terminated"}
        s.write(data)
        return {"success": True}

    def list(self) -> list[str]:
        """List all active session IDs."""
        with self._lock:
            return list(self._sessions.keys())

    def kill(self, sid: str) -> bool:
        """Kill a session by ID."""
        with self._lock:
            s = self._sessions.pop(sid, None)
        if s:
            s.kill()
            return True
        return False

    def killall(self) -> int:
        """Kill all active sessions. Returns the number killed."""
        n = 0
        for sid in list(self.list()):
            if self.kill(sid):
                n += 1
        return n

    def _reader(self, sid: str) -> None:
        """Background thread: reads session stdout into a bounded deque buffer.

        Cross-platform:
          Windows — blocking ``readline()`` (no non-blocking pipe support)
          Unix    — non-blocking ``read(4096)`` with ``bytearray`` line assembly

        Exits when the subprocess terminates, pipe is closed, or no data
        arrives within 30s (guards against stuck child processes).
        """
        s = self.get(sid)
        if not s or not s.process or not s.process.stdout:
            return
        out: IO[bytes] = s.process.stdout
        set_nonblocking(out)
        buf = bytearray()
        _last_data = time.time()
        while s.is_alive():
            try:
                if IS_WINDOWS:
                    chunk = out.readline()
                    if not chunk:
                        break
                    s.output_buffer.append(chunk.decode("utf-8", errors="replace"))
                    _last_data = time.time()
                else:
                    chunk = out.read(4096)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    _last_data = time.time()
                    while b"\n" in buf:
                        idx = buf.index(b"\n")
                        line = buf[:idx].decode("utf-8", errors="replace") + "\n"
                        del buf[:idx + 1]
                        s.output_buffer.append(line)
            except (BlockingIOError, OSError):
                # No data available yet — check for idle timeout (30s)
                if time.time() - _last_data > 30.0:
                    break
                time.sleep(POLL_INTERVAL_SLOW)
            except Exception:
                break
        if buf:
            s.output_buffer.append(buf.decode("utf-8", errors="replace"))

    def get_output(self, sid: str) -> dict:
        """Get buffered output for a session. Returns {"success", "lines", "alive"}."""
        s = self.get(sid)
        if not s:
            return {"success": False, "error": "session not found"}
        return {"success": True, "lines": list(s.output_buffer), "alive": s.is_alive()}


_manager: TerminalManager | None = None


def get_manager() -> TerminalManager:
    """Get the singleton TerminalManager instance."""
    global _manager
    if _manager is None:
        _manager = TerminalManager()
    return _manager


def reset_manager() -> None:
    """Reset the singleton — kills all sessions and clears the instance."""
    global _manager
    if _manager:
        _manager.killall()
    _manager = None
