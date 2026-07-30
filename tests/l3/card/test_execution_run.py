"""Tests for execution_run.py — execution flow extracted from execution_plan.py."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestExecutionRun:
    def test_execute_basic(self):
        from l3.execution_run import execute
        from l3.card import Card
        from l3.execution_plan import ExecutionPlan
        card = Card(intent="run test", domain=".")
        plan = ExecutionPlan(card, {"reader": "auto-run"})
        r = execute(plan, timeout=5.0)
        assert isinstance(r, dict)
        assert "steps" in r or "total_steps" in r

    def test_execute_issue_card(self):
        from l3.execution_run import execute
        from l3.card import Card
        from l3.execution_plan import ExecutionPlan
        card = Card(intent="issue test", domain=".", mode="issue")
        plan = ExecutionPlan(card, {"reader": "auto-issue"})
        r = execute(plan, timeout=5.0)
        assert isinstance(r, dict)
