"""ToolPolicy — access control rules, load from YAML, evaluation tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


def test_policy_action_values():
    from l3.tool_system.tool_policy import PolicyAction
    assert PolicyAction.DISABLE.value == "disable"
    assert PolicyAction.ENABLE.value == "enable"
    assert PolicyAction.REQUIRE_APPROVAL.value == "require_approval"


def test_policy_scope_priority():
    from l3.tool_system.tool_policy import PolicyScope
    assert PolicyScope.GLOBAL.value == "global"
    assert PolicyScope.CELL.value == "cell"
    assert PolicyScope.ROLE.value == "role"


class TestToolPolicy:
    """ToolPolicy using classmethods."""

    def setup_method(self):
        from l3.tool_system.tool_policy import ToolPolicy
        ToolPolicy.clear()

    def test_register_agent(self):
        from l3.tool_system.tool_policy import ToolPolicy
        ToolPolicy.register_agent("agent-a", role="reader")

    def test_is_allowed_no_rules(self):
        from l3.tool_system.tool_policy import ToolPolicy
        result = ToolPolicy.is_allowed("agent-reader", "read_file")
        assert isinstance(result, bool)

    def test_add_rule(self):
        from l3.tool_system.tool_policy import PolicyAction, PolicyRule, PolicyScope, ToolPolicy
        rule = PolicyRule(action=PolicyAction.ENABLE, tool="read_file",
                          scope=PolicyScope.ROLE, scope_id="reader")
        ToolPolicy.add(rule)
        rules = ToolPolicy.list_rules()
        assert len(rules) >= 1

    def test_add_rule_then_clear(self):
        from l3.tool_system.tool_policy import PolicyAction, PolicyRule, PolicyScope, ToolPolicy
        rule = PolicyRule(action=PolicyAction.ENABLE, tool="tool_x",
                          scope=PolicyScope.GLOBAL, scope_id="*")
        ToolPolicy.add(rule)
        ToolPolicy.clear()
        assert len(ToolPolicy.list_rules()) == 0

    def test_add_and_remove_rule(self):
        from l3.tool_system.tool_policy import PolicyAction, PolicyRule, PolicyScope, ToolPolicy
        rule = PolicyRule(action=PolicyAction.ENABLE, tool="tmp_tool",
                          scope=PolicyScope.GLOBAL, scope_id="*")
        ToolPolicy.add(rule)
        before = len(ToolPolicy.list_rules())
        ToolPolicy.remove("tmp_tool", PolicyScope.GLOBAL, scope_id="*")
        after = len(ToolPolicy.list_rules())
        assert after < before

    def test_to_dict(self):
        from l3.tool_system.tool_policy import ToolPolicy
        d = ToolPolicy.to_dict()
        assert isinstance(d, dict)

    def test_requires_approval_with_rule(self):
        from l3.tool_system.tool_policy import PolicyAction, PolicyRule, PolicyScope, ToolPolicy
        rule = PolicyRule(action=PolicyAction.REQUIRE_APPROVAL, tool="risky_tool",
                          scope=PolicyScope.GLOBAL, scope_id="*")
        ToolPolicy.add(rule)
        assert ToolPolicy.requires_approval("*", "risky_tool")

    def test_load_from_dict(self):
        from l3.tool_system.tool_policy import ToolPolicy
        cfg = {
            "blacklist": [{"tool": "bad_tool", "scope": "global"}],
            "approval_required": [{"tool": "risky_tool", "scope": "global"}],
        }
        ToolPolicy.load_from_yaml(cfg)
        assert len(ToolPolicy.list_rules()) > 0
