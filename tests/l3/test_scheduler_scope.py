"""Tests for l3.scheduler.scheduler_scope — ScopeScheduler step budget + scout quota."""

from __future__ import annotations


class TestScopeSchedulerStepBudget:
    """ScopeScheduler.calc_step_budget — 动态步数预算计算。"""

    def _make(self):
        from l3.scheduler.scheduler_scope import ScopeScheduler
        return ScopeScheduler()

    def test_budget_simple(self):
        """1 phase, 1 step → 5+3+2=10。"""
        s = self._make()
        b = s.calc_step_budget(1, 1)
        assert b == 10

    def test_budget_multi_phase(self):
        """3 phases, 5 steps → 5+9+10=24。"""
        s = self._make()
        b = s.calc_step_budget(3, 5)
        assert b == 24

    def test_budget_capped(self):
        """大量 phases/steps 应被 cap 限制在 30。"""
        s = self._make()
        b = s.calc_step_budget(10, 50)
        assert b == 30

    def test_budget_zero_steps(self):
        """0 phase, 0 steps → 5。"""
        s = self._make()
        b = s.calc_step_budget(0, 0)
        assert b == 5

    def test_default_max_steps(self):
        """default_max_steps 应返回 AGENT_LOOP_DEFAULT_STEPS。"""
        s = self._make()
        from l1.kernel.params.agent import AGENT_LOOP_DEFAULT_STEPS
        assert s.default_max_steps() == AGENT_LOOP_DEFAULT_STEPS


class TestScopeSchedulerScoutQuota:
    """ScopeScheduler 侦察配额管理。"""

    def _make(self):
        from l3.scheduler.scheduler_scope import ScopeScheduler
        return ScopeScheduler()

    def test_check_empty_quota(self):
        """新 agent 的侦察配额应可用。"""
        s = self._make()
        r = s.check_scout_quota("agent-a")
        assert r["allowed"] is True
        assert r["current"] == 0

    def test_acquire_increases_count(self):
        """acquire_scout 应递增计数。"""
        s = self._make()
        r1 = s.acquire_scout("agent-a")
        assert r1["allowed"]
        r2 = s.check_scout_quota("agent-a")
        assert r2["current"] == 1

    def test_release_decreases_count(self):
        """release_scout 应递减计数。"""
        s = self._make()
        s.acquire_scout("agent-a")
        s.acquire_scout("agent-a")
        s.release_scout("agent-a")
        r = s.check_scout_quota("agent-a")
        assert r["current"] == 1

    def test_release_below_zero(self):
        """release 到 0 以下应钳位为 0。"""
        s = self._make()
        s.release_scout("agent-a")
        r = s.check_scout_quota("agent-a")
        assert r["current"] == 0

    def test_reset_agent(self):
        """reset_agent 应清除计数。"""
        s = self._make()
        s.acquire_scout("agent-a")
        s.reset_agent("agent-a")
        r = s.check_scout_quota("agent-a")
        assert r["current"] == 0

    def test_multi_agent_independence(self):
        """不同 agent 的计数应独立。"""
        s = self._make()
        s.acquire_scout("agent-a")
        s.acquire_scout("agent-a")
        s.acquire_scout("agent-b")
        ra = s.check_scout_quota("agent-a")
        rb = s.check_scout_quota("agent-b")
        assert ra["current"] == 2
        assert rb["current"] == 1

    def test_stats(self):
        """stats 应返回正确的汇总。"""
        s = self._make()
        s.acquire_scout("agent-a")
        s.acquire_scout("agent-b")
        s.acquire_scout("agent-b")
        st = s.stats()
        assert st["active_scouts"] == 3
        assert st["agents"] == 2


class TestScopeSchedulerSingleton:
    """get_scope_scheduler() 单例模式。"""

    def test_singleton(self):
        from l3.scheduler.scheduler_scope import get_scope_scheduler, reset_scope_scheduler
        reset_scope_scheduler()
        s1 = get_scope_scheduler()
        s2 = get_scope_scheduler()
        assert s1 is s2

    def test_reset(self):
        from l3.scheduler.scheduler_scope import get_scope_scheduler, reset_scope_scheduler
        reset_scope_scheduler()
        s1 = get_scope_scheduler()
        reset_scope_scheduler()
        s2 = get_scope_scheduler()
        assert s1 is not s2
