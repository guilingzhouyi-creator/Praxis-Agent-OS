"""Tests for l3.cell.components.cell_mmu — MMU/TLB memory management."""

from __future__ import annotations

import pytest

from l1.kernel.params.system import TLB_MAX_ENTRIES
from l3.cell.components.cell_mmu import CellMmu, CellTlb

# ── Fixtures ──


@pytest.fixture
def tlb():
    """Fresh TLB with mock PMU."""
    pmu = _FakePmu()
    return CellTlb(max_entries=16, pmu=pmu), pmu


@pytest.fixture
def mmu():
    """MMU with TLB, no ICache (no page-walk fallback)."""
    return CellMmu(cell_id="test-cell", tlb=CellTlb(max_entries=16))


class _FakePmu:
    def __init__(self):
        self.counts = {}

    def increment(self, name: str, delta: int = 1):
        self.counts[name] = self.counts.get(name, 0) + delta


# ═══════════════════════════════════════════════════════════════
# CellTlb tests
# ═══════════════════════════════════════════════════════════════


class TestTlbInit:
    def test_empty_on_create(self, tlb):
        t, _ = tlb
        assert t.stats()["entries"] == 0

    def test_default_max_entries(self):
        t = CellTlb()
        assert t._max_entries == TLB_MAX_ENTRIES


class TestTlbFill:
    def test_fill_and_lookup(self, tlb):
        t, _ = tlb
        t.fill("src/", "agent-a", ring=1)
        entry = t.lookup("src/")
        assert entry is not None
        assert entry.agent_id == "agent-a"
        assert entry.ring == 1

    def test_fill_many(self, tlb):
        t, _ = tlb
        t.fill_many({"src/": ("agent-a", 1), "docs/": ("agent-b", 2)})
        assert t.lookup("src/").agent_id == "agent-a"
        assert t.lookup("docs/").agent_id == "agent-b"

    def test_fill_overwrites_existing(self, tlb):
        t, _ = tlb
        t.fill("src/", "agent-a")
        t.fill("src/", "agent-b", ring=2)
        entry = t.lookup("src/")
        assert entry.agent_id == "agent-b"
        assert entry.ring == 2


class TestTlbLookup:
    def test_miss_returns_none(self, tlb):
        t, _ = tlb
        assert t.lookup("nonexistent/") is None

    def test_hit_increments_counter(self, tlb):
        t, _ = tlb
        t.fill("src/", "agent-a")
        t.lookup("src/")
        entry = t.lookup("src/")
        assert entry.hit_count >= 1

    def test_miss_pmu_increment(self, tlb):
        t, pmu = tlb
        t.lookup("miss/")
        assert pmu.counts.get("tlb.misses", 0) >= 1

    def test_hit_pmu_increment(self, tlb):
        t, pmu = tlb
        t.fill("src/", "agent-a")
        t.lookup("src/")
        assert pmu.counts.get("tlb.hits", 0) >= 1

    def test_invalid_entry_returns_none(self, tlb):
        t, _ = tlb
        t.fill("src/", "agent-a")
        t.flush_agent("agent-a")
        assert t.lookup("src/") is None


class TestTlbFlush:
    def test_flush_agent(self, tlb):
        t, _ = tlb
        t.fill("src/", "agent-a")
        t.fill("docs/", "agent-a")
        count = t.flush_agent("agent-a")
        assert count == 2
        assert t.lookup("src/") is None
        assert t.lookup("docs/") is None

    def test_flush_territory(self, tlb):
        t, _ = tlb
        t.fill("src/", "agent-a")
        assert t.flush_territory("src/") is True
        assert t.lookup("src/") is None

    def test_flush_territory_missing(self, tlb):
        t, _ = tlb
        assert t.flush_territory("nonexistent/") is False

    def test_flush_all(self, tlb):
        t, _ = tlb
        t.fill("a/", "agent-1")
        t.fill("b/", "agent-2")
        count = t.flush_all()
        assert count == 2
        assert t.stats()["entries"] == 0

    def test_flush_pmu_increment(self, tlb):
        t, pmu = tlb
        t.fill("src/", "agent-a")
        t.flush_agent("agent-a")
        assert pmu.counts.get("tlb.flushes", 0) >= 1


class TestTlbEviction:
    def test_evict_when_over_capacity(self):
        t = CellTlb(max_entries=3)
        for i in range(5):
            t.fill(f"territory-{i}/", f"agent-{i}")
        stats = t.stats()
        assert stats["entries"] <= 3

    def test_evict_keeps_most_used(self):
        t = CellTlb(max_entries=3)
        t.fill("keep/", "agent-keep")
        t.lookup("keep/")  # hit count = 1
        t.fill("a/", "agent-a")
        t.fill("b/", "agent-b")
        t.fill("c/", "agent-c")  # triggers eviction
        assert t.lookup("keep/") is not None  # keep survived eviction


