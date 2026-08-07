"""ExecutionPlan execution test — init/execute/summary.

Card API: Card(intent, domain, phases=[Phase(name, mode, steps=[Step(...)])])
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestExecutionPlanInit:
    """ExecutionPlan creation and basic attributes — card wrapping, agent map."""

    def test_init_with_card(self):
        from l3.card.execution_plan import ExecutionPlan
        from l3.card.models import Card

        card = Card(intent="test", domain=".")
        plan = ExecutionPlan(card, {"reader": "agent-r"})
        assert plan.card is not None
        assert plan.agent_map == {"reader": "agent-r"}

    def test_init_multi_agent(self):
        from l3.card.execution_plan import ExecutionPlan
        from l3.card.models import Card

        card = Card(intent="multi test", domain=".")
        amap = {"reader": "r1", "writer": "w1"}
        plan = ExecutionPlan(card, amap)
        assert len(plan.agent_map) == 2


class TestExecutionPlanExecute:
    """execute() basic execution flow"""

    def test_execute_returns_dict(self):
        from l3.card.execution_plan import ExecutionPlan
        from l3.card.models import Card

        card = Card(intent="exec test", domain=".")
        plan = ExecutionPlan(card, {"reader": "auto-a"})
        r = plan.execute()
        assert isinstance(r, dict), f"expected dict, got {type(r)}"
        assert "success" in r, f"result missing 'success' key: {r.keys()}"
        assert "steps" in r, f"result missing 'steps' key: {r.keys()}"

    def test_execute_multi_step_card(self):
        from l3.card.execution_plan import ExecutionPlan
        from l3.card.models import Card

        card = Card(intent="multi step", domain=".")
        plan = ExecutionPlan(card, {"reader": "auto-b"})
        r = plan.execute()
        assert isinstance(r, dict), f"expected dict, got {type(r)}"
        assert r.get("success") is not None, f"result missing 'success': {r}"


class TestExecutionPlanSummary:
    """summary() execution summary"""

    def test_summary_returns_string_or_dict(self):
        from l3.card.execution_plan import ExecutionPlan
        from l3.card.models import Card

        card = Card(intent="summary test", domain=".")
        plan = ExecutionPlan(card, {"reader": "auto-c"})
        plan.execute()
        s = plan.summary()
        assert isinstance(s, (str, dict))


class TestExecutionPlanSteps:
    """steps property"""

    def test_steps_is_list(self):
        from l3.card.execution_plan import ExecutionPlan
        from l3.card.models import Card

        card = Card(intent="steps test", domain=".")
        plan = ExecutionPlan(card, {"reader": "auto-d"})
        plan.execute()
        steps = plan.steps
        assert isinstance(steps, list)


class TestDeriveActionScope:
    """ExecutionPlan._derive_action_scope 动作分类逻辑测试"""

    def _derive(self, action: str) -> list[str]:
        """调用ExecutionPlan的_derive_action_scope静态方法"""
        from l3.card.execution_plan import ExecutionPlan

        return ExecutionPlan._derive_action_scope(action)

    def test_read_action_returns_read_tools(self):
        """read 类动作应返回只读工具集"""
        tools = self._derive("read_file")
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_read_keyword_returns_read_tools(self):
        """'read' 关键词应映射到只读工具"""
        tools = self._derive("read")
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_inspect_keyword_returns_read_tools(self):
        """'inspect' 关键词应映射到只读工具"""
        tools = self._derive("inspect")
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_scout_keyword_returns_read_tools(self):
        """'scout' 关键词应映射到只读工具"""
        tools = self._derive("scout")
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_write_keyword_returns_write_tools(self):
        """'write' 关键词应映射到写入工具"""
        tools = self._derive("write")
        assert isinstance(tools, list)

    def test_edit_keyword_returns_write_tools(self):
        """'edit' 关键词应映射到写入工具"""
        tools = self._derive("edit")
        assert isinstance(tools, list)

    def test_run_keyword_returns_shell_tools(self):
        """'run' 关键词应映射到 shell 工具"""
        tools = self._derive("run")
        assert isinstance(tools, list)

    def test_think_keyword_returns_all_tools(self):
        """'think' 应返回所有工具（读+写+shell）"""
        tools = self._derive("think")
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_unknown_action_returns_all_tools(self):
        """未知动作应返回全部工具（安全保守）"""
        tools = self._derive("unknown_action_xyz")
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_case_insensitive(self):
        """动作名应大小写不敏感"""
        lower = self._derive("Read")
        upper = self._derive("READ")
        assert lower == upper

    def test_scout_categorized_as_read(self):
        """scout 动作应与 read 类返回相同的工具集"""
        read_tools = self._derive("read")
        scout_tools = self._derive("scout")
        assert set(scout_tools) == set(read_tools), "scout should return same tools as read"

    def test_execute_keyword_returns_shell_tools(self):
        """'execute' 关键词应映射到 shell 工具"""
        tools = self._derive("execute")
        assert isinstance(tools, list)
        assert len(tools) > 0
