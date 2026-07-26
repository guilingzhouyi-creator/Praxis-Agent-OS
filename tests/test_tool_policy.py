"""ToolPolicy 单测 — 多层策略 / 缓存 / load_from_yaml (S4 修复点)。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from services.tool_policy import (
    PolicyAction,
    PolicyRule,
    PolicyScope,
    ToolPolicy,
)


@pytest.fixture(autouse=True)
def _clean_policy():
    """Each test starts with empty rules + caches."""
    ToolPolicy.clear()
    ToolPolicy._agent_role.clear()
    ToolPolicy._agent_cell.clear()
    yield
    ToolPolicy.clear()
    ToolPolicy._agent_role.clear()
    ToolPolicy._agent_cell.clear()


class TestPolicyEnums:
    """PolicyScope.priority ordering."""

    def test_session_has_highest_priority(self):
        assert PolicyScope.SESSION.priority > PolicyScope.AGENT.priority

    def test_global_has_lowest_priority(self):
        assert PolicyScope.GLOBAL.priority < PolicyScope.CELL.priority

    def test_priority_values_descending(self):
        """SESSION(5) > AGENT(4) > ROLE(3) > CELL(2) > GLOBAL(1)."""
        assert PolicyScope.SESSION.priority == 5
        assert PolicyScope.AGENT.priority == 4
        assert PolicyScope.ROLE.priority == 3
        assert PolicyScope.CELL.priority == 2
        assert PolicyScope.GLOBAL.priority == 1


class TestRuleKey:
    """PolicyRule.key() uniqueness."""

    def test_key_format(self):
        rule = PolicyRule(
            scope=PolicyScope.AGENT, scope_id="writer-1",
            tool="read_file", action=PolicyAction.DISABLE,
        )
        assert rule.key() == "agent:writer-1:read_file"

    def test_different_tools_have_different_keys(self):
        r1 = PolicyRule(scope=PolicyScope.GLOBAL, scope_id="",
                        tool="read_file", action=PolicyAction.DISABLE)
        r2 = PolicyRule(scope=PolicyScope.GLOBAL, scope_id="",
                        tool="write_file", action=PolicyAction.DISABLE)
        assert r1.key() != r2.key()


class TestAddRemove:
    """Rule management + cache invalidation (S4 fix)."""

    def test_add_rule(self):
        rule = PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="read_file", action=PolicyAction.DISABLE,
        )
        ToolPolicy.add(rule)
        assert len(ToolPolicy.list_rules()) == 1

    def test_add_replaces_same_key(self):
        """Adding a rule with existing key replaces, not duplicates."""
        r1 = PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="read_file", action=PolicyAction.DISABLE,
        )
        r2 = PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="read_file", action=PolicyAction.ENABLE,
        )
        ToolPolicy.add(r1)
        ToolPolicy.add(r2)
        rules = ToolPolicy.list_rules()
        assert len(rules) == 1
        assert rules[0]["action"] == "enable"

    def test_remove_rule(self):
        rule = PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="read_file", action=PolicyAction.DISABLE,
        )
        ToolPolicy.add(rule)
        assert ToolPolicy.remove("read_file", PolicyScope.GLOBAL)
        assert len(ToolPolicy.list_rules()) == 0

    def test_remove_nonexistent_returns_false(self):
        assert not ToolPolicy.remove("nonexistent", PolicyScope.GLOBAL)

    def test_add_invalidates_cache(self):
        """S4 fix: cache cleared on add so stale entries don't persist."""
        ToolPolicy.register_agent("agent-1", "writer", "cell-1")
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="read_file", action=PolicyAction.ENABLE,
        ))
        # Populate cache
        assert ToolPolicy.is_allowed("agent-1", "read_file")
        assert "agent-1" in ToolPolicy._agent_cache
        assert "read_file" in ToolPolicy._agent_cache["agent-1"]
        # Add another rule — cache should clear
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="write_file", action=PolicyAction.DISABLE,
        ))
        assert ToolPolicy._agent_cache == {}


class TestEvaluation:
    """is_allowed / requires_approval across policy layers."""

    def test_no_rules_allows_everything(self):
        ToolPolicy.register_agent("agent-1", "writer", "cell-1")
        assert ToolPolicy.is_allowed("agent-1", "any_tool")
        assert not ToolPolicy.requires_approval("agent-1", "any_tool")

    def test_global_disable_blocks_all_agents(self):
        ToolPolicy.register_agent("agent-1", "writer", "cell-1")
        ToolPolicy.register_agent("agent-2", "reader", "cell-2")
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="dangerous_tool", action=PolicyAction.DISABLE,
        ))
        assert not ToolPolicy.is_allowed("agent-1", "dangerous_tool")
        assert not ToolPolicy.is_allowed("agent-2", "dangerous_tool")

    def test_agent_scope_overrides_global(self):
        """Agent-level ENABLE overrides global DISABLE."""
        ToolPolicy.register_agent("agent-1", "writer", "cell-1")
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="special_tool", action=PolicyAction.DISABLE,
        ))
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.AGENT, scope_id="agent-1",
            tool="special_tool", action=PolicyAction.ENABLE,
        ))
        assert ToolPolicy.is_allowed("agent-1", "special_tool")

    def test_session_scope_highest_priority(self):
        """SESSION > AGENT > ROLE > CELL > GLOBAL."""
        ToolPolicy.register_agent("agent-1", "writer", "cell-1")
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.AGENT, scope_id="agent-1",
            tool="t1", action=PolicyAction.DISABLE,
        ))
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.SESSION, scope_id="",
            tool="t1", action=PolicyAction.ENABLE,
        ))
        assert ToolPolicy.is_allowed("agent-1", "t1")

    def test_require_approval_action(self):
        ToolPolicy.register_agent("agent-1", "writer", "cell-1")
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="sensitive_tool", action=PolicyAction.REQUIRE_APPROVAL,
        ))
        assert ToolPolicy.requires_approval("agent-1", "sensitive_tool")
        assert ToolPolicy.is_allowed("agent-1", "sensitive_tool")

    def test_wildcard_tool_match(self):
        """tool='*' matches any tool name."""
        ToolPolicy.register_agent("agent-1", "writer", "cell-1")
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="*", action=PolicyAction.DISABLE,
        ))
        assert not ToolPolicy.is_allowed("agent-1", "any_tool")
        assert not ToolPolicy.is_allowed("agent-1", "other_tool")


