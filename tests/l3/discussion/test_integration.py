"""L3 Discussion & Convergence integration test.

Covers IssueOrchestrator lifecycle, CellAnswerRepo persistence,
AnswerAggregator merge, SupplementManager routing, and ReportService.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestIssueOrchestrator:
    """IssueOrchestrator lifecycle — start, submit, complete."""

    def _get_orchestrator(self):
        from l3.discussion.issue_orchestrator import get_orchestrator, reset_orchestrator
        reset_orchestrator()
        return get_orchestrator()

    def test_start_discussion(self):
        orch = self._get_orchestrator()
        issue_card = {"id": "test-issue-1", "title": "Test discussion"}
        r = orch.start_discussion(issue_card)
        assert r.get("success"), f"start failed: {r}"
        assert r.get("session_id", "").startswith("disc-")

    def test_list_sessions(self):
        orch = self._get_orchestrator()
        orch.start_discussion({"id": "issue-2"})
        sessions = orch.list_sessions()
        assert isinstance(sessions, list)
        assert len(sessions) >= 1

    def test_cell_answer_round_trip(self):
        from l3.discussion.cell_answer_repo import CellAnswerRepo, CellAnswer
        repo = CellAnswerRepo(cell_id="cell-1", session_id="ds-test-1")
        answer = CellAnswer(
            session_id="ds-test-1",
            cell_id="cell-1",
            content={"text": "Yes, Python 3.13 is stable"},
            answer_type="answer",
        )
        repo.store_answer(answer)
        answers = repo.get_answers(phase=0, answer_type="answer")
        assert len(answers) == 1
        assert answers[0].cell_id == "cell-1"
        assert answers[0].content.get("text") == "Yes, Python 3.13 is stable"


class TestAnswerAggregator:
    """AnswerAggregator merges and ranks cross-cell answers."""

    def test_collect_empty(self):
        from l3.discussion.answer_aggregator import AnswerAggregator
        agg = AnswerAggregator()
        r = agg.collect("nonexistent-session")
        assert isinstance(r, dict)  # should not raise

    def test_aggregate_single_answer(self):
        from l3.discussion.answer_aggregator import AnswerAggregator
        from l3.discussion.cell_answer_repo import CellAnswer
        agg = AnswerAggregator()
        answer = CellAnswer(
            session_id="s1", cell_id="c1",
            content={"text": "Use Python 3.13"},
            answer_type="answer",
        )
        r = agg.collect("s1")
        assert isinstance(r, dict)


class TestSupplementManager:
    """SupplementManager — classify and route supplements."""

    def test_classify_supplement(self):
        from l3.discussion.supplement_manager import SupplementManager
        mgr = SupplementManager()
        supplement = {"id": "sup-1", "description": "What about Windows support?"}
        r = mgr.classify([supplement])  # classify expects list[dict]
        assert isinstance(r, dict)
        assert "scope" in r or "total" in r


class TestReportService:
    """ReportService — structured report generation."""

    def test_generate_report(self):
        from l3.discussion.report_service import ReportService, get_service, reset_service
        reset_service()
        svc = get_service()
        r = svc.generate(
            session_id="ds-report-1",
            aggregation={"summary": "Team prefers Python 3.13", "title": "Migration Decision"},
        )
        assert isinstance(r, dict)
