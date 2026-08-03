"""Log service — OS-level logging with rotation, query, export.

Integrates with kernel event bus for cross-service log collection.
Supports:
  - Log levels: DEBUG, INFO, WARN, ERROR
  - File-based persistence with rotation (by size)
  - Time-range querying
  - JSON export
  - Service tagging
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from l1.kernel.params.system import (
    LOG_EXPORT_FILE,
    LOG_EXPORT_LIMIT,
    LOG_MAX_FILE_SIZE,
    LOG_MAX_FILES,
    LOG_MAX_MEMORY_ENTRIES,
    LOG_ROTATE_FILE,
    LOG_ROTATE_GLOB,
    LOG_TRUNC_500,
)
from l3._base import BaseService

logger = logging.getLogger(__name__)

from l1.kernel.paths import get_paths as _gp

_LOG_DIR = Path(_gp().config_dir) / "logs"


@dataclass
class LogEntry:
    level: str
    service: str
    message: str
    timestamp: float = field(default_factory=time.time)
    agent_id: str = ""
    task_id: str = ""

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "service": self.service,
            "message": self.message[:LOG_TRUNC_500],
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
        }


class LogService(BaseService):
    """OS-level log service with rotation and query."""

    def __init__(self, max_entries: int = LOG_MAX_MEMORY_ENTRIES):
        super().__init__("log")
        self._entries: deque[LogEntry] = deque(maxlen=max_entries)
        self._lock = threading.RLock()
        self._log_dir = _LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._current_file = 0
        self._current_size = 0

    def _on_start(self) -> dict:
        # Subscribe to kernel events for cross-service log collection
        try:
            from l1.kernel import SignalType, get_event_bus
            bus = get_event_bus()
            bus.on(SignalType.STATE_CHANGE, lambda s: self.info(
                f"State: {s.data}", s.source, s.data.get("agent_id", "")))
        except Exception as e:
            logger.warning("services/log: %s", e)
        return {"success": True, "log_dir": str(self._log_dir)}

    def _on_stop(self) -> dict:
        self._flush_to_disk()
        return {"success": True}

    # ── Log methods ──

    def debug(self, message: str, service: str = "", agent_id: str = "", task_id: str = "") -> dict:
        return self._log("DEBUG", message, service, agent_id, task_id)

    def info(self, message: str, service: str = "", agent_id: str = "", task_id: str = "") -> dict:
        return self._log("INFO", message, service, agent_id, task_id)

    def warn(self, message: str, service: str = "", agent_id: str = "", task_id: str = "") -> dict:
        return self._log("WARN", message, service, agent_id, task_id)

    def error(self, message: str, service: str = "", agent_id: str = "", task_id: str = "") -> dict:
        return self._log("ERROR", message, service, agent_id, task_id)

    def _log(self, level: str, message: str, service: str, agent_id: str, task_id: str) -> dict:
        entry = LogEntry(level=level, service=service or "system",
                         message=message, agent_id=agent_id, task_id=task_id)
        with self._lock:
            self._entries.append(entry)
            self._current_size += len(message) + 50
        # Auto-flush when memory limit reached
        if self._current_size >= LOG_MAX_FILE_SIZE:
            self._flush_to_disk()
        return {"success": True, "entry_id": len(self._entries), "level": level}

    # ── Query ──

    def query(self, level: str | None = None, service: str | None = None,
              agent_id: str | None = None, task_id: str | None = None,
              since: float | None = None, until: float | None = None,
              limit: int = 100) -> dict:
        with self._lock:
            results = list(self._entries)
        if level:
            results = [e for e in results if e.level == level.upper()]
        if service:
            results = [e for e in results if e.service == service]
        if agent_id:
            results = [e for e in results if e.agent_id == agent_id]
        if task_id:
            results = [e for e in results if e.task_id == task_id]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if until:
            results = [e for e in results if e.timestamp <= until]
        return {"success": True, "entries": [e.to_dict() for e in results[-limit:]],
                "count": min(len(results), limit)}

    def recent(self, limit: int = 50) -> dict:
        with self._lock:
            return {"success": True, "entries": [e.to_dict() for e in list(self._entries)[-limit:]],
                    "count": min(len(self._entries), limit)}

    # ── Export ──

    def export(self, path: str = "", level: str | None = None) -> dict:
        """Export logs to JSON file."""
        r = self.query(level=level, limit=LOG_EXPORT_LIMIT) if level else self.recent(LOG_EXPORT_LIMIT)
        entries = r.get("entries", [])
        out_path = path or str(self._log_dir / LOG_EXPORT_FILE.format(ts=int(time.time())))
        try:
            Path(out_path).write_text(
                json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
            return {"success": True, "path": out_path, "count": len(entries)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Rotation ──

    def _flush_to_disk(self) -> None:
        """Flush memory logs to disk file, rotate if needed."""
        if self._current_size == 0:
            return
        try:
            with self._lock:
                entries = list(self._entries)
                self._current_size = 0
            # Rotate if max files reached
            log_files = sorted(self._log_dir.glob(LOG_ROTATE_GLOB))
            if len(log_files) >= LOG_MAX_FILES:
                log_files[0].unlink()
            fname = LOG_ROTATE_FILE.format(ts=int(time.time()))
            path = self._log_dir / fname
            path.write_text(json.dumps([e.to_dict() for e in entries[-500:]], indent=2),
                           encoding="utf-8")
        except Exception as e:
            logger.warning("log flush failed: %s", e)

    def rotate(self) -> dict:
        """Force log rotation."""
        self._flush_to_disk()
        return {"success": True}

    # ── Stats ──

    # ── Logging bridge: route standard logging.getLogger() into LogService ──

    def install_handler(self) -> None:
        """Install a logging handler that sends all logger.* calls to LogService.

        After calling this, every logger.info/warning/error across all modules
        is captured by LogService in addition to standard stderr output.
        """
        import logging as _logging

        class _LogServiceHandler(_logging.Handler):
            def __init__(self, svc: LogService):
                super().__init__()
                self._svc = svc
                self.setLevel(_logging.DEBUG)

            def emit(self, record: _logging.LogRecord) -> None:
                level = record.levelname
                msg = record.getMessage()[:LOG_TRUNC_500]
                try:
                    self._svc._log(level, msg, record.name,
                                   getattr(record, 'agent_id', ''),
                                   getattr(record, 'task_id', ''))
                except Exception:
                    logger.debug("log: log handler emit failed")

        root = logging.getLogger()
        # Avoid duplicates
        for h in root.handlers:
            if isinstance(h, _LogServiceHandler):
                return
        root.addHandler(_LogServiceHandler(self))

    def stats(self) -> dict:
        with self._lock:
            levels = {}
            services = {}
            agents = set()
            for e in self._entries:
                levels[e.level] = levels.get(e.level, 0) + 1
                services[e.service] = services.get(e.service, 0) + 1
                if e.agent_id:
                    agents.add(e.agent_id)
            return {
                "total": len(self._entries),
                "by_level": levels,
                "by_service": services,
                "agents": len(agents),
                "log_files": len(list(self._log_dir.glob(LOG_ROTATE_GLOB))),
                "log_dir": str(self._log_dir),
            }


_service: LogService | None = None


def get_service() -> LogService:
    global _service
    if _service is None:
        _service = LogService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None


# ── API route handlers ──

def handle_log_query(body: dict | None = None) -> dict:
    """POST /api/logs/query — query logs with filters."""
    svc = get_service()
    return svc.query(
        level=body.get("level") if body else None,
        service=body.get("service") if body else None,
        agent_id=body.get("agent_id") if body else None,
        since=body.get("since") if body else None,
        limit=body.get("limit", 100),
    )


def handle_log_recent(body: dict | None = None) -> dict:
    """GET /api/logs/recent — recent log entries."""
    return get_service().recent(limit=(body or {}).get("limit", 50))


def handle_log_stats(body: dict | None = None) -> dict:
    """GET /api/logs/stats — log statistics."""
    return get_service().stats()


def handle_log_export(body: dict | None = None) -> dict:
    """POST /api/logs/export — export logs to JSON file."""
    return get_service().export(
        path=(body or {}).get("path", ""),
        level=(body or {}).get("level"),
    )


LOG_SERVICE_ROUTES: list[tuple[str, str, Any, str]] = [
    ("POST", "/api/logs/query", handle_log_query, "Query logs with filters"),
    ("GET", "/api/logs/recent", handle_log_recent, "Recent log entries"),
    ("GET", "/api/logs/stats", handle_log_stats, "Log statistics"),
    ("POST", "/api/logs/export", handle_log_export, "Export logs to JSON"),
]
