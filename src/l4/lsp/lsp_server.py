"""LSP server process + configuration — extracted from lsp_manager.py.

``LanguageServer`` manages one JSON-RPC-over-stdio LSP process (lifecycle,
handshake, request/response matching, background reader thread); the module
also carries the per-language server-command / file-extension maps and the
coordinate helpers used by LspManager.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from contextlib import suppress
from pathlib import Path

from l1.kernel.params.api import LSP_INIT_TIMEOUT, LSP_RESPONSE_TIMEOUT, LSP_SHUTDOWN_TIMEOUT

logger = logging.getLogger(__name__)

LSP_SERVER_COMMANDS: dict[str, list[str]] = {
    "python": ["pyright", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "go": ["gopls"],
    "rust": ["rust-analyzer"],
    "ruby": ["ruby-lsp"],
}

LSP_FILE_EXTENSIONS: dict[str, list[str]] = {
    "python": [".py"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx", ".mjs"],
    "go": [".go"],
    "rust": [".rs"],
    "ruby": [".rb"],
}

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _to_lsp_position(line: int, column: int) -> dict:
    """Convert 1-based editor coordinates to LSP 0-based position."""
    return {"line": max(line - 1, 0), "character": max(column - 1, 0)}


def _symbol_at_position(path: str, line: int, column: int) -> str:
    """Extract the identifier token at a 1-based (line, column) position.

    Returns an empty string when the position is out of range or does not
    land on an identifier — callers treat that as "no symbol".
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return ""
    if line < 1 or line > len(lines):
        return ""
    if column < 1:
        column = 1
    for m in _IDENTIFIER_RE.finditer(lines[line - 1]):
        start, end = m.start() + 1, m.end()
        if start <= column <= end:
            return m.group()
    return ""


def _rel_to_lsp_root(path: str, analyzer) -> str:
    """Convert a tool path to a path relative to the analyzer root."""
    try:
        return os.path.relpath(os.path.abspath(path), analyzer.root)
    except ValueError:
        return os.path.abspath(path)


