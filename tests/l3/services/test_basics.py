"""Services core module tests — todo, stagnation, pal_router, tool_spec."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestTodoTable:
    def test_add_and_next(self):
        from l3.services.todo import TodoStatus, TodoTable
        t = TodoTable("test-agent")
        tid = t.add("do something", priority=3)
        assert tid.startswith("test-agent-")
        item = t.next()
        assert item is not None
        assert item.intent == "do something"
        assert item.priority == 3
        # next() sets to IN_PROGRESS
        assert item.status == TodoStatus.IN_PROGRESS

    def test_priority_ordering(self):
        from l3.services.todo import TodoTable
        t = TodoTable("p-agent")
        t.add("low", priority=10)
        t.add("high", priority=1)
        t.add("medium", priority=5)
        assert t.next().intent == "high"
        assert t.next().intent == "medium"
        assert t.next().intent == "low"

    def test_dependencies(self):
        from l3.services.todo import TodoStatus, TodoTable
        t = TodoTable("dep-agent")
        a = t.add("task A")
        b = t.add("task B", depends_on=[a])
        assert t.next().id == a  # A pops first
        t.update(a, status=TodoStatus.DONE, result={"ok": True})
        assert t.next().id == b  # B now unblocked

    def test_blocked_by_missing_dep(self):
        from l3.services.todo import TodoTable
        t = TodoTable("block-agent")
        t.add("orphan", depends_on=["nonexistent"])
        assert t.next() is None

    def test_cancel(self):
        from l3.services.todo import TodoTable
        t = TodoTable("c-agent")
        tid = t.add("cancel me")
        assert t.cancel(tid)
        assert t.next() is None

    def test_list_and_stats(self):
        from l3.services.todo import TodoTable
        t = TodoTable("stat-agent")
        t.add("a", priority=1)
        t.add("b", priority=5)
        t.add("c", priority=10)
        items = t.list()
        assert len(items) >= 3
        stats = t.stats()
        assert stats["total"] >= 3
        assert stats["by_status"].get("PENDING", 0) >= 3


class TestStagnationDetector:
    def test_no_stagnation(self):
        from l3.agent.stagnation import StagnationDetector
        sd = StagnationDetector()
        assert not sd.check("fresh-agent").get("stagnant")

    def test_spinning_detection(self):
        from l3.agent.stagnation import StagnationDetector
        sd = StagnationDetector()
        for _ in range(5):
            sd.record("spinner", "same output", progress=0.5)
        r = sd.check("spinner")
        assert r.get("stagnant")
        assert r.get("pattern") == "SPINNING"

    def test_oscillation_detection(self):
        from l3.agent.stagnation import StagnationDetector
        sd = StagnationDetector()
        for o in ["version A", "version B"] * 4:
            sd.record("oscillator", o, progress=0.5)
        r = sd.check("oscillator")
        assert r.get("stagnant")
        assert r.get("pattern") == "OSCILLATION"

    def test_no_drift_detection(self):
        from l3.agent.stagnation import StagnationDetector
        sd = StagnationDetector()
        # Different content each time so SPINNING doesn't fire before NO_DRIFT
        for i in range(5):
            sd.record("driftless", f"iteration {i} content", progress=0.5)
        r = sd.check("driftless")
        assert r.get("stagnant")
        assert r.get("pattern") == "NO_DRIFT"

    def test_diminishing_returns(self):
        from l3.agent.stagnation import StagnationDetector
        sd = StagnationDetector()
        # deltas: 0.008, 0.006, 0.004 — all >= 0 and all < 0.01
        # spread: max-min = 0.018 >= 0.01, so NO_DRIFT won't fire first
        sd.record("diminisher", "a", progress=0.5)
        sd.record("diminisher", "b", progress=0.508)
        sd.record("diminisher", "c", progress=0.514)
        sd.record("diminisher", "d", progress=0.518)
        r = sd.check("diminisher")
        assert r.get("stagnant"), f"DIMINISHING_RETURNS not detected: {r}"
        assert r.get("pattern") == "DIMINISHING_RETURNS"


class TestPALRouter:
    def test_select_default_tier(self):
        from l3.agent.pal_router import PALRouter
        router = PALRouter()
        assert router.select("simple task") in ("frugal", "standard", "frontier")

    def test_select_prefer_tier(self):
        from l3.agent.pal_router import PALRouter
        assert PALRouter().select("critical", prefer_tier="frontier") == "frontier"

    def test_complexity_scoring(self):
        from l3.agent.pal_router import complexity_score
        s1 = complexity_score(tokens=100, tools=1, depth=1)
        s2 = complexity_score(tokens=10000, tools=20, depth=10)
        assert s1 < s2
        assert 0 <= s1 <= 1
        assert 0 <= s2 <= 1

    def test_stats_structure(self):
        from l3.agent.pal_router import PALRouter
        router = PALRouter()
        router.select("stats test")
        stats = router.stats()
        assert "total_calls" in stats
        assert "tier_distribution" in stats


class TestToolSpec:
    def test_param_validation_required(self):
        from l3.tool_system.tool_spec import ParamSpec
        p = ParamSpec(name="path", type="string", required=True)
        assert p.validate("/valid/path") is None
        # None for required param: falls through type check, str(None) != "string"

    def test_param_validation_optional(self):
        from l3.tool_system.tool_spec import ParamSpec
        p = ParamSpec(name="count", type="int", required=False, default=5)
        assert p.validate(None) is None
        assert p.validate(3) is None

    def test_param_validation_type_mismatch(self):
        from l3.tool_system.tool_spec import ParamSpec
        p = ParamSpec(name="count", type="int")
        assert p.validate("bad") is not None  # string not int

    def test_tool_spec_gates(self):
        from l3.tool_system.tool_spec import ToolRing, ToolSpec
        t1 = ToolSpec(name="r1", description="", category="t", ring=ToolRing.RING_1, danger=0)
        assert t1.gates == ["G1", "G2"]
        t2 = ToolSpec(name="r25", description="", category="t", ring=ToolRing.RING_2_5, danger=1)
        assert "G3" in t2.gates
        t3 = ToolSpec(name="r3", description="", category="t", ring=ToolRing.RING_3, danger=3)
        assert "G5" in t3.gates

    def test_register_and_get(self):
        from l3.tool_system.tool_spec import TOOL_REGISTRY, ToolSpec, get_tool, register
        saved = TOOL_REGISTRY.copy()
        TOOL_REGISTRY.clear()
        register(ToolSpec(name="t1", description="", category="g", ring="ring_1", danger=0))
        assert get_tool("t1") is not None
        assert get_tool("nonexistent") is None
        TOOL_REGISTRY.update(saved)

    def test_list_by_category(self):
        from l3.tool_system.tool_spec import TOOL_REGISTRY, ToolSpec, list_tools, register
        saved = TOOL_REGISTRY.copy()
        TOOL_REGISTRY.clear()
        register(ToolSpec(name="a", description="", category="alpha", ring="ring_1", danger=0))
        register(ToolSpec(name="b", description="", category="beta", ring="ring_1", danger=0))
        assert len(list_tools(category="alpha")) == 1
        assert len(list_tools()) >= 2
        TOOL_REGISTRY.update(saved)
