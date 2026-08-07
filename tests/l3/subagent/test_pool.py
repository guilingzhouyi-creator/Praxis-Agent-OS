"""Tests for subagent_pool.py — dual-buffer pool, commission, collect."""

from __future__ import annotations

from l3.agent.subagent_pool import SubAgentPool
from l3.agent.subagent_spec import SubAgentSpec


def test_pool_creation():
    """SubAgentPool creates with default worker counts."""
    p = SubAgentPool("test-cell")
    s = p.stats()
    assert s["explore_workers"] == 4
    assert s["execute_workers"] == 4
    assert s["total_commissioned"] == 0
    assert s["tracked"] == 0


def test_pool_commission_explore():
    """commission with card_type='explore' returns a task_id."""
    p = SubAgentPool("test-cell-2")
    spec = SubAgentSpec(name="test-explorer", description="Test explore", read_only=True)
    r = p.commission(spec, "test prompt", card_type="explore", parent_agent_id="agent-a")
    assert r["success"] is True
    assert r["buffer"] == "explore"
    assert "task_id" in r


def test_pool_commission_execute():
    """commission with card_type='execute' returns a task_id."""
    p = SubAgentPool("test-cell-3")
    spec = SubAgentSpec(name="test-executor", description="Test execute", read_only=False)
    r = p.commission(spec, "test execute", card_type="execute", parent_agent_id="agent-b")
    assert r["success"] is True
    assert r["buffer"] == "execute"
    assert "task_id" in r


def test_pool_collect_not_found():
    """collect returns error for unknown task_id."""
    p = SubAgentPool("test-cell-4")
    r = p.collect("nonexistent-task")
    assert r["success"] is False
    assert "not found" in r.get("error", "")


def test_pool_stats_after_commission():
    """stats reflect commissioned tasks."""
    p = SubAgentPool("test-cell-5")
    spec = SubAgentSpec(name="stats-test", description="Stats test", read_only=True)
    p.commission(spec, "stats test", card_type="explore", parent_agent_id="agent-c")
    s = p.stats()
    assert s["total_commissioned"] == 1
    assert s["tracked"] == 1


def test_pool_stats_includes_worker_counts():
    """stats includes explore_workers and execute_workers."""
    p = SubAgentPool("test-cell-6", config={"explore_workers": 2, "execute_workers": 6})
    s = p.stats()
    assert s["explore_workers"] == 2
    assert s["execute_workers"] == 6
