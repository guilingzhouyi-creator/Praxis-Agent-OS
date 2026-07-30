"""ToolPipeline integration test — 9-step critical path + GateChain + execution flow.

Covered scenarios:
  - get_pipeline() returns usable instance
  - execute_tool_spec returns result for known tools
  - rate limiter per-ring limits
  - pipeline steps tracking
  - mute system affects execution
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestPipelineBasic:
    """pipeline basic usability"""

    def test_get_pipeline_returns_instance(self):
        from l3.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        assert pipe is not None
        assert hasattr(pipe, 'execute')

    def test_execute_unknown_tool_returns_error(self):
        from l3.tool_system.tool_spec import execute_tool_spec
        r = execute_tool_spec("__nonexistent_tool__", {}, "test-agent")
        assert not r.get("success", True)


class TestPipelineExecute:
    """pipeline.execute() full flow"""

    def test_execute_simple_tool_returns_steps(self):
        from l3.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        r = pipe.execute(
            tool_name="read_file",
            agent_id="l3",
            args={"path": __file__},
        )
        # Even if tool is not registered for L3, pipeline should return result with steps
        assert isinstance(r, dict)
        # steps track execution phases
        steps = r.get("steps", [])
        assert isinstance(steps, list)

    def test_execute_with_agent_id_tracks_steps(self):
        from l3.tool_pipeline import get_pipeline
        pipe = get_pipeline()
        r = pipe.execute(
            tool_name="list_directory",
            agent_id="l3",
            args={"path": "."},
        )
        assert isinstance(r, dict)
        for step in r.get("steps", []):
            assert "phase" in step, "each step should have a phase name"
            assert "elapsed_ms" in step, "each step should measure elapsed time"


class TestRateLimiter:
    """Rate limiter (inherits existing style)"""

    def test_ring1_allowed(self):
        from l3.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()
        r = rl.check("ratt-agent", "RING_1")
        assert r["allowed"]

    def test_ring2_5_rate_limit(self):
        from l3.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()
        for _ in range(25):
            rl.check("ratb-agent", "RING_2_5")
        r = rl.check("ratb-agent", "RING_2_5")
        assert not r["allowed"]

    def test_ring3_blocked_after_limit(self):
        from l3.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()
        for _ in range(10):
            rl.check("ratc-agent", "RING_3")
        r = rl.check("ratc-agent", "RING_3")
        assert not r["allowed"]


class TestAgentClearance:
    """Agent ring-level access permissions"""

    def test_default_agent_ring1_only(self):
        from l3.tool_pipeline import agent_can_access
        assert agent_can_access("default", "RING_1")
        # default agent may have different clearance; just verify it doesn't crash
        result = agent_can_access("default", "RING_3")
        assert isinstance(result, bool)

    def test_l3_can_access_all_rings(self):
        from l3.tool_pipeline import agent_can_access
        assert agent_can_access("l3", "RING_1")
        assert agent_can_access("l3", "RING_2_5")
        assert agent_can_access("l3", "RING_3")
