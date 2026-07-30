"""ErrorBus — Unified Error Log Bus

Merges ~190 exception capture points across the project, exposing a REST API for frontend consumption.

Three-tier architecture:
  1. ErrorLogEntry — Structured error record with fingerprint-based deduplication (richer than LogEntry)
  2. ErrorBus — Merging engine: dedup + write to LogService + push to EventBus + SSE
  3. API Handlers — Expose REST endpoints via ApiGateway

Usage — One-line replacement for all except points:
    try:
        ...
    except Exception as e:
        capture("memory compact failed", exc=e, component="services")
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from l3._base import BaseService
from l1.kernel.params.system import ERROR_BUS_BUFFER, ERROR_BUS_DEDUP_WINDOW, ERROR_BUS_EXPORT_LIMIT, ERROR_EXPORT_FILE, HASH_TRUNC_LONG, LOG_ROTATE_GLOB, LOG_TRUNC_100, LOG_TRUNC_1000, LOG_TRUNC_200, LOG_TRUNC_500
from l1.kernel.paths import get_paths as _gp
from l1.kernel.platform import get_config_dir

logger = logging.getLogger(__name__)

_LOG_DIR = Path(_gp().config_dir) / "logs"


# ══════════════════════════════════════════════════════════════════════
# 1. Core data model
# ══════════════════════════════════════════════════════════════════════


@dataclass
class ErrorLogEntry:
    """Structured error log entry — richer than the generic LogEntry.

    Adds to the LogEntry from services/log.py:
      - error_code: Unified error code (linked with kernel/errors.py)
      - component:  Component layer (kernel / services / tools / api / cli)
      - source:     Source location (file:line)
      - stack_trace:Exception stack trace
      - context:    Additional key-value pairs
      - fingerprint:Deduplication fingerprint
      - count:      Cumulative occurrence count for the same fingerprint
    """

    # ── Basic fields ──
    level: str  # "ERROR" | "CRITICAL" | "WARN"
    service: str  # e.g. "kernel/allocator", "services/agent_loop"
    message: str
    timestamp: float = field(default_factory=time.time)
    agent_id: str = ""
    task_id: str = ""

    # ── Error-specific fields ──
    error_code: str = "E_INTERNAL"
    component: str = "kernel"  # kernel / services / tools / api / cli
    source: str = ""  # e.g. "kernel/allocator.py:77"
    stack_trace: str = ""
    context: dict = field(default_factory=dict)

    # ── Deduplication fields ──
    fingerprint: str = ""
    count: int = 1

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = _compute_fingerprint(
                self.level, self.error_code, self.source, self.message,
            )

    def to_dict(self) -> dict:
        return {
            "id": self.fingerprint[:12],
            "level": self.level,
            "error_code": self.error_code,
            "component": self.component,
            "service": self.service,
            "message": self.message[:LOG_TRUNC_500],
            "source": self.source,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(
                self.timestamp, tz=timezone.utc
            ).isoformat(),
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "stack_trace": (self.stack_trace or "")[:1000],
            "context": self.context,
            "count": self.count,
        }


def _compute_fingerprint(
    level: str, error_code: str, source: str, message: str,
) -> str:
    """Compute deduplication fingerprint — sha256(level + error_code + source + message[:LOG_TRUNC_100]) → hex[:16]"""
    raw = f"{level}|{error_code}|{source}|{message[:LOG_TRUNC_100]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:HASH_TRUNC_LONG]


def _caller_source(depth: int = 2) -> str:
    """Auto-detect caller location — returns 'file.py:line'"""
    import inspect
    try:
        frame = inspect.currentframe()
        # Skip up depth levels: capture() → error() → caller()
        for _ in range(depth):
            if frame and frame.f_back:
                frame = frame.f_back
        if frame:
            return f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}"
    except Exception:
        logger.debug("error_bus: caller resolve failed")
    return "unknown"


def _format_exc(exc: Exception | None) -> str:
    """Format exception stack trace, truncated to first 1000 characters"""
    if not exc:
        return ""
    lines = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    return lines[:LOG_TRUNC_1000]


# ══════════════════════════════════════════════════════════════════════
# 2. ErrorBus — Merging engine
# ══════════════════════════════════════════════════════════════════════


class ErrorBus(BaseService):
    """Unified error log bus — ingestion, deduplication, query, SSE.

    Responsibilities:
      1. ingest() receives errors from all sources → dedup → write to LogService + EventBus
      2. Maintains a ring buffer for fast queries
      3. Exposes REST API query/statistics interfaces
    """

    def __init__(self, max_entries: int = ERROR_BUS_BUFFER):
        super().__init__("error_bus")
        self._max_entries = max_entries
        self._buffer: deque[ErrorLogEntry] = deque(maxlen=max_entries)
        self._fingerprint_index: dict[str, ErrorLogEntry] = {}
        self._lock = threading.RLock()

        # SSE clients
        self._sse_clients: list[queue.Queue] = []
        self._sse_lock = threading.RLock()

        # Stats cache
        self._stats_cache: dict = {}
        self._stats_ts: float = 0.0

    # ── Lifecycle ──

    def _on_start(self) -> dict:
        """Subscribe to EventBus error events on startup"""
        try:
            from l1.kernel import get_event_bus
            bus = get_event_bus()
            bus.on_event("error_log", self._on_error_event)
        except Exception as e:
            logger.warning("error_bus: event bus subscribe failed: %s", e)
        logger.info("error_bus started (max_entries=%d)", self._max_entries)
        return {"success": True, "max_entries": self._max_entries}

    def _on_stop(self) -> dict:
        # Close all SSE connections
        with self._sse_lock:
            for q in self._sse_clients:
                q.put(None)  # Sentinel to notify disconnection
            self._sse_clients.clear()
        return {"success": True}

    # ── Ingestion entry points ──

    def error(
        self,
        message: str,
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Log an ERROR level error."""
        return self._ingest(level="ERROR", message=message, error_code=error_code,
                            component=component, service=service or component,
                            source=source, stack_trace=stack_trace,
                            agent_id=agent_id, task_id=task_id, context=context or {})

    def critical(
        self,
        message: str,
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Log a CRITICAL level error."""
        return self._ingest(level="CRITICAL", message=message, error_code=error_code,
                            component=component, service=service or component,
                            source=source, stack_trace=stack_trace,
                            agent_id=agent_id, task_id=task_id, context=context or {})

    def warn(
        self,
        message: str,
        error_code: str = "",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Log a WARN level warning."""
        return self._ingest(level="WARN", message=message,
                            error_code=error_code or "E_WARN",
                            component=component, service=service or component,
                            source=source, agent_id=agent_id,
                            task_id=task_id, context=context or {})

    def exception(
        self,
        exc: Exception,
        message: str = "",
        error_code: str = "E_INTERNAL",
        component: str = "kernel",
        service: str = "",
        source: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        """Extract information from an Exception object and log it.

        Automatically extracts stack_trace; if source is empty, auto-infers the call location.
        """
        stack_trace = _format_exc(exc)
        _source = source or _caller_source(depth=3)
        _message = message or str(exc)[:LOG_TRUNC_200]
        return self.error(message=_message, error_code=error_code,
                          component=component, service=service,
                          source=_source, stack_trace=stack_trace,
                          agent_id=agent_id, task_id=task_id, context=context or {})

    # ── Internal ingestion logic ──

    def _ingest(
        self,
        level: str,
        message: str,
        error_code: str,
        component: str,
        service: str,
        source: str,
        stack_trace: str = "",
        agent_id: str = "",
        task_id: str = "",
        context: dict | None = None,
    ) -> dict:
        entry = ErrorLogEntry(
            level=level,
            service=service,
            message=message,
            timestamp=time.time(),
            agent_id=agent_id,
            task_id=task_id,
            error_code=error_code,
            component=component,
            source=source,
            stack_trace=stack_trace,
            context=context or {},
        )

        with self._lock:
            # Deduplication
            existing = self._fingerprint_index.get(entry.fingerprint)
            if existing:
                existing.count += 1
                existing.timestamp = entry.timestamp  # Update timestamp
                result_entry = existing
            else:
                # deque(maxlen=N) auto-evicts the leftmost element on append when full;
                # must capture the entry about to be evicted before appending, and
                # after appending clean up its fingerprint index to keep
                # the index in sync with the actual buffer contents.
                evicted: ErrorLogEntry | None = None
                if len(self._buffer) >= self._max_entries:
                    evicted = self._buffer[0]
                self._buffer.append(entry)
                self._fingerprint_index[entry.fingerprint] = entry
                result_entry = entry
                if evicted is not None and evicted.fingerprint in self._fingerprint_index:
                    del self._fingerprint_index[evicted.fingerprint]

        # ── Push to LogService ──
        try:
            from l3.bus.log import get_service as get_log_service
            log_svc = get_log_service()
            log_svc._log(
                level=level,
                message=f"[{error_code}] {message[:LOG_TRUNC_200]}",
                service=service,
                agent_id=agent_id,
                task_id=task_id,
            )
        except Exception as e:
            logger.warning("error_bus: log push failed: %s", e)

        # ── Push to EventBus ──
        try:
            from l1.kernel import emit_event
            emit_event("error_log", result_entry.to_dict(), source=component)
        except Exception as e:
            logger.warning("error_bus: event push failed: %s", e)

        # Invalidate stats cache
        self._stats_ts = 0.0

        return {"success": True, "entry": result_entry.to_dict()}

    # ── EventBus callback ──

    def _on_error_event(self, signal: Any) -> None:
        """Receive error events from EventBus → push to all SSE clients"""
        data = signal.data if hasattr(signal, "data") else signal
        with self._sse_lock:
            dead: list[queue.Queue] = []
            for q in self._sse_clients:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._sse_clients.remove(q)

    # ── SSE ──

    def subscribe_sse(self) -> queue.Queue:
        """Create a subscription queue for an SSE client."""
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._sse_lock:
            self._sse_clients.append(q)
        return q

    def unsubscribe_sse(self, q: queue.Queue) -> None:
        """Remove an SSE client queue."""
        with self._sse_lock:
            if q in self._sse_clients:
                self._sse_clients.remove(q)

    # ── Query ──

    def query(
        self,
        level: str | None = None,
        error_code: str | None = None,
        component: str | None = None,
        service: str | None = None,
        agent_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Query error logs by criteria (paginated, descending by time)."""
        with self._lock:
            results = list(self._buffer)

        # Filter
        if level:
            results = [e for e in results if e.level == level.upper()]
        if error_code:
            results = [e for e in results if e.error_code == error_code]
        if component:
            results = [e for e in results if e.component == component]
        if service:
            results = [e for e in results if e.service == service]
        if agent_id:
            results = [e for e in results if e.agent_id == agent_id]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if until:
            results = [e for e in results if e.timestamp <= until]

        # Descending by time
        results.sort(key=lambda e: e.timestamp, reverse=True)

        total = len(results)
        page = results[offset:offset + limit]

        return {
            "success": True,
            "total": total,
            "offset": offset,
            "limit": limit,
            "entries": [e.to_dict() for e in page],
        }

    def get_by_fingerprint(self, fingerprint: str) -> dict | None:
        """Get a single error detail by fingerprint."""
        with self._lock:
            entry = self._fingerprint_index.get(fingerprint)
            if entry:
                # Collect all timestamps where this fingerprint appeared
                return entry.to_dict()
            return None

    def stats(self) -> dict:
        """Error statistics: aggregated by level / error_code / component, with cache."""
        now = time.time()
        if now - self._stats_ts < 2.0 and self._stats_cache:
            return self._stats_cache

        with self._lock:
            entries = list(self._buffer)

        by_level: dict[str, int] = {}
        by_error_code: dict[str, int] = {}
        by_component: dict[str, int] = {}
        top_sources: dict[str, int] = {}
        agents: set[str] = set()

        for e in entries:
            by_level[e.level] = by_level.get(e.level, 0) + 1
            by_error_code[e.error_code] = by_error_code.get(e.error_code, 0) + 1
            by_component[e.component] = by_component.get(e.component, 0) + 1
            src = f"{e.source}" if e.source else "unknown"
            top_sources[src] = top_sources.get(src, 0) + 1
            if e.agent_id:
                agents.add(e.agent_id)

        # Sort top_sources, take top 10
        sorted_sources = sorted(top_sources.items(), key=lambda x: -x[1])[:10]

        result = {
            "success": True,
            "total": len(entries),
            "by_level": by_level,
            "by_error_code": by_error_code,
            "by_component": by_component,
            "top_sources": [
                {"source": s, "count": c} for s, c in sorted_sources
            ],
            "agents": len(agents),
        }

        # Disk file count
        try:
            log_dir = _LOG_DIR
            if log_dir.exists():
                result["disk_files"] = len(list(log_dir.glob(LOG_ROTATE_GLOB)))
                result["log_dir"] = str(log_dir)
        except Exception:
            logger.debug("error_bus: stats disk check failed")

        self._stats_cache = result
        self._stats_ts = now
        return result

    def trend(self, window_minutes: int = 60, bucket_minutes: int = 10) -> dict:
        """Error trend: bucket statistics by time window.

        Args:
            window_minutes: Lookback window (default 60 minutes)
            bucket_minutes: Bucket size (default 10 minutes)

        Returns:
            {"buckets": [{"bucket": "ISO8601", "count": int}, ...]}
        """
        now = time.time()
        since = now - window_minutes * 60

        with self._lock:
            entries = [e for e in self._buffer if e.timestamp >= since]

        # Bucketing
        bucket_size = bucket_minutes * 60
        buckets: dict[int, int] = defaultdict(int)

        for e in entries:
            bucket_ts = int(e.timestamp // bucket_size) * bucket_size
            buckets[bucket_ts] += 1

        result = [
            {
                "bucket": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "count": count,
            }
            for ts, count in sorted(buckets.items())
        ]

        return {"success": True, "window_minutes": window_minutes, "buckets": result}

    def recent(self, limit: int = 50) -> dict:
        """Get the most recent N errors (fast)."""
        with self._lock:
            entries = list(self._buffer)[-limit:]
        entries.reverse()
        return {
            "success": True,
            "entries": [e.to_dict() for e in entries],
            "count": len(entries),
        }

    def clear(self, before: float | None = None) -> dict:
        """Clear the error buffer (optionally before a given timestamp)."""
        with self._lock:
            if before is None:
                removed = len(self._buffer)
                self._buffer.clear()
                self._fingerprint_index.clear()
            else:
                remaining = [e for e in self._buffer if e.timestamp >= before]
                removed = len(self._buffer) - len(remaining)
                self._buffer = deque(remaining, maxlen=self._max_entries)
                self._fingerprint_index = {e.fingerprint: e for e in remaining}
        self._stats_ts = 0.0
        return {"success": True, "removed": removed}

    def export(self, path: str = "") -> dict:
        """Export error logs to a JSON file."""
        with self._lock:
            entries = [e.to_dict() for e in self._buffer]

        out_path = path or str(_LOG_DIR / ERROR_EXPORT_FILE.format(ts=int(time.time())))
        try:
            Path(out_path).write_text(
                json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return {"success": True, "path": out_path, "count": len(entries)}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════
# 3. Global quick-access entry points
# ══════════════════════════════════════════════════════════════════════

_bus: ErrorBus | None = None
_bus_lock = threading.Lock()


def get_bus() -> ErrorBus:
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = ErrorBus()
                _bus.start()  # triggers _on_start → EventBus subscription
    return _bus


def reset_bus() -> None:
    global _bus
    if _bus:
        _bus.stop()
    _bus = None


@contextmanager
def error_boundary(
    message: str = "",
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    agent_id: str = "",
    task_id: str = "",
    re_raise: bool = False,
) -> Generator:
    """Context manager — capture all exceptions within a block into ErrorBus.

    Usage:
        with error_boundary("agent loop failed", component="services"):
            ...

    By default exceptions are consumed (not re-raised).
    Set re_raise=True to propagate after capture.
    """
    try:
        yield
    except Exception as e:
        capture(message or str(e), error_code=error_code, component=component,
                exc=e, agent_id=agent_id, task_id=task_id)
        if re_raise:
            raise


def capture(
    message: str,
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    exc: Exception | None = None,
    agent_id: str = "",
    task_id: str = "",
    context: dict | None = None,
) -> dict:
    """Simplest error capture entry point — one-line replacement for all except blocks.

    Usage:
        try:
            ...
        except Exception as e:
            capture("memory compact failed", exc=e, component="services")

    Auto-extracts:
      - source: caller's file:line from the call stack
      - stack_trace: traceback from exc
      - service: reuses the component value

    Returns:
        {"success": True, "entry": {...}}
    """
    bus = get_bus()
    source = _caller_source(depth=2)
    stack_trace = _format_exc(exc) if exc else ""
    return bus.error(
        message=message,
        error_code=error_code,
        component=component,
        service=component,
        source=source,
        stack_trace=stack_trace,
        agent_id=agent_id,
        task_id=task_id,
        context=context or {},
    )


def capture_exception(
    exc: Exception,
    message: str = "",
    error_code: str = "E_INTERNAL",
    component: str = "kernel",
    agent_id: str = "",
    task_id: str = "",
    context: dict | None = None,
) -> dict:
    """Capture directly from an Exception object.

    Usage:
        except Exception as e:
            capture_exception(e, "XXX failed", component="services")
    """
    bus = get_bus()
    return bus.exception(
        exc=exc,
        message=message,
        error_code=error_code,
        component=component,
        agent_id=agent_id,
        task_id=task_id,
        context=context or {},
    )


# ══════════════════════════════════════════════════════════════════════
# 4. API Handlers — Mounted to ApiGateway
# ══════════════════════════════════════════════════════════════════════

# These handlers are mixed into the ApiHandlers class in api_handlers.py


# ── Re-export API handlers from sub-module ──

from .api import (  # noqa: F401
    handle_log_errors, handle_log_errors_detail,
    handle_log_errors_stats, handle_log_errors_trend,
    handle_log_errors_clear, handle_log_errors_export,
)
