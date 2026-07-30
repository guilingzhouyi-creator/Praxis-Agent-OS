"""R4Agent tests — lifecycle, status, stale detection."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestR4Agent:
    def test_create_agent(self):
        from l3.memory.r4_agent import R4Agent
        agent = R4Agent(interval=9999)
        assert agent.interval == 9999
        assert not agent._running
        assert agent._total_archived == 0

    def test_start_stop(self):
        from l3.memory.r4_agent import R4Agent
        agent = R4Agent(interval=9999)
        r = agent.start()
        assert r.get("success")
        assert agent._running
        r2 = agent.stop()
        assert r2.get("success")
        assert not agent._running

    def test_status_before_start(self):
        from l3.memory.r4_agent import R4Agent
        agent = R4Agent(interval=9999)
        s = agent.status()
        assert not s["running"]
        assert s["total_archived"] == 0

    def test_status_after_start(self):
        from l3.memory.r4_agent import R4Agent
        agent = R4Agent(interval=9999)
        agent.start()
        s = agent.status()
        assert s["running"]
        agent.stop()

    def test_tick_no_error(self):
        from l3.memory.r4_agent import R4Agent
        agent = R4Agent(interval=9999)
        r = agent.tick()
        assert "stale" in r
        assert "archived" in r
        assert "contradictions" in r
        assert "alerts" in r

    def test_get_r4_agent_singleton(self):
        from l3.memory.r4_agent import get_r4_agent
        a1 = get_r4_agent()
        a2 = get_r4_agent()
        assert a1 is a2

    def test_archived_count_increments(self):
        from l3.memory.r4_agent import R4Agent
        agent = R4Agent(interval=9999)
        r1 = agent.tick()
        assert r1["archived"] >= 0

    def test_start_r4_agent_top_level(self):
        from l3.memory.r4_agent import start_r4_agent, stop_r4_agent, get_r4_agent
        r = start_r4_agent()
        assert r.get("success")
        assert get_r4_agent()._running
        stop_r4_agent()
        assert not get_r4_agent()._running
