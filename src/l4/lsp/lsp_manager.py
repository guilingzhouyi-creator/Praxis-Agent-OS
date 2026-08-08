"""LSP Manager — Multi-language LSP process management + diagnostic cache + feedback loop

Architecture:
  LspManager (services/lsp_manager.py)
  ├── LanguageServer         — Process lifecycle of a single LSP server (lsp_server.py)
  ├── DiagnosticCache        — File-level diagnostic cache, incremental updates (lsp_diagnostics.py)
  ├── FeedbackLoop           — Auto-trigger diagnostics after editing → result callback
  └── API Handlers           — REST endpoints

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
from pathlib import Path

from l1.kernel.params.api import LSP_MANAGER_TIMEOUT

from .lsp_diagnostics import (  # noqa: F401 — re-export
    DiagnosticCache,
    DiagnosticEntry,
    FileDiagnostics,
)
from .lsp_server import (  # noqa: F401 — re-export
    LSP_FILE_EXTENSIONS,
    LSP_SERVER_COMMANDS,
    LanguageServer,
    _rel_to_lsp_root,
    _symbol_at_position,
    _to_lsp_position,
)

logger = logging.getLogger(__name__)


class LspManager:
    """LSP Manager — multi-language server management + diagnostics + feedback loop."""

    def __init__(self, project_root: str = ""):
        self._project_root = project_root or os.getcwd()
        self._servers: dict[str, LanguageServer] = {}
        self._cache = DiagnosticCache()
        self._lock = threading.RLock()

    # ── Server Lifecycle ──

    def start_server(self, language: str) -> dict:
        """Start the language server for the language, reusing a live one."""
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
        """Stop and remove the language server for the language."""
        with self._lock:
            ls = self._servers.pop(language, None)
            if not ls:
                return {"success": True, "status": "not_running"}
            return ls.stop()

    def stop_all(self) -> dict:
        """Stop every running language server."""
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
                return {"success": True, "diagnostics": self._ast_diagnostics(file_path), "source": "ast"}
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
        """Return status for all servers plus diagnostic cache stats."""
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
    """Return the process-wide LspManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LspManager()
    return _manager


def reset_manager() -> None:
    """Stop all servers and clear the LspManager singleton."""
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
