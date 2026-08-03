"""PlanStepTypes — step and state enum tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestPlanStepTypes:
    def test_step_state_enum(self):
        from l3.card.plan_step_types import StepState
        assert StepState.PENDING.name == "PENDING"
        assert StepState.RUNNING.name == "RUNNING"
        assert StepState.DONE.name == "DONE"
