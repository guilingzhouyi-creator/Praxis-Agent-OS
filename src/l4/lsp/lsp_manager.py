"""LSP Manager — Multi-language LSP process management + diagnostic cache + feedback loop

Architecture:
  LspManager (services/lsp_manager.py)
  ├── _LanguageServer       — Process lifecycle of a single LSP server
  ├── DiagnosticCache       — File-level diagnostic cache, incremental updates
  ├── FeedbackLoop          — Auto-trigger diagnostics after editing → result callback
  └── API Handlers          — REST endpoints

Supported LSP servers:
  Python: pyright (preferred) / pylsp
  TypeScript/JS: typescript-language-server
  Go: gopls
  Rust: rust-analyzer
  Ruby: ruby-lsp

API:
  POST /api/lsp/diagnostics    — Get file diagnostics
  POST /api/lsp/hover          — Hover information
  GET  /api/lsp/servers        — LSP process status
  POST /api/lsp/start          — Start LSP server
  POST /api/lsp/stop           — Stop LSP server
  POST /api/lsp/feedback       — Post-edit trigger feedback loop
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
from dataclasses import dataclass, field
from pathlib import Path

from l1.kernel.params.api import (
    LSP_INIT_TIMEOUT,
    LSP_MANAGER_TIMEOUT,
    LSP_RESPONSE_TIMEOUT,
    LSP_SHUTDOWN_TIMEOUT,
)
from l1.kernel.params.system import LOG_TRUNC_200

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# 1. LSP Server Configuration
# ══════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════
# 2. Language Server Process
# ══════════════════════════════════════════════════════════════════════


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
            logger.debug("lsp_manager: lsp stdin write failed")

    def _read_loop(self) -> None:
        """Background reader: drain stdout messages into the queue."""
        while self._running and self._process is not None:
            msg = self._read_message()
            if msg is None:
                break
            self._msg_queue.put(msg)

    def _read_message(self) -> dict | None:
        """Read one JSON-RPC message (Content-Length framed) from stdout."""
        try:
            length = 0
            header = self._process.stdout.readline()
            if not header:
                return None
            while header and header.strip():
                line = header.strip()
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1].strip())
                header = self._process.stdout.readline()
            if length <= 0:
                return None
            body = self._process.stdout.read(length)
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
        return self._running and self._process is not None and self._process.poll() is None

    def status(self) -> dict:
        return {
            "language": self.language,
            "running": self._running,
            "alive": self.is_alive(),
        }


# ══════════════════════════════════════════════════════════════════════
# 3. Diagnostic Cache
# ══════════════════════════════════════════════════════════════════════


@dataclass
class DiagnosticEntry:
    """Single diagnostic entry."""

    file: str
    line: int
    column: int
    message: str
    severity: str  # "error" | "warning" | "info"
    code: str = ""
    source: str = ""  # "pyright" | "gopls" | etc.

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "message": self.message[:LOG_TRUNC_200],
            "severity": self.severity,
            "code": self.code,
            "source": self.source,
        }


@dataclass
class FileDiagnostics:
    """Diagnostic snapshot for one file."""

    file: str
    diagnostics: list[DiagnosticEntry] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)
    version: int = 0  # File content version (for incremental updates)

    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)

    def summary(self) -> dict:
        errors = sum(1 for d in self.diagnostics if d.severity == "error")
        warnings = sum(1 for d in self.diagnostics if d.severity == "warning")
        return {
            "file": self.file,
            "errors": errors,
            "warnings": warnings,
            "total": len(self.diagnostics),
        }


class DiagnosticCache:
    """Diagnostic cache — file-level + incremental updates + TTL."""

    def __init__(self, ttl: float = 30.0):
        self._cache: dict[str, FileDiagnostics] = {}
        self._lock = threading.RLock()
        self._ttl = ttl

    def get(self, file_path: str) -> FileDiagnostics | None:
        """Get file diagnostics (if cached and not expired)."""
        with self._lock:
            entry = self._cache.get(file_path)
            if entry is None:
                return None
            if time.time() - entry.checked_at > self._ttl:
                self._cache.pop(file_path, None)
                return None
            return entry

    def set(self, diagnostics: FileDiagnostics) -> None:
        with self._lock:
            self._cache[diagnostics.file] = diagnostics

    def invalidate(self, file_path: str) -> None:
        with self._lock:
            self._cache.pop(file_path, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def stats(self) -> dict:
        with self._lock:
            return {
                "cached_files": len(self._cache),
                "total_diagnostics": sum(len(d.diagnostics) for d in self._cache.values()),
                "files_with_errors": sum(1 for d in self._cache.values() if d.has_errors()),
            }

    def all_summary(self) -> list[dict]:
        with self._lock:
            return [d.summary() for d in self._cache.values()]


# ══════════════════════════════════════════════════════════════════════
# 4. LSP Manager
# ══════════════════════════════════════════════════════════════════════


class LspManager:
    """LSP Manager — multi-language server management + diagnostics + feedback loop."""

    def __init__(self, project_root: str = ""):
        self._project_root = project_root or os.getcwd()
        self._servers: dict[str, LanguageServer] = {}
        self._cache = DiagnosticCache()
        self._lock = threading.RLock()

    # ── Server Lifecycle ──

    def start_server(self, language: str) -> dict:
        with self._lock:
            if language in self._servers:
                ls = self._servers[language]
                if ls.is_alive():
                    return {"success": True, "status": "already_running"}
            ls = LanguageServer(language, self._project_root)
            result = ls.start()
            if result.get("success"):
                self._servers[language] = ls
            return result

    def stop_server(self, language: str) -> dict:
        with self._lock:
            ls = self._servers.pop(language, None)
            if not ls:
                return {"success": True, "status": "not_running"}
            return ls.stop()

    def stop_all(self) -> dict:
        with self._lock:
            results = {}
            for lang, ls in list(self._servers.items()):
                results[lang] = ls.stop()
                self._servers.pop(lang, None)
            return {"success": True, "results": results}

    # ── Diagnostics ──

    def get_diagnostics(self, file_path: str) -> dict:
        """Get file diagnostics (check cache first, fall back to LSP)."""
        # Check cache
        cached = self._cache.get(file_path)
        if cached:
            return {
                "success": True,
                "source": "cache",
                "diagnostics": [d.to_dict() for d in cached.diagnostics],
                "summary": cached.summary(),
            }

        # Detect language
        ext = Path(file_path).suffix
        language = self._detect_language(ext)
        if not language:
            return {"success": False, "error": f"unsupported file type: {ext}"}

        # Ensure server is running
        ls = self._get_or_start_server(language)
        if not ls:
            return {"success": False, "error": f"failed to start LSP server for {language}"}

        # Open file + request diagnostics
        uri = f"file://{Path(file_path).resolve()}"
        self._send_notification(
            ls,
            "textDocument/didOpen",
            {
                "textDocument": {"uri": uri, "languageId": language, "text": ""},
            },
        )
        ls.send_request(
            "textDocument/semanticTokens/full",
            {
                "textDocument": {"uri": uri},
            },
        )

        # Fall back to pyright CLI (more reliable)
        diag_result = self._fallback_diagnostics(file_path)
        if diag_result.get("success"):
            diags = []
            for d in diag_result.get("diagnostics", []):
                entry = DiagnosticEntry(
                    file=file_path,
                    line=d.get("line", 0),
                    column=d.get("column", 0),
                    message=d.get("message", ""),
                    severity=d.get("severity", "warning"),
                    code=d.get("code", ""),
                    source=language,
                )
                diags.append(entry)

            fd = FileDiagnostics(file=file_path, diagnostics=diags)
            self._cache.set(fd)

            return {
                "success": True,
                "source": "lsp",
                "language": language,
                "diagnostics": [d.to_dict() for d in diags],
                "summary": fd.summary(),
            }

        return {"success": True, "diagnostics": [], "source": "none"}

    def _fallback_diagnostics(self, file_path: str) -> dict:
        """Fall back to tool-based diagnostics (pyright/json/lint)."""
        # Python: pyright
        path = Path(file_path)
        if path.suffix == ".py":
            try:
                # Try pyright
                r = subprocess.run(
                    ["pyright", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=LSP_MANAGER_TIMEOUT,
                )
                stdout = r.stdout or r.stderr
                diags = self._parse_pyright_output(stdout, str(path))
                return {"success": True, "diagnostics": diags}
            except Exception:
                # Fall back to ast
                return self._ast_diagnostics(file_path)
        # Other languages fallback to empty
        return {"success": True, "diagnostics": []}

    def _parse_pyright_output(self, output: str, file_path: str) -> list[dict]:
        """Parse pyright text output."""
        diags = []
        for line in output.splitlines():
            # format: "file.py:line:col: severity: message"
            parts = line.split(":", 4)
            if len(parts) >= 5 and file_path in parts[0]:
                try:
                    diags.append(
                        {
                            "line": int(parts[1]) - 1,
                            "column": int(parts[2]) - 1,
                            "severity": parts[3].strip().lower(),
                            "message": parts[4].strip(),
                        }
                    )
                except ValueError:
                    continue
        return diags

    def _ast_diagnostics(self, file_path: str) -> list[dict]:
        """Basic diagnostics using Python ast."""
        import ast

        diags = []
        try:
            with open(file_path, encoding="utf-8") as f:
                ast.parse(f.read())
        except SyntaxError as e:
            diags.append(
                {
                    "line": e.lineno or 0,
                    "column": e.offset or 0,
                    "severity": "error",
                    "message": f"SyntaxError: {e.msg}",
                    "code": "E999",
                }
            )
        return diags

    # ── Hover ──

    def hover(self, file_path: str, line: int, column: int) -> dict:
        """Get hover information at a 1-based (line, column) position."""
        ext = Path(file_path).suffix
        language = self._detect_language(ext)
        if not language:
            return {"success": False, "error": "unsupported language"}

        ls = self._get_or_start_server(language)
        if not ls:
            return {"success": False, "error": f"cannot start LSP for {language}"}

        uri = f"file://{Path(file_path).resolve()}"
        return ls.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": _to_lsp_position(line, column),
            },
        )

    # ── Definition / References ──

    def definition(self, file_path: str, line: int, column: int) -> dict:
        """Resolve the symbol definition at a 1-based position.

        Prefers the running LSP server (``textDocument/definition``); falls
        back to the AST analyzer when no server is available.
        """
        language = self._detect_language(Path(file_path).suffix)
        if language:
            ls = self._get_or_start_server(language)
            if ls is not None:
                result = ls.send_request(
                    "textDocument/definition",
                    {
                        "textDocument": {"uri": f"file://{Path(file_path).resolve()}"},
                        "position": _to_lsp_position(line, column),
                    },
                )
                if result.get("success"):
                    return {"success": True, "source": "lsp", "result": result.get("result", {})}
        return self._ast_definition(file_path, line, column)

    def references(self, file_path: str, line: int, column: int) -> dict:
        """Find references to the symbol at a 1-based position.

        Prefers the running LSP server (``textDocument/references``); falls
        back to the AST analyzer when no server is available.
        """
        language = self._detect_language(Path(file_path).suffix)
        if language:
            ls = self._get_or_start_server(language)
            if ls is not None:
                result = ls.send_request(
                    "textDocument/references",
                    {
                        "textDocument": {"uri": f"file://{Path(file_path).resolve()}"},
                        "position": _to_lsp_position(line, column),
                        "context": {"includeDeclaration": True},
                    },
                )
                if result.get("success"):
                    return {"success": True, "source": "lsp", "result": result.get("result", [])}
        return self._ast_references(file_path, line, column)

    def _ast_definition(self, file_path: str, line: int, column: int) -> dict:
        """AST fallback — token at position resolved via LocalAnalyzer."""
        from l4.lsp.lsp import LocalAnalyzer

        name = _symbol_at_position(file_path, line, column)
        if not name:
            return {"success": True, "source": "ast", "found": False, "result": None}
        analyzer = LocalAnalyzer(self._project_root)
        sym = analyzer.go_to_definition(name, _rel_to_lsp_root(file_path, analyzer))
        if sym is None:
            return {"success": True, "source": "ast", "found": False, "result": None}
        return {
            "success": True,
            "source": "ast",
            "found": True,
            "result": {
                "name": sym.name,
                "kind": sym.kind,
                "file": sym.file,
                "line": sym.line,
                "column": sym.column,
                "parent": sym.parent,
                "docstring": sym.docstring,
            },
        }

    def _ast_references(self, file_path: str, line: int, column: int) -> dict:
        """AST fallback — references to the token at position."""
        from l4.lsp.lsp import LocalAnalyzer

        name = _symbol_at_position(file_path, line, column)
        if not name:
            return {"success": True, "source": "ast", "results": [], "total": 0}
        analyzer = LocalAnalyzer(self._project_root)
        refs = analyzer.find_references(name, _rel_to_lsp_root(file_path, analyzer))
        return {"success": True, "source": "ast", "results": refs, "total": len(refs)}

    # ── Feedback Loop ──

    def feedback_loop(self, file_path: str) -> dict:
        """Post-edit feedback loop: diagnostics → formatted results."""
        diag_result = self.get_diagnostics(file_path)
        if not diag_result.get("success"):
            return diag_result

        summary = diag_result.get("summary", {})
        has_errors = summary.get("errors", 0) > 0

        return {
            "success": True,
            "file": file_path,
            "has_errors": has_errors,
            "diagnostics": diag_result.get("diagnostics", []),
            "summary": summary,
            "suggest_fix": has_errors,
        }

    # ── Status ──

    def servers_status(self) -> dict:
        with self._lock:
            return {
                "success": True,
                "servers": {lang: ls.status() for lang, ls in self._servers.items()},
                "cache": self._cache.stats(),
            }

    # ── Internal ──

    def _detect_language(self, ext: str) -> str | None:
        for lang, exts in LSP_FILE_EXTENSIONS.items():
            if ext in exts:
                return lang
        return None

    def _get_or_start_server(self, language: str) -> LanguageServer | None:
        with self._lock:
            ls = self._servers.get(language)
            if ls and ls.is_alive():
                return ls
            ls = LanguageServer(language, self._project_root)
            result = ls.start()
            if result.get("success"):
                self._servers[language] = ls
                return ls
            return None

    def _send_notification(self, ls: LanguageServer, method: str, params: dict) -> None:
        """Send JSON-RPC notification (no response expected)."""
        if not ls._process or not ls._process.stdin:
            return
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        content = json.dumps(request)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        try:
            ls._process.stdin.write(header + content)
            ls._process.stdin.flush()
        except Exception:
            logger.debug("lsp_manager: lsp stdin write failed")


# ══════════════════════════════════════════════════════════════════════
# 5. Global Singleton
# ══════════════════════════════════════════════════════════════════════

_manager: LspManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> LspManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LspManager()
    return _manager


def reset_manager() -> None:
    global _manager
    if _manager:
        _manager.stop_all()
    _manager = None


# ══════════════════════════════════════════════════════════════════════
# 6. API Handlers
# ══════════════════════════════════════════════════════════════════════


def handle_lsp_diagnostics(body: dict | None = None) -> dict:
    """POST /api/lsp/diagnostics — Get file diagnostics"""
    b = body or {}
    file_path = b.get("file", "")
    if not file_path:
        return {"success": False, "error": "file is required"}
    return get_manager().get_diagnostics(file_path)


def handle_lsp_hover(body: dict | None = None) -> dict:
    """POST /api/lsp/hover — Get hover info"""
    b = body or {}
    file_path = b.get("file", "")
    line = b.get("line", 0)
    column = b.get("column", 0)
    if not file_path:
        return {"success": False, "error": "file is required"}
    return get_manager().hover(file_path, line, column)


def handle_lsp_servers(body: dict | None = None) -> dict:
    """GET /api/lsp/servers — LSP process status"""
    return get_manager().servers_status()


def handle_lsp_start(body: dict | None = None) -> dict:
    """POST /api/lsp/start — Start LSP server"""
    b = body or {}
    language = b.get("language", "")
    if not language:
        return {"success": False, "error": "language is required"}
    return get_manager().start_server(language)


def handle_lsp_stop(body: dict | None = None) -> dict:
    """POST /api/lsp/stop — Stop LSP server"""
    b = body or {}
    language = b.get("language", "")
    if not language:
        return {"success": False, "error": "language is required"}
    return get_manager().stop_server(language)


def handle_lsp_feedback(body: dict | None = None) -> dict:
    """POST /api/lsp/feedback — Post-edit feedback loop"""
    b = body or {}
    file_path = b.get("file", "")
    if not file_path:
        return {"success": False, "error": "file is required"}
    return get_manager().feedback_loop(file_path)


# ── Route Registration ──
# Routes are consolidated in l4/api/api_endpoints.py (ENDPOINT_MANIFEST); no duplicate list maintained here.
