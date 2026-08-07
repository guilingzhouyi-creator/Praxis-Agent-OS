"""ReportService — structured report generation, L3A push, and SSE broadcast.

After cross-Cell aggregation produces an AggregatedReport, ReportService:
  1. Generates a structured report (consistency + divergences + supplements)
  2. Pushes the report to L3A via CentralController
  3. Emits SSE events for frontend real-time updates
  4. Exposes REST API endpoints for querying reports
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from l1.kernel.params.system import HASH_TRUNC_MEDIUM, LOG_TRUNC_200

logger = logging.getLogger(__name__)


class ReportService:
    """Generate and distribute structured discussion reports."""

    def __init__(self):
        self._reports: dict[str, dict] = {}
        self._lock = threading.RLock()

    def generate(self, session_id: str, aggregation: dict) -> dict:
        """Produce a structured report from aggregation results.

        The report includes:
          - Overview: cells, answers, status
          - Consistency: agreed points
          - Divergences: disputed points with cell positions
          - Supplements: new issues raised
          - Coverage: which issues each cell answered
        """
        report_id = f"rpt-{uuid.uuid4().hex[:HASH_TRUNC_MEDIUM]}"

        status = aggregation.get("status", "unknown")
        consistency = aggregation.get("consistency", [])
        divergences = aggregation.get("divergences", [])
        supplements = aggregation.get("supplement_issues", [])

        report = {
            "id": report_id,
            "session_id": session_id,
            "status": status,
            "created_at": time.time(),
            # ── Overview ──
            "overview": {
                "total_cells": aggregation.get("total_cells", 0),
                "participating_cells": aggregation.get("participating_cells", []),
                "total_answers": sum(aggregation.get("answers_by_cell", {}).values()),
                "status": status,
            },
            # ── Consistency (agreed points) ──
            "consistency": [
                {"fingerprint": c.get("fingerprint", ""),
                 "cells": c.get("cells", []),
                 "consensus": True}
                for c in consistency
            ],
            # ── Divergences (disputed points) ──
            "divergences": [
                {"topic": d.get("topic", "?"),
                 "cells": d.get("cells", []),
                 "severity": d.get("severity", "medium"),
                 "positions": d.get("positions", []),
                 "resolution": None}
                for d in divergences
            ],
            # ── Supplement issues raised ──
            "supplements": [
                {"title": s.get("title", ""),
                 "source_cell": s.get("source_cell", ""),
                 "description": s.get("description", "")[:LOG_TRUNC_200]}
                for s in supplements
            ],
            # ── Coverage & merged answer ──
            "coverage": aggregation.get("coverage", {}),
            "merged_answer": aggregation.get("merged_answer", {}),
        }

        with self._lock:
            self._reports[report_id] = report

        return report

    def push_to_l3a(self, report: dict) -> dict:
        """Push a structured report to L3A via CentralController."""
        try:
            from l3.cell.peers.l3 import get_coordinator
            coord = get_coordinator()
            result = coord.process_intent(
                f"Discussion completed: {report.get('session_id', '')}\n"
                f"Status: {report.get('status', '')}\n"
                f"Divergences: {len(report.get('divergences', []))}\n"
                f"Supplements: {len(report.get('supplements', []))}"
            )
            return {"success": True, "l3a_result": result.get("success")}
        except Exception as e:
            logger.warning("report push to L3A: %s", e)
            return {"success": False, "error": str(e)}

    def push_to_frontend(self, report: dict) -> None:
        """Emit SSE event for frontend consumption."""
        try:
            from l1.kernel import get_event_bus
            bus = get_event_bus()
            bus.emit_event("discussion.report", data={
                "report_id": report.get("id", ""),
                "session_id": report.get("session_id", ""),
                "status": report.get("status", ""),
                "divergences": len(report.get("divergences", [])),
                "supplements": len(report.get("supplements", [])),
                "consistency": len(report.get("consistency", [])),
            })
        except Exception as e:
            logger.warning("report SSE: %s", e)

    def get_report(self, report_id: str) -> dict | None:
        """Return the report with *report_id*, or None."""
        with self._lock:
            return self._reports.get(report_id)

    def get_reports_by_session(self, session_id: str) -> list[dict]:
        """Return all reports belonging to *session_id*."""
        with self._lock:
            return [r for r in self._reports.values()
                    if r.get("session_id") == session_id]

    def list_reports(self, status: str = "") -> list[dict]:
        """List reports, optionally filtered by status, newest first."""
        with self._lock:
            reports = list(self._reports.values())
        if status:
            reports = [r for r in reports if r.get("status") == status]
        return sorted(reports, key=lambda r: r.get("created_at", 0), reverse=True)


# ── Singleton ──

_service: ReportService | None = None


def get_service() -> ReportService:
    """Return the shared ReportService singleton."""
    global _service
    if _service is None:
        _service = ReportService()
    return _service


def reset_service() -> None:
    """Reset the ReportService singleton to None."""
    global _service
    _service = None
