"""ToolPipeline tests — clearance, rate limit, constitution, alloc, lock, execute."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestToolRateLimiter:
    def test_ring1_allowed(self):
        from services.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()
        r = rl.check("test-agent", "RING_1")
        assert r["allowed"]

    def test_ring3_rate_limit(self):
        from services.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()
        for _ in range(10):
            rl.check("heavy-agent", "RING_3")
        r = rl.check("heavy-agent", "RING_3")
        assert not r["allowed"]

    def test_per_agent_isolation(self):
        from services.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()
        for _ in range(10):
            rl.check("hog", "RING_1")
        r = rl.check("other", "RING_1")
        assert r["allowed"]

    def test_reset_after_window(self):
        from services.tool_pipeline import get_rate_scheduler
        import time as _t
        rl = get_rate_scheduler()
        for _ in range(5):
            rl.check("reset-agent", "RING_3")
        r = rl.check("reset-agent", "RING_3")
        assert not r["allowed"]
        key = "reset-agent:RING_3"
        rl._counters[key] = [_t.time() - 120]
        r2 = rl.check("reset-agent", "RING_3")
        assert r2["allowed"]


class TestAgentCanAccess:
    def test_ring1_default(self):
        from services.tool_pipeline import agent_can_access
        assert agent_can_access("unknown", "RING_1")

    def test_ring3_blocked(self):
        from services.tool_pipeline import agent_can_access
        # default agent has ring 1 clearance
        from kernel.params.agent import AGENT_CLEARANCE
        assert AGENT_CLEARANCE.get("default", 1) == 1
        assert not agent_can_access("default", "RING_3")

    def test_l3_can_access_ring3(self):
        from services.tool_pipeline import agent_can_access
        assert agent_can_access("l3", "RING_3")
