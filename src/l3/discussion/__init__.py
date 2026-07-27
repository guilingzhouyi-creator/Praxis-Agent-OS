"""Discussion & Convergence — Cross-Cell multi-agent orchestration.

Exports:
  - IssueOrchestrator — start/query/completion lifecycle
  - CellAnswerRepo — per-Cell answer persistence
  - AnswerAggregator — cross-Cell merge and analysis
  - SupplementManager — classify and route supplement issues
  - ReportService — structured report generation
"""

from __future__ import annotations

from .issue_orchestrator import IssueOrchestrator, DiscussionSession
from .cell_answer_repo import CellAnswerRepo, CellAnswer
from .answer_aggregator import AnswerAggregator
from .supplement_manager import SupplementManager
from .report_service import ReportService

__all__ = [
    "IssueOrchestrator", "DiscussionSession",
    "CellAnswerRepo", "CellAnswer",
    "AnswerAggregator",
    "SupplementManager",
    "ReportService",
]
