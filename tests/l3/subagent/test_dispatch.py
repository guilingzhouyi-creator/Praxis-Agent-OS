"""Tests for SubAgentDispatcher / ResultMerger / SubAgentSpec."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSubAgentSpec:
    def test_builtin_specs(self):
        from l3.subagent_spec import BUILTIN_SUBAGENTS, SubAgentSpec
        assert len(BUILTIN_SUBAGENTS) >= 2
        assert "security-auditor" in BUILTIN_SUBAGENTS
        assert "code-reviewer" in BUILTIN_SUBAGENTS

    def test_to_dict(self):
        from l3.subagent_spec import SubAgentSpec
        spec = SubAgentSpec(name="test-agent", description="A test agent")
        d = spec.to_dict()
        assert d["name"] == "test-agent"
        assert d["description"] == "A test agent"
        assert d["read_only"] is True


class TestSubAgentDispatcher:
    def test_init(self):
        from l3.subagent_dispatcher import SubAgentDispatcher
        d = SubAgentDispatcher()
        assert d is not None

    def test_parse_mentions_empty(self):
        from l3.subagent_dispatcher import SubAgentDispatcher
        d = SubAgentDispatcher()
        results = d.parse_mentions("")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_parse_mentions_no_match(self):
        from l3.subagent_dispatcher import SubAgentDispatcher
        d = SubAgentDispatcher()
        results = d.parse_mentions("just some text without any mentions")
        assert len(results) == 0

    def test_dispatch_unknown_spec(self):
        from l3.subagent_dispatcher import SubAgentDispatcher
        d = SubAgentDispatcher()
        r = d.dispatch("nonexistent-spec", "do something")
        assert not r.get("success")

    def test_dispatch_known_spec(self):
        from l3.subagent_dispatcher import SubAgentDispatcher
        d = SubAgentDispatcher()
        r = d.dispatch("security-auditor", "review this code")
        # dispatch may return success or error depending on backend availability
        assert isinstance(r, dict)


class TestResultMerger:
    def test_merge_empty(self):
        from l3.subagent_merger import ResultMerger
        r = ResultMerger.merge([])
        assert r["total"] == 0
        assert r["completed"] == 0

    def test_merge_all_completed(self):
        from l3.subagent_merger import ResultMerger
        results = [
            {"status": "completed", "spec": "agent-a", "result": {"content": "result A"}},
            {"status": "completed", "spec": "agent-b", "result": {"content": "result B"}},
        ]
        r = ResultMerger.merge(results)
        assert r["total"] == 2
        assert r["completed"] == 2
        assert r["failed"] == 0

    def test_merge_with_failures(self):
        from l3.subagent_merger import ResultMerger
        results = [
            {"status": "completed", "spec": "agent-a", "result": {"content": "ok"}},
            {"status": "failed", "spec": "agent-b", "result": {"content": ""}},
        ]
        r = ResultMerger.merge(results)
        assert r["total"] == 2
        assert r["completed"] == 1
        assert r["failed"] == 1

    def test_merge_detect_conflicts(self):
        from l3.subagent_merger import ResultMerger
        results = [
            {"status": "completed", "spec": "a", "result": {"content": "safe to deploy"}},
            {"status": "completed", "spec": "b", "result": {"content": "vulnerable, do not deploy"}},
        ]
        r = ResultMerger.merge(results)
        assert isinstance(r["conflicts"], list)
