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
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from l1.kernel.params.api import LSP_MANAGER_TIMEOUT
from l1.kernel.params.system import LOG_TRUNC_200

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# 1. LSP Server Configuration
# ══════════════════════════════════════════════════════════════════════

LSP_SERVER_COMMANDS: dict[str, list[str]] = {
    "python":    ["pyright", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "go":        ["gopls"],
    "rust":      ["rust-analyzer"],
    "ruby":      ["ruby-lsp"],
}

LSP_FILE_EXTENSIONS: dict[str, list[str]] = {
    "python":      [".py"],
    "typescript":  [".ts", ".tsx"],
    "javascript":  [".js", ".jsx", ".mjs"],
    "go":          [".go"],
    "rust":        [".rs"],
    "ruby":        [".rb"],
}


# ══════════════════════════════════════════════════════════════════════
# 2. Language Server Process
# ══════════════════════════════════════════════════════════════════════


class LanguageServer:
    """Single LSP server process management."""

    def __init__(self, language: str, project_root: str = ""):
        self.language = language
        self.project_root = project_root or os.getcwd()
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._running = False
        self._seq = 0

    def start(self) -> dict:
        """Start the LSP server process."""
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
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.project_root,
                    text=True,
                )
                self._running = True
                logger.info("LSP %s started (pid=%d)", self.language, self._process.pid)
                return {"success": True, "pid": self._process.pid}
            except Exception as e:
                return {"success": False, "error": str(e)}

    def stop(self) -> dict:
        """Shut down the LSP server process."""
        with self._lock:
            if not self._running or not self._process:
                return {"success": True, "status": "not_running"}
            try:
                self._process.terminate()
                self._process.wait(timeout=LSP_MANAGER_TIMEOUT)
            except Exception:
                self._process.kill()
            self._running = False
            logger.info("LSP %s stopped", self.language)
            return {"success": True}

    def send_request(self, method: str, params: dict | None = None) -> dict:
        """Send JSON-RPC request to LSP server."""
        with self._lock:
            if not self._running or not self._process or not self._process.stdin:
                return {"success": False, "error": "LSP server not running"}

            self._seq += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._seq,
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

            # Read response
            try:
                resp_header = self._process.stdout.readline()  # Content-Length: xxx
                if not resp_header:
                    return {"success": False, "error": "no response header"}
                length = int(resp_header.strip().split(":")[1])
                self._process.stdout.readline()  # Blank line
                resp_body = self._process.stdout.read(length)
                result = json.loads(resp_body)
                return {"success": True, "result": result.get("result", {})}
            except Exception as e:
                return {"success": False, "error": f"read failed: {e}"}

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
    severity: str          # "error" | "warning" | "info"
    code: str = ""
    source: str = ""       # "pyright" | "gopls" | etc.

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
    version: int = 0          # File content version (for incremental updates)

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
        self._send_notification(ls, "textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": language, "text": ""},
        })
        result = ls.send_request("textDocument/semanticTokens/full", {
            "textDocument": {"uri": uri},
        })

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
                    capture_output=True, text=True, timeout=LSP_MANAGER_TIMEOUT,
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
                    diags.append({
                        "line": int(parts[1]) - 1,
                        "column": int(parts[2]) - 1,
                        "severity": parts[3].strip().lower(),
                        "message": parts[4].strip(),
                    })
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
            diags.append({
                "line": e.lineno or 0,
                "column": e.offset or 0,
                "severity": "error",
                "message": f"SyntaxError: {e.msg}",
                "code": "E999",
            })
        return diags

    # ── Hover ──

    def hover(self, file_path: str, line: int, column: int) -> dict:
        """Get hover information."""
        ext = Path(file_path).suffix
        language = self._detect_language(ext)
        if not language:
            return {"success": False, "error": "unsupported language"}

        ls = self._get_or_start_server(language)
        if not ls:
            return {"success": False, "error": f"cannot start LSP for {language}"}

        uri = f"file://{Path(file_path).resolve()}"
        result = ls.send_request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": column},
        })
        return result

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

    def _send_notification(self, ls: LanguageServer, method: str,
                           params: dict) -> None:
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
            pass


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

LSP_ROUTES: list[tuple[str, str, Any, str]] = [
    ("POST", "/api/lsp/diagnostics", handle_lsp_diagnostics, "Get file diagnostics"),
    ("POST", "/api/lsp/hover", handle_lsp_hover, "Get hover info"),
    ("GET", "/api/lsp/servers", handle_lsp_servers, "List LSP server status"),
    ("POST", "/api/lsp/start", handle_lsp_start, "Start LSP server"),
    ("POST", "/api/lsp/stop", handle_lsp_stop, "Stop LSP server"),
    ("POST", "/api/lsp/feedback", handle_lsp_feedback, "Post-edit feedback loop"),
]
