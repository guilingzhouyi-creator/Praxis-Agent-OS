"""ExecutionPlan execution test — init/execute/summary.

Card API: Card(intent, domain, phases=[Phase(name, mode, steps=[Step(...)])])
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestExecutionPlanInit:
    """ExecutionPlan creation and basic attributes"""

    def test_init_with_card(self):
        from l3.card import Card
        from l3.execution_plan import ExecutionPlan
        card = Card(intent="test", domain=".")
        plan = ExecutionPlan(card, {"reader": "agent-r"})
        assert plan.card is not None
        assert plan.agent_map == {"reader": "agent-r"}

    def test_init_multi_agent(self):
        from l3.card import Card
        from l3.execution_plan import ExecutionPlan
        card = Card(intent="multi test", domain=".")
        amap = {"reader": "r1", "writer": "w1"}
        plan = ExecutionPlan(card, amap)
        assert len(plan.agent_map) == 2


class TestExecutionPlanExecute:
    """execute() basic execution flow"""

    def test_execute_returns_dict(self):
        from l3.card import Card
        from l3.execution_plan import ExecutionPlan
        card = Card(intent="exec test", domain=".")
        plan = ExecutionPlan(card, {"reader": "auto-a"})
        r = plan.execute()
        assert isinstance(r, dict)
        assert "steps" in r or "success" in r

    def test_execute_multi_step_card(self):
        from l3.card import Card
        from l3.execution_plan import ExecutionPlan
        card = Card(intent="multi step", domain=".")
        plan = ExecutionPlan(card, {"reader": "auto-b"})
        r = plan.execute()
        assert isinstance(r, dict)


class TestExecutionPlanSummary:
    """summary() execution summary"""

    def test_summary_returns_string_or_dict(self):
        from l3.card import Card
        from l3.execution_plan import ExecutionPlan
        card = Card(intent="summary test", domain=".")
        plan = ExecutionPlan(card, {"reader": "auto-c"})
        plan.execute()
        s = plan.summary()
        assert isinstance(s, (str, dict))


class TestExecutionPlanSteps:
    """steps property"""

    def test_steps_is_list(self):
        from l3.card import Card
        from l3.execution_plan import ExecutionPlan
        card = Card(intent="steps test", domain=".")
        plan = ExecutionPlan(card, {"reader": "auto-d"})
        plan.execute()
        steps = plan.steps
        assert isinstance(steps, list)
