"""IssueOrchestrator — top-level discussion lifecycle management.

Receives IssueCards from L3A, broadcasts to all Cells, manages AnswerSessions
per Cell, triggers AnswerAggregation when all Cells complete, and routes
supplement issues back through the pipeline.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import HASH_TRUNC_MEDIUM

logger = logging.getLogger(__name__)


@dataclass
class DiscussionSession:
    """One complete discussion lifecycle for a single IssueCard."""
    id: str = ""
    issue_card_id: str = ""
    status: str = "pending"
    participating_cells: list[str] = field(default_factory=list)
    completed_cells: list[str] = field(default_factory=list)
    phase: int = 0
    total_answers: int = 0
    supplement_issues: list[dict] = field(default_factory=list)
    report_ref: str = ""
    created_at: float = 0.0
    completed_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()


class IssueOrchestrator:
    """Manages the full lifecycle of a discussion session.

    Flow:
      1. start_discussion(issue_card) → DiscussionSession
      2. Broadcast to all Cells
      3. Each Cell runs AnswerSession independently
      4. Cell completion fires "discussion.cell_complete" event
      5. All Cells complete → AnswerAggregator collects
      6. Supplements extracted → routed back
      7. Final report → L3A
    """

    def __init__(self):
        self._sessions: dict[str, DiscussionSession] = {}
        self._lock = threading.RLock()

    # ── Lifecycle ─────────────────────────────────────────────

    def start_discussion(self, issue_card: Any) -> dict:
        """Start a new discussion session for an issue card."""
        session_id = f"disc-{uuid.uuid4().hex[:HASH_TRUNC_MEDIUM]}"

        with self._lock:
            session = DiscussionSession(
                id=session_id,
                issue_card_id=getattr(issue_card, "id", ""),
                status="in_progress",
                phase=1,
            )
            self._sessions[session_id] = session

        # Register with IssueTable
        try:
            from l3.card.issue import get_table
            table = get_table()
            table.set_status(issue_card.id, "DELIBERATING")
        except Exception as e:
            logger.warning("orchestrator: issue table update: %s", e)

        logger.info("orchestrator: started discussion %s for issue %s",
                     session_id, getattr(issue_card, "id", "?"))

        return {"success": True, "session_id": session_id}

    def register_cell(self, session_id: str, cell_id: str) -> dict:
        """Register a Cell as participating in a discussion."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"success": False, "error": f"session not found: {session_id}"}
            if cell_id not in session.participating_cells:
                session.participating_cells.append(cell_id)
            return {"success": True, "cell_id": cell_id}

    def process_cell_completion(self, session_id: str, cell_id: str,
                                 answer_count: int,
                                 supplement_count: int) -> dict:
        """Called when a Cell completes its AnswerSession.

        Collects the result.  When all Cells complete, triggers aggregation.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"success": False, "error": f"session not found: {session_id}"}

            if cell_id not in session.completed_cells:
                session.completed_cells.append(cell_id)
            session.total_answers += answer_count
            session.phase = 4

            # Check if all cells completed
            if set(session.completed_cells) >= set(session.participating_cells):
                return self._finalize(session)

        return {"success": True, "session_id": session_id,
                "completed": len(session.completed_cells),
                "total": len(session.participating_cells)}

    def _finalize(self, session: DiscussionSession) -> dict:
        """All Cells completed — trigger aggregation and reporting."""
        session.phase = 5
        logger.info("orchestrator: all %d cells completed for %s",
                     len(session.participating_cells), session.id)

        # Trigger AnswerAggregator
        try:
            from .answer_aggregator import AnswerAggregator
            aggregator = AnswerAggregator()
            report = aggregator.collect(session.id)
            session.report_ref = report.get("session_id", "")

            # Process supplements
            supplements = report.get("supplement_issues", [])
            if supplements:
                self._route_supplements(session, supplements)

            # Update IssueTable status
            session.status = "completed"
            session.completed_at = time.time()

            # Push report via bus event
            try:
                from l1.kernel import get_event_bus
                bus = get_event_bus()
                bus.emit_event("discussion.completed", data={
                    "session_id": session.id,
                    "issue_card_id": session.issue_card_id,
                    "status": "completed",
                    "total_answers": session.total_answers,
                    "supplements": len(supplements),
                })
            except Exception:
                logger.debug("issue_orchestrator: session collect failed")

        except Exception as e:
            logger.error("orchestrator: finalize failed: %s", e)
            session.status = "failed"
            return {"success": False, "error": str(e)}

        return {"success": True, "session_id": session.id,
                "status": "completed", "report_ref": session.report_ref}

    def _route_supplements(self, session: DiscussionSession,
                           supplements: list[dict]) -> None:
        """Route supplement issues back through IssueTable."""
        try:
            from .supplement_manager import SupplementManager
            mgr = SupplementManager()
            classified = mgr.classify(supplements)
            for item in classified.get("cross_cell", []):
                mgr.cross_cell_route(item, session.id)
            session.supplement_issues = classified.get("cross_cell", [])
        except Exception as e:
            logger.warning("orchestrator: supplement routing: %s", e)

    # ── Query ─────────────────────────────────────────────────

    def get_session(self, session_id: str) -> DiscussionSession | None:
        """Return the session with *session_id*, or None."""
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(self, status: str = "") -> list[dict]:
        """List sessions, optionally filtered by status, newest first."""
        with self._lock:
            sessions = list(self._sessions.values())
        if status:
            sessions = [s for s in sessions if s.status == status]
        return [
            {"id": s.id, "issue_card_id": s.issue_card_id,
             "status": s.status, "cells": len(s.participating_cells),
             "completed_cells": len(s.completed_cells),
             "answers": s.total_answers,
             "created_at": s.created_at}
            for s in sorted(sessions, key=lambda x: x.created_at, reverse=True)
        ]

    def stats(self) -> dict:
        """Return session statistics (total, active, completed)."""
        with self._lock:
            return {
                "total_sessions": len(self._sessions),
                "active": sum(1 for s in self._sessions.values()
                              if s.status == "in_progress"),
                "completed": sum(1 for s in self._sessions.values()
                                 if s.status == "completed"),
            }


# ── Singleton ──

_orchestrator: IssueOrchestrator | None = None
_orch_lock = threading.Lock()


def get_orchestrator() -> IssueOrchestrator:
    """Return the shared IssueOrchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        with _orch_lock:
            if _orchestrator is None:
                _orchestrator = IssueOrchestrator()
    return _orchestrator


def reset_orchestrator() -> None:
    """Reset the orchestrator singleton to None."""
    global _orchestrator
    _orchestrator = None
