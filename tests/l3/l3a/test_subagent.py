"""Tests for L3A SubAgent pool — commission, collect, peek."""

from __future__ import annotations


class TestL3ASubAgentPool:
    def test_commission_unknown_spec(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        pool = L3ASubAgentPool(max_workers=2)
        r = pool.commission(spec="nonexistent", task="do something")
        assert r["success"] is False
        assert "unknown" in r["error"]

    def test_collect_unknown_group(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        pool = L3ASubAgentPool(max_workers=2)
        r = pool.collect(group="ghost")
        assert r["success"] is False
        assert "unknown group" in r["error"]

    def test_peek_unknown_task(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        pool = L3ASubAgentPool(max_workers=2)
        r = pool.peek(task_id="nonexistent")
        assert r["success"] is False

    def test_spawn_investigator(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        pool = L3ASubAgentPool(max_workers=2)
        r = pool.commission(spec="investigator", task="list files", group="g1")
        assert r["success"] is True
        assert r["spec"] == "investigator"
        assert r["group"] == "g1"

    def test_spawn_card_planner(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        pool = L3ASubAgentPool(max_workers=2)
        r = pool.commission(spec="card-planner", task="plan feature", group="g2")
        assert r["success"] is True
        assert r["spec"] == "card-planner"

    def test_pool_singleton(self):
        from l3.cell.peers.l3a.subagent import get_pool, reset_pool

        reset_pool()
        p1 = get_pool()
        p2 = get_pool()
        assert p1 is p2
        reset_pool()

    def test_extract_findings(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        spec = {"expect_keys": ["findings", "summary"]}
        result = L3ASubAgentPool._extract_findings("test task", '{"findings": ["ok"]}', spec)
        assert "findings" in result
        assert result["findings"] == ["ok"]

    def test_extract_findings_truncation(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        long_task = "x" * 500
        result = L3ASubAgentPool._extract_findings(long_task, "short answer", {})
        assert len(result["task"]) <= 210  # should be truncated to LOG_TRUNC_200

    def test_shutdown(self):
        from l3.cell.peers.l3a.subagent import L3ASubAgentPool

        pool = L3ASubAgentPool(max_workers=2)
        pool.shutdown(wait=True)
        # Should not raise
        assert True
