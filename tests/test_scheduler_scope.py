"""Tests for ScopeScheduler — step budget + scout quota."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_calc_step_budget():
    from l3.scheduler_scope import ScopeScheduler
    ss = ScopeScheduler()
    budget = ss.calc_step_budget(num_phases=2, total_steps=4)
    assert 10 <= budget <= 30
    assert budget == 5 + 3 * 2 + 2 * 4


def test_calc_step_budget_capped():
    from l3.scheduler_scope import ScopeScheduler
    ss = ScopeScheduler()
    budget = ss.calc_step_budget(num_phases=10, total_steps=50)
    assert budget == 30


def test_check_scout_quota():
    from l3.scheduler_scope import ScopeScheduler
    ss = ScopeScheduler()
    r = ss.check_scout_quota("test-agent")
    assert r.get("allowed")


def test_acquire_release_scout():
    from l3.scheduler_scope import ScopeScheduler
    ss = ScopeScheduler()
    ss.acquire_scout("busy-agent")
    r = ss.check_scout_quota("busy-agent")
    assert r.get("current") == 1
    ss.release_scout("busy-agent")
    r2 = ss.check_scout_quota("busy-agent")
    assert r2.get("current") == 0


def test_stats():
    from l3.scheduler_scope import ScopeScheduler
    ss = ScopeScheduler()
    s = ss.stats()
    assert "active_scouts" in s


def test_get_scheduler():
    from l3.scheduler_scope import get_scope_scheduler, reset_scope_scheduler
    reset_scope_scheduler()
    s1 = get_scope_scheduler()
    s2 = get_scope_scheduler()
    assert s1 is s2
