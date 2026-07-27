"""RecordCenter — unified error/log/reference record center.

Wraps ErrorBus + LogService + ReferenceChannel under a single facade.
  - Unified query across all three stores
  - Unified export with retention policy
  - Bridges aggregate metrics to StatsCenter
  - Scheduled auto-export for persistence

Each subsystem remains independent internally; RecordCenter is a thin
orchestration layer that presents a single API surface.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from l1.kernel.platform import get_config_dir
from l1.kernel.params.system import ERROR_BUS_BUFFER, ERROR_BUS_EXPORT_LIMIT

logger = logging.getLogger(__name__)

_LOG_DIR = Path(get_config_dir()) / "logs"


@dataclass
class RecordQuery:
    sources: list[str] | None = None    # "error" | "log" | "reference"
    level: str = ""
    service: str = ""
    agent_id: str = ""
    error_code: str = ""
    component: str = ""
    since: float = 0.0
    until: float = 0.0
    offset: int = 0
    limit: int = 50
    keyword: str = ""


class RecordCenter:
    """Unified error/log/reference record center.

    Delegates to:
      - ErrorBus for error records (fingerprint-deduped)
      - LogService for general log records (ring buffer + disk)
      - ReferenceChannel for audit/training records (JSONL)
    """

    def __init__(
        self,
        export_dir: str = "",
        auto_export_interval: float = 300.0,
        retention_days: int = 30,
    ):
        self._export_dir = export_dir or str(_LOG_DIR / "exports")
        self._auto_export_interval = auto_export_interval
        self._retention_days = retention_days
        self._lock = threading.RLock()
        self._export_counter = 0
        self._last_auto_export = time.time()

        # Subsystem references (lazy-loaded)
        self._error_bus = None
        self._log_service = None
        self._ref_channel = None
        self._stats_center = None

    # ── Lazy accessors ───────────────────────────────────────────

    def _errors(self):
        if self._error_bus is None:
            from .error_bus import get_bus
            self._error_bus = get_bus()
        return self._error_bus

    def _logs(self):
        if self._log_service is None:
            from .bus.log import get_service
            self._log_service = get_service()
        return self._log_service

    def _refs(self):
        if self._ref_channel is None:
            from .bus.reference_channel import get_rc
            self._ref_channel = get_rc()
        return self._ref_channel

    def _stats(self):
        if self._stats_center is None:
            try:
                from .services.stats_center import get_center
                self._stats_center = get_center()
            except Exception:
                pass
        return self._stats_center

    # ── Unified query ────────────────────────────────────────────

    def query(self, q: RecordQuery) -> dict:
        """Query across error/log/reference stores.

        Returns unified result set with source-tagged entries.
        """
        results = []
        sources = q.sources or ["error", "log"]

        if "error" in sources:
            r = self._errors().query(
                level=q.level or None,
                error_code=q.error_code or None,
                component=q.component or None,
                service=q.service or None,
                agent_id=q.agent_id or None,
                since=q.since or None,
                until=q.until or None,
                offset=0,
                limit=q.limit,
            )
            for e in (r.get("entries") or []):
                e["_source"] = "error"
                results.append(e)

        if "log" in sources:
            r = self._logs().query(
                level=q.level or None,
                service=q.service or None,
                agent_id=q.agent_id or None,
                since=q.since or None,
                until=q.until or None,
            )
            for e in (r or []):
                e["_source"] = "log"
                results.append(e)

        if "reference" in sources:
            try:
                r = self._refs().export(since=q.since, limit=q.limit)
                for e in (r or []):
                    e["_source"] = "reference"
                    results.append(e)
            except Exception:
                pass

        # Keyword filter
        if q.keyword:
            kw = q.keyword.lower()
            results = [
                r for r in results
                if kw in json.dumps(r).lower()
            ]

        # Sort by timestamp descending
        results.sort(key=lambda r: r.get("timestamp", 0), reverse=True)

        total = len(results)
        page = results[q.offset:q.offset + q.limit]

        return {
            "success": True,
            "total": total,
            "offset": q.offset,
            "limit": q.limit,
            "sources": sources,
            "entries": page,
        }

    # ── Unified stats ────────────────────────────────────────────

    def stats(self) -> dict:
        """Aggregated stats from ErrorBus + LogService + ReferenceChannel."""
        error_stats = self._errors().stats()
        log_stats = self._logs().stats()
        try:
            ref_stats = self._refs().stats()
        except Exception:
            ref_stats = {}

        return {
            "success": True,
            "errors": {
                "total": error_stats.get("total", 0),
                "by_level": error_stats.get("by_level", {}),
                "by_component": error_stats.get("by_component", {}),
            },
            "logs": {
                "total": log_stats.get("total", 0),
                "by_level": log_stats.get("by_level", {}),
                "by_service": log_stats.get("by_service", {}),
            },
            "reference": {
                "total_events": ref_stats.get("total_events", 0),
                "buffered": ref_stats.get("buffered", 0),
            },
            "exports": {
                "total_exports": self._export_counter,
                "export_dir": self._export_dir,
                "retention_days": self._retention_days,
                "last_auto_export_ago": round(time.time() - self._last_auto_export, 1),
            },
        }

    # ── Export ───────────────────────────────────────────────────

    def export(self, path: str = "", sources: list[str] | None = None) -> dict:
        """Export records to a JSON file.

        If path is empty, generates an auto-named path in export_dir.
        Returns {success, path, total, sources}.
        """
        sources = sources or ["error", "log"]
        path = path or self._auto_export_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)

        all_records = []
        counts = {}

        if "error" in sources:
            r = self._errors().export(path="")
            if isinstance(r, dict):
                entries = r.get("entries") or r if r.get("success") else []
                for e in entries:
                    if isinstance(e, dict):
                        e["_source"] = "error"
                        all_records.append(e)
                counts["errors"] = len(entries)

        if "log" in sources:
            r = self._logs().export(path="")
            if isinstance(r, list):
                for e in r:
                    if isinstance(e, dict):
                        e["_source"] = "log"
                        all_records.append(e)
                counts["logs"] = len(r)

        if "reference" in sources:
            try:
                r = self._refs().export(limit=ERROR_BUS_EXPORT_LIMIT)
                if isinstance(r, list):
                    for e in r:
                        if isinstance(e, dict):
                            e["_source"] = "reference"
                            all_records.append(e)
                    counts["reference"] = len(r)
            except Exception:
                pass

        export_data = {
            "exported_at": datetime.now(tz=timezone.utc).isoformat(),
            "exported_at_ts": time.time(),
            "sources": sources,
            "counts": counts,
            "total": len(all_records),
            "records": all_records,
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
            self._export_counter += 1
            logger.info("RecordCenter: exported %d records to %s", len(all_records), path)
            return {"success": True, "path": path, "total": len(all_records), "sources": sources}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Auto-export (call periodically) ──────────────────────────

    def auto_export(self, force: bool = False) -> dict | None:
        """Auto-export if interval elapsed.  Returns export result or None."""
        now = time.time()
        if not force and now - self._last_auto_export < self._auto_export_interval:
            return None
        self._last_auto_export = now
        r = self.export()
        self._apply_retention()
        return r

    # ── Bridge to StatsCenter ────────────────────────────────────

    def bridge_stats(self) -> None:
        """Push aggregate error/log metrics to StatsCenter."""
        sc = self._stats()
        if sc is None:
            return
        try:
            es = self._errors().stats()
            sc.ingest_batch([
                _metric("errors.total", float(es.get("total", 0)),
                        tags={"source": "error_bus"}, ts=time.time()),
            ])
            for level, count in es.get("by_level", {}).items():
                sc.ingest(_metric(f"errors.level.{level.lower()}", float(count),
                                  tags={"source": "error_bus"}, ts=time.time()))
            ls = self._logs().stats()
            sc.ingest(_metric("logs.total", float(ls.get("total", 0)),
                              tags={"source": "log_service"}, ts=time.time()))
        except Exception as e:
            logger.warning("RecordCenter bridge stats: %s", e)

    # ── Internal ─────────────────────────────────────────────────

    def _auto_export_path(self) -> str:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        return os.path.join(self._export_dir, f"records_{ts}.json")

    def _apply_retention(self) -> int:
        """Remove export files older than retention_days.  Returns count removed."""
        if self._retention_days <= 0:
            return 0
        cutoff = time.time() - self._retention_days * 86400
        removed = 0
        try:
            for fname in os.listdir(self._export_dir):
                fpath = os.path.join(self._export_dir, fname)
                if not fname.startswith("records_") or not fname.endswith(".json"):
                    continue
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
        except FileNotFoundError:
            pass
        if removed:
            logger.info("RecordCenter: retention removed %d old exports", removed)
        return removed


def _metric(name: str, value: float, tags: dict, ts: float):
    """Helper to create a MetricPoint without importing StatsCenter types."""
    from .services.stats_center import MetricPoint
    return MetricPoint(name=name, value=value, tags=tags, timestamp=ts, metric_type="gauge")


# ── Singleton ────────────────────────────────────────────────

_center: RecordCenter | None = None
_center_lock = threading.Lock()


def get_record_center() -> RecordCenter:
    global _center
    if _center is None:
        with _center_lock:
            if _center is None:
                _center = RecordCenter()
    return _center


def reset_record_center() -> None:
    global _center
    _center = None
