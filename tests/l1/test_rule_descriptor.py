"""Tests for kernel.rule_descriptor — RuleDescriptor, RuleSeverity, CheckResult, str_to_severity.

Covers:
  - RuleSeverity / CheckResult enum values
  - str_to_severity() mapping and fallback
  - RuleDescriptor construction with all field combinations
  - evaluate() with check_fn returning PASS / WARN / BLOCK / None
  - evaluate() with check_fn=None (always PASS)
  - evaluate() passes correct arguments to check_fn
  - to_dict() serialization
  - Immutability of frozen dataclass
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from l1.kernel.rule_descriptor import (
    CheckResult,
    RuleDescriptor,
    RuleSeverity,
    str_to_severity,
)


class TestRuleSeverity:
    def test_values(self):
        assert RuleSeverity.MUST.value == 1
        assert RuleSeverity.SHOULD.value == 2
        assert RuleSeverity.MAY.value == 3


class TestCheckResult:
    def test_values(self):
        assert CheckResult.PASS.value == 1
        assert CheckResult.WARN.value == 2
        assert CheckResult.BLOCK.value == 3


class TestStrToSeverity:
    def test_must(self):
        assert str_to_severity("MUST") == RuleSeverity.MUST

    def test_should(self):
        assert str_to_severity("SHOULD") == RuleSeverity.SHOULD

    def test_may(self):
        assert str_to_severity("MAY") == RuleSeverity.MAY

    def test_case_sensitive(self):
        assert str_to_severity("must") == RuleSeverity.MAY  # unknown → fallback

    def test_empty_string_fallback(self):
        assert str_to_severity("") == RuleSeverity.MAY  # unknown → fallback

    def test_unknown_string_fallback(self):
        assert str_to_severity("CRITICAL") == RuleSeverity.MAY


class TestRuleDescriptorConstruction:
    def test_minimal(self):
        rule = RuleDescriptor(id="test.1", section="§1", severity=RuleSeverity.MUST,
                              description="Minimal rule")
        assert rule.id == "test.1"
        assert rule.section == "§1"
        assert rule.severity == RuleSeverity.MUST
        assert rule.description == "Minimal rule"
        assert rule.check_fn is None
        assert rule.source == "builtin"
        assert rule.tags == frozenset()
        assert rule.created_at > 0

    def test_full(self):
        def dummy_fn(*_):
            return CheckResult.PASS
        rule = RuleDescriptor(
            id="test.full", section="§2", severity=RuleSeverity.SHOULD,
            description="Full rule", check_fn=dummy_fn,
            source="custom", tags=frozenset({"tag1", "tag2"}),
        )
        assert rule.id == "test.full"
        assert rule.check_fn is dummy_fn
        assert rule.source == "custom"
        assert rule.tags == frozenset({"tag1", "tag2"})

    def test_created_at_is_set(self):
        import time
        before = time.time()
        rule = RuleDescriptor(id="ts", section="§1", severity=RuleSeverity.MAY,
                              description="Timestamp check")
        assert before <= rule.created_at <= time.time() + 1


class TestRuleDescriptorEvaluate:
    def test_no_check_fn_always_pass(self):
        rule = RuleDescriptor(id="noop", section="§1", severity=RuleSeverity.MUST,
                              description="No check")
        result = rule.evaluate("read_file", "agent-a")
        assert result == CheckResult.PASS

    def test_check_fn_returns_pass(self):
        def dummy_fn(rule, action, agent_id, target, territory):
            return CheckResult.PASS
        rule = RuleDescriptor(id="pass", section="§1", severity=RuleSeverity.MUST,
                              description="Always pass", check_fn=dummy_fn)
        assert rule.evaluate("write_file", "agent-a") == CheckResult.PASS

    def test_check_fn_returns_warn(self):
        def dummy_fn(rule, action, agent_id, target, territory):
            return CheckResult.WARN
        rule = RuleDescriptor(id="warn", section="§1", severity=RuleSeverity.SHOULD,
                              description="Always warn", check_fn=dummy_fn)
        assert rule.evaluate("run_in_terminal", "agent-a") == CheckResult.WARN

    def test_check_fn_returns_block(self):
        def dummy_fn(rule, action, agent_id, target, territory):
            return CheckResult.BLOCK
        rule = RuleDescriptor(id="block", section="§1", severity=RuleSeverity.MUST,
                              description="Always block", check_fn=dummy_fn)
        assert rule.evaluate("delete", "agent-a") == CheckResult.BLOCK

    def test_check_fn_returns_none_falls_to_pass(self):
        def dummy_fn(rule, action, agent_id, target, territory):
            return None
        rule = RuleDescriptor(id="none-fn", section="§1", severity=RuleSeverity.MUST,
                              description="None fn", check_fn=dummy_fn)
        assert rule.evaluate("read_file", "agent-a") == CheckResult.PASS

    def test_check_fn_receives_correct_arguments(self):
        captured = {}
        def spy_fn(rule, action, agent_id, target, territory):
            captured["rule"] = rule
            captured["action"] = action
            captured["agent_id"] = agent_id
            captured["target"] = target
            captured["territory"] = territory
            return CheckResult.PASS
        rule = RuleDescriptor(id="spy", section="§1", severity=RuleSeverity.MUST,
                              description="Spy", check_fn=spy_fn)
        rule.evaluate("grep", "agent-b", target="/src", territory=["/src", "/docs"])
        assert captured["rule"] is rule
        assert captured["action"] == "grep"
        assert captured["agent_id"] == "agent-b"
        assert captured["target"] == "/src"
        assert captured["territory"] == ["/src", "/docs"]

    def test_territory_defaults_to_empty_list(self):
        captured = {}
        def spy_fn(rule, action, agent_id, target, territory):
            captured["territory"] = territory
            return CheckResult.PASS
        rule = RuleDescriptor(id="territory-default", section="§1",
                              severity=RuleSeverity.MUST,
                              description="Territory default", check_fn=spy_fn)
        rule.evaluate("read_file", "agent-a")
        assert captured["territory"] == []


class TestRuleDescriptorToDict:
    def test_to_dict(self):
        rule = RuleDescriptor(id="dict.test", section="§5", severity=RuleSeverity.SHOULD,
                              description="Dict test", source="custom",
                              tags=frozenset({"a", "b"}))
        d = rule.to_dict()
        assert d["id"] == "dict.test"
        assert d["section"] == "§5"
        assert d["severity"] == "SHOULD"
        assert d["description"] == "Dict test"
        assert d["source"] == "custom"
        assert d["tags"] == ["a", "b"]

    def test_to_dict_no_tags(self):
        rule = RuleDescriptor(id="notags", section="§1", severity=RuleSeverity.MAY,
                              description="No tags")
        d = rule.to_dict()
        assert d["tags"] == []


class TestRuleDescriptorImmutability:
    def test_cannot_mutate_fields(self):
        rule = RuleDescriptor(id="immutable", section="§1", severity=RuleSeverity.MUST,
                              description="Immutable test")
        try:
            rule.id = "changed"
            assert False, "should have raised"
        except Exception:
            pass

    def test_tags_are_frozenset(self):
        rule = RuleDescriptor(id="frozen-tags", section="§1", severity=RuleSeverity.MUST,
                              description="Frozen tags", tags=frozenset({"x"}))
        assert isinstance(rule.tags, frozenset)
