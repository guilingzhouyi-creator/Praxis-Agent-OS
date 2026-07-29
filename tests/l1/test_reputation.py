"""Tests for kernel reputation system — agent trust scores for GateChain G5."""

from __future__ import annotations

import pytest

from l1.kernel.reputation import (
    ReputationSystem,
    get_reputation,
    reset_reputation,
)
from l1.kernel.params.agent import (
    REP_DEFAULT_REPUTATION,
    REP_TASK_SUCCESS,
    REP_TASK_FAILURE,
)


# ═══════════════════════════════════════════════════════════════════
# ReputationSystem
# ═══════════════════════════════════════════════════════════════════


class TestReputationGet:
    def test_get_unknown_agent_returns_default(self):
        rs = ReputationSystem()
        score = rs.get("unknown-agent")
        assert score == REP_DEFAULT_REPUTATION

    def test_get_after_set(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        assert rs.get("agent-a") == 0.5


class TestReputationSet:
    def test_set_clamps_to_max(self):
        rs = ReputationSystem()
        rs.set("agent-a", 2.0)
        assert rs.get("agent-a") == 1.0

    def test_set_clamps_to_min(self):
        rs = ReputationSystem()
        rs.set("agent-a", -0.5)
        assert rs.get("agent-a") == 0.0

    def test_set_normal_value(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.75)
        assert rs.get("agent-a") == 0.75


class TestReputationAdjust:
    def test_adjust_positive(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        new = rs.adjust("agent-a", 0.1)
        assert new == pytest.approx(0.6)

    def test_adjust_negative(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        new = rs.adjust("agent-a", -0.2)
        assert new == pytest.approx(0.3)

    def test_adjust_unknown_agent(self):
        rs = ReputationSystem()
        new = rs.adjust("new-agent", 0.1)
        assert new == pytest.approx(REP_DEFAULT_REPUTATION + 0.1)


class TestReputationRecordTask:
    def test_task_success_increases(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        new = rs.record_task("agent-a", success=True)
        assert new == pytest.approx(0.5 + REP_TASK_SUCCESS)

    def test_task_failure_decreases(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        new = rs.record_task("agent-a", success=False)
        assert new == pytest.approx(0.5 + REP_TASK_FAILURE)


class TestReputationRecordReview:
    def test_review_approved(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        new = rs.record_review("agent-a", approved=True)
        assert new == pytest.approx(0.5 + 0.01)

    def test_review_rejected(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        new = rs.record_review("agent-a", approved=False)
        assert new == pytest.approx(0.5 - 0.03)


class TestReputationRecordDispute:
    def test_dispute_upheld(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        new = rs.record_dispute("agent-a", upheld=True)
        assert new == pytest.approx(0.5 + 0.03)

    def test_dispute_dismissed(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.5)
        new = rs.record_dispute("agent-a", upheld=False)
        assert new == pytest.approx(0.5 - 0.02)


class TestReputationAll:
    def test_all_empty(self):
        rs = ReputationSystem()
        assert rs.all() == {}

    def test_all_multi_agent(self):
        rs = ReputationSystem()
        rs.set("agent-a", 0.8)
        rs.set("agent-b", 0.6)
        all_scores = rs.all()
        assert len(all_scores) == 2
        assert all_scores["agent-a"] == 0.8
        assert all_scores["agent-b"] == 0.6


# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════


class TestGetReputation:
    def test_get_reputation_singleton(self):
        reset_reputation()
        r1 = get_reputation()
        r2 = get_reputation()
        assert r1 is r2

    def test_reset_reputation(self):
        reset_reputation()
        r = get_reputation()
        r.set("agent-a", 0.9)
        reset_reputation()
        r2 = get_reputation()
        assert r2.get("agent-a") == REP_DEFAULT_REPUTATION