class LanguageServer:
    """Single LSP server process management (JSON-RPC over stdio).

    A background reader thread drains the server stdout into a queue so
    server-pushed notifications never block the pipe; requests are matched
    by ``id`` with a response timeout.
    """

    def __init__(self, language: str, project_root: str = ""):
        self.language = language
        self.project_root = project_root or os.getcwd()
        self._process: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._running = False
        self._seq = 0
        self._msg_queue: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None

    def start(self) -> dict:
        """Start the LSP server process and perform the initialize handshake."""
        cmd = LSP_SERVER_COMMANDS.get(self.language)
        if not cmd:
            return {"success": False, "error": f"unsupported language: {self.language}"}

        # Check if command exists
        if not self._find_executable(cmd[0]):
            return {"success": False, "error": f"LSP server not found: {cmd[0]}"}

        with self._lock:
            if self._running:
                return {"success": True, "status": "already_running"}

            try:
                # stderr -> DEVNULL: servers log noisily and an unread pipe
                # would fill up and deadlock the JSON-RPC channel.
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    cwd=self.project_root,
                    text=True,
                )
                self._running = True
                self._reader = threading.Thread(target=self._read_loop, name=f"lsp-reader-{self.language}", daemon=True)
                self._reader.start()
                logger.info("LSP %s started (pid=%d)", self.language, self._process.pid)
            except Exception as e:
                self._running = False
                return {"success": False, "error": str(e)}

            init = self._initialize()
            if not init.get("success"):
                logger.warning("LSP %s initialize failed: %s", self.language, init.get("error"))
                self._teardown()
                return {"success": False, "error": f"initialize failed: {init.get('error', 'unknown')}"}
            return {"success": True, "pid": self._process.pid}

    def stop(self) -> dict:
        """Gracefully shut down the LSP server (shutdown + exit, then kill)."""
        with self._lock:
            if not self._running or not self._process:
                return {"success": True, "status": "not_running"}
            self.send_request("shutdown", {})
            self._notify("exit")
            self._teardown()
            logger.info("LSP %s stopped", self.language)
            return {"success": True}

    def _teardown(self) -> None:
        """Terminate the process and reset reader state."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=LSP_SHUTDOWN_TIMEOUT)
            except Exception:
                with suppress(Exception):
                    self._process.kill()
        self._process = None
        self._running = False
        self._reader = None

    def _initialize(self) -> dict:
        """Send ``initialize`` and ``initialized`` — the LSP handshake."""
        result = self.send_request(
            "initialize",
            {
                "processId": None,
                "rootUri": Path(self.project_root).resolve().as_uri(),
                "capabilities": {},
            },
            timeout=LSP_INIT_TIMEOUT,
        )
        if not result.get("success"):
            return result
        self._notify("initialized")
        return result

    def send_request(self, method: str, params: dict | None = None, timeout: float = LSP_RESPONSE_TIMEOUT) -> dict:
        """Send a JSON-RPC request and wait for the matching id response.

        Server-pushed notifications (window/logMessage etc.) are consumed
        and skipped until a response with the request id arrives; a missing
        response fails after ``timeout`` seconds.
        """
        with self._lock:
            if not self._running or not self._process or not self._process.stdin:
                return {"success": False, "error": "LSP server not running"}

            self._seq += 1
            req_id = self._seq
            request = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }
            content = json.dumps(request)
            header = f"Content-Length: {len(content)}\r\n\r\n"
            try:
                self._process.stdin.write(header + content)
                self._process.stdin.flush()
            except Exception as e:
                return {"success": False, "error": f"write failed: {e}"}

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"success": False, "error": f"response timeout for {method}"}
                try:
                    msg = self._msg_queue.get(timeout=remaining)
                except queue.Empty:
                    return {"success": False, "error": f"response timeout for {method}"}
                if msg.get("id") == req_id:
                    if "error" in msg:
                        return {"success": False, "error": str(msg.get("error"))}
                    return {"success": True, "result": msg.get("result", {})}
                # Notification or a stray response — skip and keep waiting.

    def _notify(self, method: str, params: dict | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return
        request = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        content = json.dumps(request)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        try:
            self._process.stdin.write(header + content)
            self._process.stdin.flush()
        except Exception:
            logger.debug("lsp_server: lsp stdin write failed")

    def _read_loop(self) -> None:
        """Background reader: drain stdout messages into the queue."""
        while self._running and self._process is not None:
            msg = self._read_message()
            if msg is None:
                break
            self._msg_queue.put(msg)

    def _read_message(self) -> dict | None:
        """Read one JSON-RPC message (Content-Length framed) from stdout."""
        process = self._process
        if process is None or process.stdout is None:
            return None
        try:
            length = 0
            header = process.stdout.readline()
            if not header:
                return None
            while header and header.strip():
                line = header.strip()
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1].strip())
                header = process.stdout.readline()
            if length <= 0:
                return None
            body = process.stdout.read(length)
            return json.loads(body) if body else None
        except Exception:
            return None

    def _find_executable(self, name: str) -> bool:
        """Check if executable is in PATH."""
        path = os.environ.get("PATH", "")
        for p in path.split(os.pathsep):
            exe = os.path.join(p, name)
            if os.path.isfile(exe) and os.access(exe, os.X_OK):
                return True
            # Windows
            exe_exe = exe + ".exe"
            if os.path.isfile(exe_exe) and os.access(exe_exe, os.X_OK):
                return True
        return False

    def is_alive(self) -> bool:
        """Return True when the language server process is still running."""
        return self._running and self._process is not None and self._process.poll() is None

    def status(self) -> dict:
        """Return language, running flag, and process liveness."""
        return {
            "language": self.language,
            "running": self._running,
            "alive": self.is_alive(),
        }
