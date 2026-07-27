"""Discussion API handlers — Layer 3 discussion lifecycle endpoints.

Endpoints:
  POST /api/v2/discussion/start              — start discussion for an issue
  GET  /api/v2/discussion/{id}               — session status
  GET  /api/v2/discussion/{id}/answers       — raw answers
  GET  /api/v2/discussion/{id}/report        — aggregated report
  POST /api/v2/discussion/{id}/supplement    — submit supplement issue
  GET  /api/v2/discussion/sessions           — list all sessions
  GET  /api/v2/discussion/reports            — list all reports
  POST /api/v2/discussion/push-to-l3a        — push report to L3A
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def handle_discussion_start(body: dict | None = None) -> dict:
    """POST /api/v2/discussion/start — start discussion for an issue."""
    b = body or {}
    issue_card_id = b.get("issue_card_id", "")
    if not issue_card_id:
        return {"success": False, "error": "issue_card_id required"}
    try:
        from l3.card.issue import get_table
        card = get_table().get(issue_card_id)
        if not card:
            return {"success": False, "error": f"issue card not found: {issue_card_id}"}
        from l3.discussion.issue_orchestrator import get_orchestrator
        orch = get_orchestrator()
        return orch.start_discussion(card)
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_discussion_get(session_id: str = "") -> dict:
    """GET /api/v2/discussion/{id} — session status."""
    if not session_id:
        return {"success": False, "error": "session_id required"}
    try:
        from l3.discussion.issue_orchestrator import get_orchestrator
        session = get_orchestrator().get_session(session_id)
        if not session:
            return {"success": False, "error": f"session not found: {session_id}"}
        return {"success": True, "session": {
            "id": session.id,
            "issue_card_id": session.issue_card_id,
            "status": session.status,
            "phase": session.phase,
            "cells": len(session.participating_cells),
            "completed_cells": len(session.completed_cells),
            "answers": session.total_answers,
            "supplements": len(session.supplement_issues),
            "created_at": session.created_at,
            "completed_at": session.completed_at,
        }}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_discussion_answers(session_id: str = "") -> dict:
    """GET /api/v2/discussion/{id}/answers — raw cell answers."""
    if not session_id:
        return {"success": False, "error": "session_id required"}
    try:
        from l3.discussion.answer_aggregator import AnswerAggregator
        agg = AnswerAggregator()
        result = agg.collect(session_id)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_discussion_report(session_id: str = "") -> dict:
    """GET /api/v2/discussion/{id}/report — aggregated report."""
    if not session_id:
        return {"success": False, "error": "session_id required"}
    try:
        from l3.discussion.report_service import get_service
        reports = get_service().get_reports_by_session(session_id)
        if not reports:
            # Generate on demand
            from l3.discussion.answer_aggregator import AnswerAggregator
            agg = AnswerAggregator()
            result = agg.collect(session_id)
            if not result.get("success"):
                return result
            from l3.discussion.report_service import get_service
            report = get_service().generate(session_id, result)
            return {"success": True, "report": report}
        return {"success": True, "report": reports[-1]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_discussion_supplement(session_id: str = "",
                                 body: dict | None = None) -> dict:
    """POST /api/v2/discussion/{id}/supplement — submit supplement issue."""
    if not session_id:
        return {"success": False, "error": "session_id required"}
    b = body or {}
    try:
        from l3.discussion.supplement_manager import SupplementManager
        mgr = SupplementManager()
        supplement = {
            "title": b.get("title", ""),
            "description": b.get("description", ""),
            "domain": b.get("domain", ""),
            "source_cell": b.get("source_cell", ""),
        }
        return mgr.cross_cell_route(supplement, session_id)
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_discussion_sessions(body: dict | None = None) -> dict:
    """GET /api/v2/discussion/sessions — list all sessions."""
    try:
        from l3.discussion.issue_orchestrator import get_orchestrator
        status = (body or {}).get("status", "") if body else ""
        return {"success": True, "sessions": get_orchestrator().list_sessions(status)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_discussion_reports(body: dict | None = None) -> dict:
    """GET /api/v2/discussion/reports — list all reports."""
    try:
        from l3.discussion.report_service import get_service
        status = (body or {}).get("status", "") if body else ""
        return {"success": True, "reports": get_service().list_reports(status)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_discussion_push_l3a(body: dict | None = None) -> dict:
    """POST /api/v2/discussion/push-to-l3a — push report to L3A."""
    b = body or {}
    session_id = b.get("session_id", "")
    if not session_id:
        return {"success": False, "error": "session_id required"}
    try:
        from l3.discussion.report_service import get_service
        reports = get_service().get_reports_by_session(session_id)
        if not reports:
            return {"success": False, "error": "no report for session"}
        result = get_service().push_to_l3a(reports[-1])
        get_service().push_to_frontend(reports[-1])
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}
