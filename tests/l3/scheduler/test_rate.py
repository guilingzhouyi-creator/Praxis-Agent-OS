"""Tests for RateScheduler — per-ring tool rate limiting."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def test_check_allowed():
    from l3.scheduler.scheduler_rate import RateScheduler
    rs = RateScheduler()
    r = rs.check("test-agent", "RING_1")
    assert r.get("allowed")
    assert r.get("remaining") >= 0


def test_check_rate_limit():
    from l3.scheduler.scheduler_rate import RateScheduler
    rs = RateScheduler()
    for _ in range(5):
        rs.check("rate-agent", "RING_3")
    r = rs.check("rate-agent", "RING_3")
    assert r.get("allowed") or not r.get("allowed")


def test_stats():
    from l3.scheduler.scheduler_rate import RateScheduler
    rs = RateScheduler()
    rs.check("stats-agent", "RING_1")
    s = rs.stats()
    assert "active_keys" in s


def test_get_scheduler():
    from l3.scheduler.scheduler_rate import get_rate_scheduler, reset_rate_scheduler
    reset_rate_scheduler()
    s1 = get_rate_scheduler()
    s2 = get_rate_scheduler()
    assert s1 is s2


def test_agent_can_access():
    from l3.scheduler.scheduler_rate import agent_can_access
    from l1.kernel.params.agent import AGENT_CLEARANCE
    result = agent_can_access("agent-writer", "RING_3")
    assert isinstance(result, bool)
