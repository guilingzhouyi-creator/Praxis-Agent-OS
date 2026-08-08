"""LSP diagnostic cache — extracted from lsp_manager.py.

``DiagnosticEntry`` / ``FileDiagnostics`` are the per-diagnostic and per-file
snapshot models; ``DiagnosticCache`` provides file-level caching with TTL and
incremental updates. ``LspManager`` (in lsp_manager.py) consumes this cache.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from l1.kernel.discovery import get_service_limit
from l1.kernel.params.api import LSP_CACHE_TTL
from l1.kernel.params.system import LOG_TRUNC_200

logger = logging.getLogger(__name__)


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
        """Convert the diagnostic entry to a serializable dict."""
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
        """Return True when any diagnostic is an error."""
        return any(d.severity == "error" for d in self.diagnostics)

    def summary(self) -> dict:
        """Return error/warning counts for the file snapshot."""
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

    def __init__(self, ttl: float | None = None):
        # Declarative override via config/discovery/service_limits.yaml,
        # params constant as fallback (AGENTS.md three-layer config).
        if ttl is None:
            ttl = get_service_limit("lsp_cache_ttl", LSP_CACHE_TTL)
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
        """Store a diagnostics snapshot for its file."""
        with self._lock:
            self._cache[diagnostics.file] = diagnostics

    def invalidate(self, file_path: str) -> None:
        """Drop the cached diagnostics for the given file."""
        with self._lock:
            self._cache.pop(file_path, None)

    def clear(self) -> None:
        """Clear the entire diagnostic cache."""
        with self._lock:
            self._cache.clear()

    def stats(self) -> dict:
        """Return cache size and diagnostic counts."""
        with self._lock:
            return {
                "cached_files": len(self._cache),
                "total_diagnostics": sum(len(d.diagnostics) for d in self._cache.values()),
                "files_with_errors": sum(1 for d in self._cache.values() if d.has_errors()),
            }

    def all_summary(self) -> list[dict]:
        """Return summaries for every cached file."""
        with self._lock:
            return [d.summary() for d in self._cache.values()]