class TestTlbStats:
    def test_stats_shape(self, tlb):
        t, _ = tlb
        s = t.stats()
        assert "entries" in s
        assert "max_entries" in s
        assert "agents" in s
        assert "patterns" in s

    def test_stats_lists_agents(self, tlb):
        t, _ = tlb
        t.fill("src/", "agent-a")
        t.fill("docs/", "agent-b")
        assert "agent-a" in t.stats()["agents"]
        assert "agent-b" in t.stats()["agents"]


# ═══════════════════════════════════════════════════════════════
# CellMmu tests
# ═══════════════════════════════════════════════════════════════


class TestMmuResolve:
    def test_resolve_tlb_hit(self, mmu):
        mmu._tlb.fill("src/", "agent-a", ring=1)
        r = mmu.resolve("src/")
        assert r["agent_id"] == "agent-a"
        assert r["ring"] == 1

    def test_resolve_miss_no_agents(self, mmu):
        r = mmu.resolve("nonexistent/")
        assert r["agent_id"] == ""
        assert "error" in r

    def test_resolve_fallback_agents_dict(self, mmu):
        from l3.cell.components.cell_types import AgentInfo

        agents = {
            "agent-a": AgentInfo(role="reader", ring=1, territory=["src/"]),
            "agent-b": AgentInfo(role="writer", ring=2, territory=["docs/"]),
        }
        r = mmu.resolve("src/", agents)
        assert r["agent_id"] == "agent-a"
        assert r["ring"] == 1

    def test_resolve_fallback_caches_result(self, mmu):
        from l3.cell.components.cell_types import AgentInfo

        agents = {"agent-a": AgentInfo(ring=1, territory=["src/"])}
        mmu.resolve("src/", agents)
        # Second call should hit TLB
        r = mmu.resolve("src/")
        assert r["agent_id"] == "agent-a"

    def test_resolve_best_match_longest_prefix(self, mmu):
        from l3.cell.components.cell_types import AgentInfo

        agents = {
            "agent-a": AgentInfo(ring=1, territory=["src/"]),
            "agent-b": AgentInfo(ring=2, territory=["src/sub/"]),
        }
        r = mmu.resolve("src/sub/deep/", agents)
        # Should prefer agent-b (longer prefix match)
        assert r["agent_id"] == "agent-b"

    def test_resolve_many(self, mmu):
        from l3.cell.components.cell_types import AgentInfo

        agents = {
            "agent-a": AgentInfo(ring=1, territory=["src/"]),
            "agent-b": AgentInfo(ring=2, territory=["docs/"]),
        }
        results = mmu.resolve_many(["src/", "docs/"], agents)
        assert results["src/"]["agent_id"] == "agent-a"
        assert results["docs/"]["agent_id"] == "agent-b"

    def test_resolve_many_mixed(self, mmu):
        from l3.cell.components.cell_types import AgentInfo

        agents = {"agent-a": AgentInfo(ring=1, territory=["src/"])}
        results = mmu.resolve_many(["src/", "unknown/"], agents)
        assert results["src/"]["agent_id"] == "agent-a"
        assert results["unknown/"]["agent_id"] == ""


class TestMmuCacheWarming:
    def test_warm_from_agents(self, mmu):
        from l3.cell.components.cell_types import AgentInfo

        agents = {
            "agent-a": AgentInfo(ring=1, territory=["src/", "docs/"]),
            "agent-b": AgentInfo(ring=2, territory=["api/"]),
        }
        mmu.warm_from_agents(agents)
        assert mmu._tlb.lookup("src/") is not None
        assert mmu._tlb.lookup("docs/") is not None
        assert mmu._tlb.lookup("api/") is not None

    def test_warm_empty_agents(self, mmu):
        mmu.warm_from_agents({})
        assert mmu._tlb.stats()["entries"] == 0


class TestMmuFlush:
    def test_flush_agent_delegates_to_tlb(self, mmu):
        mmu._tlb.fill("src/", "agent-a")
        count = mmu.flush_agent("agent-a")
        assert count == 1
        assert mmu._tlb.lookup("src/") is None

    def test_flush_all_delegates_to_tlb(self, mmu):
        mmu._tlb.fill("src/", "agent-a")
        mmu._tlb.fill("docs/", "agent-b")
        count = mmu.flush_all()
        assert count == 2


class TestMmuStats:
    def test_stats_shape(self, mmu):
        s = mmu.stats()
        assert "cell_id" in s
        assert "tlb" in s
        assert s["cell_id"] == "test-cell"
