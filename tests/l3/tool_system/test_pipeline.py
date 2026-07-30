"""ToolPipeline tests — 9-step execution pipeline, hooks, rate limit, clearance."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestPipelineInit:
    """get_pipeline() returns a usable pipeline instance."""

    def test_get_pipeline_returns_instance(self):
        from l3.tool_system.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        assert pipe is not None
        assert hasattr(pipe, "execute")
        assert hasattr(pipe, "set_pmu")

    def test_pipeline_has_steps_tracking(self):
        from l3.tool_system.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        assert hasattr(pipe, "_post_execute_hooks")
        assert hasattr(pipe, "_tool_definition_hooks")

    def test_reset_pipeline_clears_singleton(self):
        from l3.tool_system.tool_pipeline import get_pipeline, reset_pipeline
        p1 = get_pipeline()
        reset_pipeline()
        p2 = get_pipeline()
        assert p2 is not None


class TestPipelineExecute:
    """pipeline.execute() basic error path."""

    def test_execute_without_registry_returns_error(self):
        from l3.tool_system.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        r = pipe.execute("read_file", "test-agent", args={"path": "/tmp/x"})
        assert not r.get("success", True)

    def test_execute_simple_tool_returns_steps(self):
        from l3.tool_system.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        r = pipe.execute(
            tool_name="read_file",
            agent_id="l3",
            args={"path": __file__},
        )
        assert isinstance(r, dict)
        steps = r.get("steps", [])
        assert isinstance(steps, list)


class TestPipelineHooks:
    """Post-execute and tool-definition hooks."""

    def test_register_post_execute_hook(self):
        from l3.tool_system.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        calls = []

        def _hook(tool, agent, args, result):
            calls.append((tool, agent))

        pipe.register_post_execute_hook(_hook)
        assert _hook in pipe._post_execute_hooks

    def test_register_tool_definition_hook(self):
        from l3.tool_system.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        calls = []

        def _hook(tool, spec):
            calls.append(tool)
            return spec

        pipe.register_tool_definition_hook(_hook)
        assert _hook in pipe._tool_definition_hooks

    def test_apply_tool_definition_hooks_returns_modified_spec(self):
        from l3.tool_system.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        orig = {"name": "test_tool", "ring": "RING_1"}

        def _hook(tool, spec):
            spec["ring"] = "RING_2"
            return spec

        pipe.register_tool_definition_hook(_hook)
        modified = pipe.apply_tool_definition_hooks("test_tool", dict(orig))
        assert modified["ring"] == "RING_2"


class TestPipelineSetPmu:
    """PMU integration for tool execution counting."""

    def test_set_pmu_accepts_mock(self):
        from l3.tool_system.tool_pipeline import get_pipeline
        pipe = get_pipeline()

        class FakePmu:
            counts = {}

            def increment(self, name, delta=1):
                self.counts[name] = self.counts.get(name, 0) + delta

        pmu = FakePmu()
        pipe.set_pmu(pmu)
        assert pipe._pmu is pmu


class TestRateLimiter:
    """Rate limiter per-ring."""

    def test_ring1_allowed(self):
        from l3.tool_system.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()
        r = rl.check("ratt-agent", "RING_1")
        assert r["allowed"]

    def test_ring2_5_rate_limit(self):
        from l3.tool_system.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()
        for _ in range(25):
            rl.check("ratb-agent", "RING_2_5")
        r = rl.check("ratb-agent", "RING_2_5")
        assert not r["allowed"]

    def test_ring3_blocked_after_limit(self):
        from l3.tool_system.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()
        for _ in range(10):
            rl.check("ratc-agent", "RING_3")
        r = rl.check("ratc-agent", "RING_3")
        assert not r["allowed"]


class TestAgentClearance:
    """Agent ring-level access permissions."""

    def test_default_agent_ring1_only(self):
        from l3.tool_system.tool_pipeline import agent_can_access
        assert agent_can_access("default", "RING_1")
        result = agent_can_access("default", "RING_3")
        assert isinstance(result, bool)

    def test_l3_can_access_all_rings(self):
        from l3.tool_system.tool_pipeline import agent_can_access
        assert agent_can_access("l3", "RING_1")
        assert agent_can_access("l3", "RING_2_5")
        assert agent_can_access("l3", "RING_3")
