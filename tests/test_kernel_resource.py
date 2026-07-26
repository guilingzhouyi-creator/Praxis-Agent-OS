"""Resource-limiter tests — profiles, limits, check/release, usage, edge cases."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestResourceLimiterConstruction:
    """Construction and singleton access."""

    def test_limiter_created(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        assert lim is not None
        assert hasattr(lim, "_profiles")
        assert hasattr(lim, "_usage")

    def test_limiter_has_default_profiles(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        assert "default" in lim._profiles
        assert "scout" in lim._profiles
        assert "l3" in lim._profiles
        assert "human" in lim._profiles

    def test_get_limiter_singleton(self):
        from kernel.resource import get_limiter, reset_limiter
        reset_limiter()
        l1 = get_limiter()
        l2 = get_limiter()
        assert l1 is l2

    def test_reset_limiter(self):
        from kernel.resource import get_limiter, reset_limiter
        reset_limiter()
        l1 = get_limiter()
        reset_limiter()
        l2 = get_limiter()
        assert l1 is not l2


class TestGetProfile:
    """get_profile normal paths and edge cases."""

    def test_get_profile_default(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        p = lim.get_profile("default")
        assert isinstance(p, dict)
        assert p["max_tokens"] == 4096
        assert p["max_workers"] == 4
        assert p["max_scouts"] == 3
        assert p["max_memory"] == 100
        assert p["priority"] == 5

    def test_get_profile_scout(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        p = lim.get_profile("scout")
        assert p["max_tokens"] == 2048
        assert p["max_workers"] == 1
        assert p["max_scouts"] == 0

    def test_get_profile_l3(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        p = lim.get_profile("l3")
        assert p["max_tokens"] == 2048
        assert p["max_workers"] == 2
        assert p["priority"] == 1

    def test_get_profile_human(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        p = lim.get_profile("human")
        assert p["max_tokens"] == 0
        assert p["max_workers"] == 0
        assert p["max_scouts"] == 0
        assert p["priority"] == 0

    def test_get_profile_unknown_agent_falls_back_to_default(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        p = lim.get_profile("nonexistent-agent")
        assert p["max_tokens"] == 4096
        assert p["priority"] == 5

    def test_get_profile_isolation(self):
        """Returned dict is a fresh copy, not a reference to internal state."""
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        p1 = lim.get_profile("default")
        p2 = lim.get_profile("default")
        assert p1 == p2
        # Mutating one should not affect the other
        p1["max_tokens"] = 9999
        assert lim.get_profile("default")["max_tokens"] == 4096


class TestSetProfile:
    """set_profile — custom profiles per agent."""

    def test_set_profile_creates_new_agent(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.set_profile("custom-agent", max_tokens=8192, max_workers=8)
        assert result == {"success": True}
        p = lim.get_profile("custom-agent")
        assert p["max_tokens"] == 8192
        assert p["max_workers"] == 8

    def test_set_profile_overwrites_field(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("overwrite-agent", max_tokens=8192)
        p = lim.get_profile("overwrite-agent")
        assert p["max_tokens"] == 8192
        # other fields unchanged (defaults from ResourceProfile())
        assert p["max_workers"] == 4
        assert p["max_memory"] == 100

    def test_set_profile_partial_update(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("agent-x", priority=1)
        p = lim.get_profile("agent-x")
        assert p["priority"] == 1
        assert p["max_tokens"] == 4096  # default
        assert p["max_workers"] == 4
        assert p["max_scouts"] == 3
        assert p["max_memory"] == 100

    def test_set_profile_ignores_invalid_field(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        # kwargs that don't exist on ResourceProfile are silently ignored
        result = lim.set_profile("default", nonexistent=999)
        assert result == {"success": True}
        # profile unchanged
        p = lim.get_profile("default")
        assert p["max_tokens"] == 4096

    def test_set_profile_multiple_calls_accumulate(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("multi", max_tokens=2000)
        lim.set_profile("multi", max_workers=6)
        lim.set_profile("multi", priority=2)
        p = lim.get_profile("multi")
        assert p["max_tokens"] == 2000
        assert p["max_workers"] == 6
        assert p["priority"] == 2
        assert p["max_scouts"] == 3  # default untouched


class TestCheck:
    """check — resource consumption accounting."""

    def test_check_tokens_success(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.check("default", "tokens", cost=100)
        assert result["success"] is True
        assert result["current"] == 100
        assert result["limit"] == 4096

    def test_check_workers_success(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.check("default", "workers", cost=1)
        assert result["success"] is True
        assert result["current"] == 1
        assert result["limit"] == 4

    def test_check_scouts_success(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.check("default", "scouts", cost=1)
        assert result["success"] is True
        assert result["current"] == 1
        assert result["limit"] == 3

    def test_check_memory_success(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.check("default", "memory", cost=10)
        assert result["success"] is True
        assert result["current"] == 10
        assert result["limit"] == 100

    def test_check_exceeds_limit(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        # Use a limiter with a known small profile
        lim.set_profile("limited", max_workers=2)
        result = lim.check("limited", "workers", cost=3)
        assert result["success"] is False
        assert "exceeded" in result["error"]
        assert result["current"] == 0
        assert result["limit"] == 2
        assert result["requested"] == 3

    def test_check_accumulates_cost(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.check("acc", "workers", cost=1)
        lim.check("acc", "workers", cost=1)
        result = lim.check("acc", "workers", cost=1)
        assert result["success"] is True
        assert result["current"] == 3
        assert result["limit"] == 4

    def test_check_exceeds_on_accumulation(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("tight", max_workers=2)
        lim.check("tight", "workers", cost=1)
        lim.check("tight", "workers", cost=1)
        result = lim.check("tight", "workers", cost=1)
        assert result["success"] is False
        assert result["current"] == 2
        assert result["limit"] == 2

    def test_check_unknown_resource(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.check("default", "cpu", cost=1)
        assert result["success"] is False
        assert "unknown resource" in result["error"]

    def test_check_unknown_agent_uses_fallback(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.check("ghost", "tokens", cost=100)
        assert result["success"] is True
        assert result["limit"] == 4096

    def test_check_zero_cost(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.check("default", "tokens", cost=0)
        assert result["success"] is True
        assert result["current"] == 0

    def test_check_exact_limit(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("exact", max_workers=3)
        result = lim.check("exact", "workers", cost=3)
        assert result["success"] is True
        assert result["current"] == 3
        assert result["limit"] == 3

    def test_check_isolation_between_agents(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.check("agent-a", "workers", cost=4)
        result_b = lim.check("agent-b", "workers", cost=4)
        assert result_b["success"] is True
        assert result_b["current"] == 4
        result_a = lim.check("agent-a", "workers", cost=1)
        assert result_a["success"] is False  # agent-a exhausted

    def test_check_isolation_between_resources(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.check("iso", "workers", cost=4)
        result = lim.check("iso", "tokens", cost=100)
        assert result["success"] is True  # tokens are separate pool


class TestRelease:
    """release — decrement usage counters."""

    def test_release_decrements(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.check("rel", "workers", cost=3)
        result = lim.release("rel", "workers", cost=1)
        assert result["success"] is True
        assert result["current"] == 2

    def test_release_below_zero_clamps(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.release("rel", "workers", cost=10)
        assert result["success"] is True
        assert result["current"] == 0

    def test_release_on_unused_agent(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.release("fresh-agent", "workers", cost=1)
        assert result["success"] is True
        assert result["current"] == 0

    def test_release_on_unchecked_agent(self):
        """release on an agent that has never called check still works."""
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.release("never-checked", "scouts", cost=5)
        assert result["success"] is True
        assert result["current"] == 0

    def test_release_allows_recheck(self):
        """After releasing, the same resource can be consumed again."""
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("cyclic", max_workers=2)
        lim.check("cyclic", "workers", cost=2)
        assert lim.check("cyclic", "workers", cost=1)["success"] is False
        lim.release("cyclic", "workers", cost=2)
        result = lim.check("cyclic", "workers", cost=2)
        assert result["success"] is True
        assert result["current"] == 2

    def test_release_partial(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.check("part", "tokens", cost=100)
        lim.release("part", "tokens", cost=30)
        u = lim.usage("part")
        assert u["tokens"]["current"] == 70


class TestUsage:
    """usage and all_usage reporting."""

    def test_usage_empty_agent(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        u = lim.usage("nobody")
        assert u["workers"]["current"] == 0
        assert u["workers"]["max"] == 4  # falls back to default
        assert u["scouts"]["current"] == 0
        assert u["memory"]["current"] == 0
        assert u["tokens"]["current"] == 0

    def test_usage_after_checks(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.check("busy", "workers", cost=2)
        lim.check("busy", "tokens", cost=500)
        u = lim.usage("busy")
        assert u["workers"]["current"] == 2
        assert u["workers"]["max"] == 4
        assert u["tokens"]["current"] == 500
        assert u["tokens"]["max"] == 4096
        assert u["memory"]["current"] == 0

    def test_usage_after_release(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.check("releaser", "scouts", cost=2)
        lim.release("releaser", "scouts", cost=1)
        u = lim.usage("releaser")
        assert u["scouts"]["current"] == 1

    def test_usage_custom_agent(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("big-agent", max_workers=16, max_tokens=32000, max_memory=500)
        lim.check("big-agent", "workers", cost=4)
        u = lim.usage("big-agent")
        assert u["workers"]["max"] == 16
        assert u["tokens"]["max"] == 32000
        assert u["memory"]["max"] == 500

    def test_all_usage_returns_all_profiles(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        all_u = lim.all_usage()
        assert "default" in all_u
        assert "scout" in all_u
        assert "l3" in all_u
        assert "human" in all_u

    def test_all_usage_includes_custom(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("custom", max_tokens=999)
        all_u = lim.all_usage()
        assert "custom" in all_u
        assert all_u["custom"]["tokens"]["max"] == 999

    def test_all_usage_values_are_dicts(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        all_u = lim.all_usage()
        for _aid, metrics in all_u.items():
            assert isinstance(metrics, dict)
            for key in ("workers", "scouts", "memory", "tokens"):
                assert key in metrics
                assert "current" in metrics[key]
                assert "max" in metrics[key]

    def test_all_usage_shows_consumption(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.check("default", "tokens", cost=100)
        lim.check("default", "workers", cost=2)
        all_u = lim.all_usage()
        assert all_u["default"]["tokens"]["current"] == 100
        assert all_u["default"]["workers"]["current"] == 2

    def test_usage_round_trip(self):
        """Full cycle: check, usage, release, usage."""
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("cycle-agent", max_workers=5, max_tokens=8000)
        lim.check("cycle-agent", "workers", cost=1)
        lim.check("cycle-agent", "tokens", cost=2000)
        u_before = lim.usage("cycle-agent")
        assert u_before["workers"]["current"] == 1
        assert u_before["tokens"]["current"] == 2000
        lim.release("cycle-agent", "workers", cost=1)
        lim.release("cycle-agent", "tokens", cost=500)
        u_after = lim.usage("cycle-agent")
        assert u_after["workers"]["current"] == 0
        assert u_after["tokens"]["current"] == 1500


class TestConcurrency:
    """Basic thread-safety smoke tests."""

    def test_concurrent_checks(self):
        import threading

        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("concurrent", max_workers=4)
        errors = []

        def worker():
            for _ in range(10):
                try:
                    lim.check("concurrent", "workers", cost=1)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        assert not errors, f"Concurrent access raised errors: {errors}"

    def test_concurrent_check_and_release(self):
        import threading

        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("cr", max_workers=4)
        errors = []

        def hammer():
            for _ in range(20):
                try:
                    lim.check("cr", "workers", cost=1)
                    lim.release("cr", "workers", cost=1)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=hammer, daemon=True) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        assert not errors, f"Concurrent check/release raised errors: {errors}"


class TestEdgeCases:
    """Edge cases and defensive behaviours."""

    def test_negative_cost_in_check(self):
        """Negative cost reduces usage (acts like a partial release)."""
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("neg", max_workers=10)
        lim.check("neg", "workers", cost=5)
        result = lim.check("neg", "workers", cost=-2)
        assert result["success"] is True
        assert result["current"] == 3

    def test_large_cost_value(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.check("default", "tokens", cost=10_000_000)
        assert result["success"] is False
        assert "exceeded" in result["error"]

    def test_set_profile_empty_kwargs(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.set_profile("empty-kwargs")
        assert result == {"success": True}

    def test_profile_for_human_has_zero_limits(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        p = lim.get_profile("human")
        assert p["max_tokens"] == 0
        assert p["max_workers"] == 0
        assert p["max_scouts"] == 0
        assert p["max_memory"] == 100
        # check should always fail
        result = lim.check("human", "tokens", cost=1)
        assert result["success"] is False

    def test_release_unknown_resource_key(self):
        """Release on a resource key never checked before works."""
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        result = lim.release("any", "memory", cost=5)
        assert result["success"] is True
        assert result["current"] == 0

    def test_usage_on_custom_profile_without_usage(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("inactive", max_workers=10)
        u = lim.usage("inactive")
        assert u["workers"]["max"] == 10
        assert u["workers"]["current"] == 0

    def test_set_profile_updates_all_usage(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("default", max_workers=10)
        all_u = lim.all_usage()
        assert all_u["default"]["workers"]["max"] == 10

    def test_release_thrice_underflow(self):
        """Release more than checked multiple times still clamps at zero."""
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.release("under", "workers", cost=1)
        lim.release("under", "workers", cost=5)
        lim.release("under", "workers", cost=100)
        u = lim.usage("under")
        assert u["workers"]["current"] == 0

    def test_all_usage_excludes_unprofiled_agents(self):
        """Agents not in _profiles won't appear in all_usage even if they have usage."""
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        lim.check("temporary", "tokens", cost=10)
        all_u = lim.all_usage()
        # "temporary" was never set_profile'd, but check stores usage anyway.
        # all_usage iterates _profiles, so temporary may not be present
        # unless it ended up in _profiles via setdefault.
        # Let's verify it's there if created via set_profile, but via check alone
        # the agent_id wouldn't be in _profiles... actually setdefault is called
        # in set_profile, not in check. So temporary should *not* be in all_usage.
        assert "temporary" not in all_u

    def test_get_profile_returns_all_five_keys(self):
        from kernel.resource import ResourceLimiter
        lim = ResourceLimiter()
        p = lim.get_profile("default")
        assert set(p.keys()) == {"max_tokens", "max_workers", "max_scouts", "max_memory", "priority"}

    def test_default_cost_used_when_omitted(self):
        from kernel.resource import RESOURCE_DEFAULT_COST, ResourceLimiter
        lim = ResourceLimiter()
        lim.set_profile("default-cost", max_workers=5)
        r1 = lim.check("default-cost", "workers")
        assert r1["success"] is True
        assert r1["current"] == RESOURCE_DEFAULT_COST
        r2 = lim.check("default-cost", "workers")
        assert r2["success"] is True
        assert r2["current"] == RESOURCE_DEFAULT_COST * 2