class TestCache:
    """_agent_cache behavior (S4 fix)."""

    def test_cache_populated_after_evaluate(self):
        ToolPolicy.register_agent("agent-1", "writer", "cell-1")
        ToolPolicy.is_allowed("agent-1", "read_file")
        assert "agent-1" in ToolPolicy._agent_cache
        assert "read_file" in ToolPolicy._agent_cache["agent-1"]

    def test_clear_empties_cache(self):
        ToolPolicy.register_agent("agent-1", "writer", "cell-1")
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="t", action=PolicyAction.DISABLE,
        ))
        ToolPolicy.is_allowed("agent-1", "t")
        assert ToolPolicy._agent_cache
        ToolPolicy.clear()
        assert ToolPolicy._agent_cache == {}


class TestParseScope:
    """_parse_scope helper (S4 fix)."""

    def test_parse_global_no_id(self):
        scope, sid = ToolPolicy._parse_scope("global")
        assert scope == PolicyScope.GLOBAL
        assert sid == ""

    def test_parse_agent_with_id(self):
        scope, sid = ToolPolicy._parse_scope("agent:writer")
        assert scope == PolicyScope.AGENT
        assert sid == "writer"

    def test_parse_cell_with_id(self):
        scope, sid = ToolPolicy._parse_scope("cell:cell-1")
        assert scope == PolicyScope.CELL
        assert sid == "cell-1"


class TestLoadFromYaml:
    """load_from_yaml — blacklist + approval_required (S4 refactor)."""

    def test_load_blacklist(self):
        cfg = {
            "blacklist": [
                {"scope": "global", "tool": "dangerous", "reason": "unsafe"},
            ],
        }
        ToolPolicy.load_from_yaml(cfg)
        rules = ToolPolicy.list_rules()
        assert len(rules) == 1
        assert rules[0]["action"] == "disable"
        assert rules[0]["tool"] == "dangerous"

    def test_load_approval_required(self):
        cfg = {
            "approval_required": [
                {"scope": "agent:writer", "tool": "deploy"},
            ],
        }
        ToolPolicy.load_from_yaml(cfg)
        rules = ToolPolicy.list_rules()
        assert len(rules) == 1
        assert rules[0]["action"] == "require_approval"

    def test_load_empty_cfg_no_op(self):
        ToolPolicy.load_from_yaml(None)
        assert len(ToolPolicy.list_rules()) == 0
        ToolPolicy.load_from_yaml({})
        assert len(ToolPolicy.list_rules()) == 0

    def test_load_scoped_entry_parsed_correctly(self):
        """S4 fix: 'agent:writer' → (AGENT, 'writer') via _parse_scope."""
        cfg = {
            "blacklist": [
                {"scope": "cell:cell-1", "tool": "rm"},
            ],
        }
        ToolPolicy.load_from_yaml(cfg)
        rules = ToolPolicy.list_rules()
        assert rules[0]["scope"] == "cell"
        assert rules[0]["scope_id"] == "cell-1"


class TestToDict:
    """to_dict() grouping by action."""

    def test_to_dict_groups_by_action(self):
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="t1", action=PolicyAction.DISABLE,
        ))
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="t2", action=PolicyAction.REQUIRE_APPROVAL,
        ))
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.GLOBAL, scope_id="",
            tool="t3", action=PolicyAction.ENABLE,
        ))
        d = ToolPolicy.to_dict()
        assert len(d["blacklist"]) == 1
        assert len(d["approval_required"]) == 1
        assert len(d["overrides"]) == 1


class TestRegisterAgent:
    """register_agent injects identity for scope matching."""

    def test_register_agent_identity(self):
        ToolPolicy.register_agent("a1", "writer", "cell-1")
        assert ToolPolicy._get_role("a1") == "writer"
        assert ToolPolicy._get_cell("a1") == "cell-1"

    def test_role_scope_matches(self):
        ToolPolicy.register_agent("a1", "writer", "cell-1")
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.ROLE, scope_id="writer",
            tool="t", action=PolicyAction.DISABLE,
        ))
        assert not ToolPolicy.is_allowed("a1", "t")

    def test_cell_scope_matches(self):
        ToolPolicy.register_agent("a1", "writer", "cell-1")
        ToolPolicy.add(PolicyRule(
            scope=PolicyScope.CELL, scope_id="cell-1",
            tool="t", action=PolicyAction.DISABLE,
        ))
        assert not ToolPolicy.is_allowed("a1", "t")
