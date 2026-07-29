"""Comprehensive allocator tests — alloc/free, OOM, pressure, swap, limits."""

from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestAllocatorBasics:
    """Allocator creation and core alloc/free/usage."""

    def test_get_allocator_singleton(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a1 = get_allocator()
        a2 = get_allocator()
        assert a1 is a2

    def test_reset_allocator(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        assert a is not None
        reset_allocator()
        b = get_allocator()
        assert a is not b

    def test_alloc_success_defaults(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        result = a.alloc("agent_a", "tokens")
        assert result["success"] is True
        assert result["used"] >= 1
        assert result["remaining"] >= 0

    def test_alloc_returns_remaining(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("agent_b", "tokens", 50)
        r = a.alloc("agent_b", "tokens", 10)
        assert r["success"] is True
        assert r["remaining"] == 40
        assert r["used"] == 10
        r2 = a.alloc("agent_b", "tokens", 10)
        assert r2["remaining"] == 30

    def test_free_returns_freed_amount(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        # free() removes complete Allocation objects; if the only allocation
        # has amount=10, freeing 5 still removes the whole 10.
        a.alloc("agent_c", "tokens", 10)
        r = a.free("agent_c", "tokens", 5)
        assert r["success"] is True
        assert r["freed"] == 10  # whole allocation removed

    def test_free_exact_amount(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.alloc("agent_d", "tokens", 7)
        r = a.free("agent_d", "tokens", 7)
        assert r["freed"] == 7

    def test_free_nonexistent_agent(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        r = a.free("no_such_agent", "tokens", 5)
        assert r["success"] is True
        assert r["freed"] == 0

    def test_usage_returns_all_resources(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        from l1.kernel.params.kernel import (
            RESOURCE_TOKENS,
            RESOURCE_RING1,
            RESOURCE_RING2,
            RESOURCE_RING3,
            RESOURCE_SANDBOX_KB,
            RESOURCE_PRIORITY,
        )
        reset_allocator()
        a = get_allocator()
        u = a.usage("agent_e")
        assert RESOURCE_TOKENS in u
        assert RESOURCE_RING1 in u
        assert RESOURCE_RING2 in u
        assert RESOURCE_RING3 in u
        assert RESOURCE_SANDBOX_KB in u
        assert RESOURCE_PRIORITY in u

    def test_usage_shows_pct(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("agent_f", "tokens", 100)
        a.alloc("agent_f", "tokens", 25)
        u = a.usage("agent_f")
        assert u["tokens"]["used"] == 25
        assert u["tokens"]["limit"] == 100
        assert u["tokens"]["pct"] == 25.0

    def test_summary_lists_all_agents(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.alloc("sum_agent_1", "tokens", 5)
        a.alloc("sum_agent_2", "ring1", 3)
        s = a.summary()
        assert "sum_agent_1" in s
        assert "sum_agent_2" in s
        assert isinstance(s["sum_agent_1"], dict)


class TestAllocatorLimits:
    """set_limit and enforcement."""

    def test_set_limit_returns_success(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        r = a.set_limit("limit_agent", "tokens", 200)
        assert r == {"success": True}

    def test_set_limit_overrides_default(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("limit_agent_b", "tokens", 50)
        # Make sure limit is reflected in usage
        u = a.usage("limit_agent_b")
        assert u["tokens"]["limit"] == 50

    def test_set_limit_multiple_resources(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("multi_agent", "tokens", 100)
        a.set_limit("multi_agent", "ring1", 10)
        u = a.usage("multi_agent")
        assert u["tokens"]["limit"] == 100
        assert u["ring1"]["limit"] == 10

    def test_alloc_fails_when_exceeding_limit(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("small_agent", "tokens", 10)
        # Allocate all 10
        a.alloc("small_agent", "tokens", 10)
        # Try to exceed — should trigger reclamation, OOM, then fail
        r = a.alloc("small_agent", "tokens", 5)
        assert r["success"] is False
        assert r.get("oom") is True

    def test_reclaim_expired_allocations(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("exp_agent", "tokens", 50)
        # Allocate with short TTL (0.01s) so it expires quickly
        a.alloc("exp_agent", "tokens", 40, purpose="ephemeral", ttl=0.01)
        time.sleep(0.03)
        # Now allocate more — should reclaim expired ones internally
        r = a.alloc("exp_agent", "tokens", 30)
        assert r["success"] is True
        # The returned "used" is pre-reclaim used + amount = 40+30=70,
        # but the actual stored state only has the new allocation (30).
        u = a.usage("exp_agent")
        assert u["tokens"]["used"] == 30  # expired ones were reclaimed

    def test_reclaim_observe_purpose(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("obs_agent", "tokens", 50)
        # Allocate 40 with "observe" purpose (reclaimable)
        a.alloc("obs_agent", "tokens", 40, purpose="observe.something")
        # Allocate 10 regular
        a.alloc("obs_agent", "tokens", 10)
        # Now try to allocate 10 more — should reclaim observe allocations
        r = a.alloc("obs_agent", "tokens", 10)
        assert r["success"] is True


class TestOOMKiller:
    """OOM killer: victim selection, interrupt firing, process exit."""

    def test_oom_kill_reclaims_resources(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        # Two agents: one with low priority, one requesting
        a.set_limit("victim_low", "tokens", 30)
        a.set_limit("victim_low", "priority", 1)  # low priority -> victim
        a.alloc("victim_low", "tokens", 30)

        a.set_limit("requester", "tokens", 20)
        a.alloc("requester", "tokens", 5)

        # Request beyond available — triggers OOM which reclaims 30 from victim
        # After OOM reclaim, available becomes enough, so alloc SUCCEEDS
        r = a.alloc("requester", "tokens", 30)
        assert r["success"] is True
        # Victim's allocations were reclaimed
        u = a.usage("victim_low")
        assert u["tokens"]["used"] == 0

    def test_oom_fires_interrupt(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        from l1.kernel.interrupt import get_table, InterruptType
        reset_allocator()
        int_table = get_table()
        # Reset counts for clean test
        before = int_table.counts().get("OOM_KILL", 0)

        a = get_allocator()
        a.set_limit("oom_victim", "tokens", 20)
        a.set_limit("oom_victim", "priority", 1)
        a.alloc("oom_victim", "tokens", 20)

        a.set_limit("oom_req", "tokens", 20)
        a.alloc("oom_req", "tokens", 20)

        # Try to exceed — should trigger OOM
        a.alloc("oom_req", "tokens", 10)

        after = int_table.counts().get("OOM_KILL", 0)
        assert after > before, "OOM_KILL interrupt should have been fired"

    def test_oom_selects_lowest_priority_victim(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()

        # High priority agent
        a.set_limit("high_prio", "tokens", 30)
        a.set_limit("high_prio", "priority", 10)
        a.alloc("high_prio", "tokens", 30)

        # Low priority agent
        a.set_limit("low_prio", "tokens", 30)
        a.set_limit("low_prio", "priority", 1)
        a.alloc("low_prio", "tokens", 30)

        # Requester
        a.set_limit("req", "tokens", 30)
        a.alloc("req", "tokens", 30)

        # Request more — OOM kills low_prio (priority=1), reclaims its tokens
        r = a.alloc("req", "tokens", 10)
        # After reclaim the alloc succeeds
        assert r["success"] is True
        # The low-priority victim's allocations were reclaimed
        usage_after = a.usage("low_prio")
        assert usage_after["tokens"]["used"] < 30

    def test_oom_no_candidate_returns_zero(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("solo", "tokens", 5)
        a.alloc("solo", "tokens", 5)
        r = a.alloc("solo", "tokens", 10)
        assert r["success"] is False
        assert r.get("oom") is True

    def test_oom_resource_exhaustion_interrupt(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        from l1.kernel.interrupt import get_table, InterruptType
        reset_allocator()
        int_table = get_table()
        before = int_table.counts().get("RESOURCE_EXHAUSTION", 0)

        a = get_allocator()
        a.set_limit("exhaust_me", "tokens", 5)
        a.alloc("exhaust_me", "tokens", 5)
        a.alloc("exhaust_me", "tokens", 10)

        after = int_table.counts().get("RESOURCE_EXHAUSTION", 0)
        assert after > before


class TestPressureDetection:
    """Pressure threshold detection."""

    def test_no_pressure_when_below_threshold(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("low_usage", "tokens", 100)
        a.alloc("low_usage", "tokens", 10)
        p = a.pressure()
        assert p["under_pressure"] is False
        assert p["count"] == 0

    def test_pressure_when_above_threshold(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("high_usage", "tokens", 100)
        # 90% usage — above default 80% threshold
        a.alloc("high_usage", "tokens", 90)
        p = a.pressure()
        assert p["under_pressure"] is True
        assert p["count"] >= 1

    def test_pressure_custom_threshold(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("custom_thresh", "tokens", 100)
        a.alloc("custom_thresh", "tokens", 30)
        # 30% usage — not above 80%
        p80 = a.pressure()
        assert p80["under_pressure"] is False
        # 30% usage — above 20% threshold
        p20 = a.pressure(threshold=20.0)
        assert p20["under_pressure"] is True

    def test_pressure_reports_agent_and_resource(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("pressure_agent", "ring1", 10)
        a.alloc("pressure_agent", "ring1", 9)
        p = a.pressure()
        assert p["under_pressure"] is True
        found = any(
            agent["agent_id"] == "pressure_agent" and agent["resource"] == "ring1"
            for agent in p["agents"]
        )
        assert found, "pressure_agent/ring1 should be in pressure report"

    def test_pressure_multiple_agents(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("p1", "tokens", 10)
        a.set_limit("p2", "tokens", 10)
        a.alloc("p1", "tokens", 9)
        a.alloc("p2", "tokens", 9)
        p = a.pressure()
        assert p["count"] >= 2


class TestSwapOut:
    """swap_out: move allocations between resources."""

    def test_swap_out_ring1_to_ring2(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("swap_agent", "ring1", 100)
        a.set_limit("swap_agent", "ring2", 100)
        a.alloc("swap_agent", "ring1", 10)
        r = a.swap_out("swap_agent", resource="ring1", target_resource="ring2")
        assert r["success"] is True
        assert r["moved"] >= 1
        assert r["from"] == "ring1"
        assert r["to"] == "ring2"
        u = a.usage("swap_agent")
        # ring1 should have less, ring2 more
        assert u["ring1"]["used"] == 0
        assert u["ring2"]["used"] == 10

    def test_swap_out_ring2_to_ring3(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("swap_agent2", "ring2", 100)
        a.set_limit("swap_agent2", "ring3", 100)
        # Allocate 7 as a single Allocation object
        a.alloc("swap_agent2", "ring2", 7)
        r = a.swap_out("swap_agent2", resource="ring2", target_resource="ring3")
        # swap_out moves individual Allocation objects (up to count=5 default).
        # Since there is 1 Allocation object, moved=1.
        assert r["success"] is True
        assert r["moved"] == 1
        u = a.usage("swap_agent2")
        assert u["ring2"]["used"] == 0
        assert u["ring3"]["used"] == 7

    def test_swap_out_to_disk_removes_allocation(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        from l1.kernel.params.kernel import ALLOCATOR_DISK_RESOURCE
        reset_allocator()
        a = get_allocator()
        a.set_limit("swap_disk", "ring3", 100)
        a.alloc("swap_disk", "ring3", 5)
        r = a.swap_out("swap_disk", resource="ring3", target_resource=ALLOCATOR_DISK_RESOURCE)
        assert r["success"] is True
        # 1 Allocation object moved
        assert r["moved"] == 1
        # Allocation should be removed from ring3
        u = a.usage("swap_disk")
        assert u["ring3"]["used"] == 0

    def test_swap_out_empty_source_noop(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        r = a.swap_out("nonexistent", resource="ring1", target_resource="ring2")
        assert r["success"] is True
        assert r["moved"] == 0

    def test_swap_out_respects_count_param(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("swap_count", "ring1", 100)
        for _ in range(10):
            a.alloc("swap_count", "ring1")
        r = a.swap_out("swap_count", resource="ring1", target_resource="ring2", count=3)
        assert r["success"] is True
        assert r["moved"] == 3


class TestCancellationAndEdgeCases:
    """Edge cases: concurrent calls, invalid amounts, ttl expiry."""

    def test_alloc_with_ttl_expiry(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("ttl_agent", "tokens", 50)
        a.alloc("ttl_agent", "tokens", 30, purpose="temp", ttl=0.01)
        time.sleep(0.03)
        # Allocate more — should trigger reclamation of expired
        r = a.alloc("ttl_agent", "tokens", 30)
        assert r["success"] is True

    def test_alloc_with_purpose(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        r = a.alloc("purpose_agent", "tokens", 5, purpose="test.purpose")
        assert r["success"] is True

    def test_alloc_zero_amount(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        from l1.kernel.params.kernel import ALLOCATOR_DEFAULT_AMOUNT
        reset_allocator()
        a = get_allocator()
        r = a.alloc("zero_agent", "tokens", 0)
        # Should succeed with default amount not relevant; 0 alloc uses 0
        assert r["success"] is True

    def test_thread_safety(self):
        import threading
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("thread_agent", "tokens", 1000)

        errors = []

        def alloc_loop():
            for _ in range(50):
                r = a.alloc("thread_agent", "tokens", 1)
                if not r["success"]:
                    errors.append(r.get("error"))
                time.sleep(0.001)

        threads = [threading.Thread(target=alloc_loop) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_multiple_frees(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("multi_free", "tokens", 100)
        a.alloc("multi_free", "tokens", 50)
        # free() removes whole Allocation objects, so freeing 20 removes the
        # entire 50 allocation.
        r1 = a.free("multi_free", "tokens", 20)
        assert r1["freed"] == 50
        u = a.usage("multi_free")
        assert u["tokens"]["used"] == 0

    def test_usage_empty_agent_returns_defaults(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        u = a.usage("never_allocated")
        assert u["tokens"]["used"] == 0
        assert u["tokens"]["limit"] > 0

    def test_fallback_limit_used_when_no_limit_set(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        from l1.kernel.params.kernel import ALLOCATOR_FALLBACK_LIMIT
        reset_allocator()
        a = get_allocator()
        # "cpu" is not in DEFAULTS, so the fallback limit (100) is used.
        # Allocating beyond fallback should fail.
        r = a.alloc("fallback_agent", "cpu", ALLOCATOR_FALLBACK_LIMIT + 10)
        assert r["success"] is False


class TestAllocatorIntegration:
    """Integration-style tests combining multiple operations."""

    def test_alloc_free_reuse(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("cycle", "tokens", 100)
        assert a.alloc("cycle", "tokens", 80)["success"]
        # free() removes the whole allocation (80)
        assert a.free("cycle", "tokens", 40)["freed"] == 80
        assert a.alloc("cycle", "tokens", 30)["success"]
        u = a.usage("cycle")
        assert u["tokens"]["used"] == 30

    def test_pressure_relief_after_free(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("relief", "tokens", 100)
        a.alloc("relief", "tokens", 90)
        assert a.pressure()["under_pressure"] is True
        a.free("relief", "tokens", 50)
        assert a.pressure()["under_pressure"] is False

    def test_oom_then_free_then_alloc(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.set_limit("oom_recover", "tokens", 20)
        a.alloc("oom_recover", "tokens", 20)
        r = a.alloc("oom_recover", "tokens", 10)
        assert r["success"] is False  # OOM

        # Free some
        a.free("oom_recover", "tokens", 15)
        # Now should succeed
        r2 = a.alloc("oom_recover", "tokens", 5)
        assert r2["success"] is True

    def test_summary_includes_all_agents(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        reset_allocator()
        a = get_allocator()
        a.alloc("s1", "tokens", 1)
        a.alloc("s2", "tokens", 2)
        a.alloc("s3", "tokens", 3)
        s = a.summary()
        assert len(s) == 3
        for agent in ("s1", "s2", "s3"):
            assert agent in s

    def test_different_resource_types(self):
        from l1.kernel.allocator import get_allocator, reset_allocator
        from l1.kernel.params.kernel import (
            RESOURCE_TOKENS,
            RESOURCE_RING1,
            RESOURCE_RING2,
            RESOURCE_RING3,
            RESOURCE_SANDBOX_KB,
        )
        reset_allocator()
        a = get_allocator()
        a.set_limit("multi_resource", RESOURCE_TOKENS, 100)
        a.set_limit("multi_resource", RESOURCE_RING1, 20)
        a.set_limit("multi_resource", RESOURCE_RING2, 50)
        a.set_limit("multi_resource", RESOURCE_RING3, 100)
        a.set_limit("multi_resource", RESOURCE_SANDBOX_KB, 5000)

        a.alloc("multi_resource", RESOURCE_TOKENS, 30)
        a.alloc("multi_resource", RESOURCE_RING1, 5)
        a.alloc("multi_resource", RESOURCE_RING2, 10)
        a.alloc("multi_resource", RESOURCE_RING3, 25)
        a.alloc("multi_resource", RESOURCE_SANDBOX_KB, 1000)

        u = a.usage("multi_resource")
        assert u[RESOURCE_TOKENS]["used"] == 30
        assert u[RESOURCE_RING1]["used"] == 5
        assert u[RESOURCE_RING2]["used"] == 10
        assert u[RESOURCE_RING3]["used"] == 25
        assert u[RESOURCE_SANDBOX_KB]["used"] == 1000
