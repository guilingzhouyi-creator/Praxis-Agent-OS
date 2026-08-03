"""Tool chain tests — start, child, complete, get, chain, subtree, verify,
agent_calls, recent, stats. Covers fingerprint chain integrity and trimming."""
from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

if TYPE_CHECKING:
    from l1.kernel.tool_chain import ToolChain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chain(max_calls: int = 5000) -> ToolChain:
    """Return a fresh ToolChain for test isolation."""
    from l1.kernel.tool_chain import ToolChain
    tc = ToolChain()
    tc._max_calls = max_calls
    return tc


# ---------------------------------------------------------------------------
# start / child
# ---------------------------------------------------------------------------

class TestToolChainStart:
    def test_start_returns_call_id(self):
        from l1.kernel.tool_chain import ToolChain
        tc = ToolChain()
        cid = tc.start("read_file", "agent_a")
        assert cid.startswith("call-")
        assert len(cid) == 5 + 8  # "call-" + 8 hex chars

    def test_start_root_depth_one(self):
        tc = _make_chain()
        cid = tc.start("read_file", "agent_a", ring=2)
        link = tc.get(cid)
        assert link is not None
        assert link.depth == 1
        assert link.tool_name == "read_file"
        assert link.agent_id == "agent_a"
        assert link.ring == 2
        assert link.parent_id == ""

    def test_start_with_parent_increments_depth(self):
        tc = _make_chain()
        parent_id = tc.start("review", "agent_b", ring=2)
        child_id = tc.start("read_file", "agent_a", ring=1, parent_id=parent_id)
        child_link = tc.get(child_id)
        assert child_link is not None
        assert child_link.depth == 2
        assert child_link.parent_id == parent_id
        # parent children list updated
        parent_link = tc.get(parent_id)
        assert child_id in parent_link.children

    def test_start_generates_unique_ids(self):
        tc = _make_chain()
        ids = {tc.start("tool", "agent") for _ in range(20)}
        assert len(ids) == 20

    def test_child_convenience(self):
        tc = _make_chain()
        parent_id = tc.start("composite", "agent_c")
        child_id = tc.child("atomic", "agent_c", ring=1, parent=parent_id)
        assert child_id.startswith("call-")
        link = tc.get(child_id)
        assert link.parent_id == parent_id
        assert link.depth == 2
        assert link.tool_name == "atomic"

    def test_child_default_ring(self):
        tc = _make_chain()
        parent_id = tc.start("p", "a")
        cid = tc.child("c", "a", parent=parent_id)
        assert tc.get(cid).ring == 1


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------

class TestToolChainComplete:
    def test_mark_success(self):
        tc = _make_chain()
        cid = tc.start("build", "agent_x")
        assert tc.complete(cid, success=True) is True
        link = tc.get(cid)
        assert link.success is True

    def test_mark_failure_with_error(self):
        tc = _make_chain()
        cid = tc.start("deploy", "agent_x")
        assert tc.complete(cid, success=False, error="timeout") is True
        link = tc.get(cid)
        assert link.success is False
        assert link.error == "timeout"

    def test_complete_sets_duration(self):
        tc = _make_chain()
        cid = tc.start("ping", "agent_y")
        tc.complete(cid, duration=1.234)
        assert tc.get(cid).duration == 1.234

    def test_complete_invalid_id_returns_false(self):
        tc = _make_chain()
        assert tc.complete("call-nonexistent") is False


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

class TestToolChainGet:
    def test_get_returns_link(self):
        tc = _make_chain()
        cid = tc.start("scan", "agent_z")
        link = tc.get(cid)
        assert isinstance(link, object)
        assert link.call_id == cid
        assert link.fingerprint != ""

    def test_get_missing_returns_none(self):
        tc = _make_chain()
        assert tc.get("call-00000000") is None


# ---------------------------------------------------------------------------
# chain (ancestry traversal)
# ---------------------------------------------------------------------------

class TestToolChainChain:
    def test_root_chain_is_singleton(self):
        tc = _make_chain()
        cid = tc.start("root_tool", "agent")
        ancestry = tc.chain(cid)
        assert len(ancestry) == 1
        assert ancestry[0].call_id == cid

    def test_chain_from_leaf_to_root(self):
        tc = _make_chain()
        r1 = tc.start("grandparent", "a", ring=3)
        r2 = tc.start("parent", "a", ring=2, parent_id=r1)
        r3 = tc.start("child", "a", ring=1, parent_id=r2)

        ancestry = tc.chain(r3)
        # order: child → parent → grandparent
        assert len(ancestry) == 3
        assert ancestry[0].call_id == r3
        assert ancestry[1].call_id == r2
        assert ancestry[2].call_id == r1
        assert ancestry[2].depth == 1

    def test_chain_missing_id(self):
        tc = _make_chain()
        assert tc.chain("call-nope") == []


# ---------------------------------------------------------------------------
# subtree (descendant traversal)
# ---------------------------------------------------------------------------

class TestToolChainSubtree:
    def test_subtree_single(self):
        tc = _make_chain()
        cid = tc.start("solo", "agent")
        nodes = tc.subtree(cid)
        assert len(nodes) == 1
        assert nodes[0].call_id == cid

    def test_subtree_all_descendants(self):
        tc = _make_chain()
        r = tc.start("root", "a", ring=3)
        c1 = tc.child("child1", "a", parent=r)
        c2 = tc.child("child2", "a", parent=r)
        g1 = tc.child("grandchild", "a", parent=c1)

        nodes = tc.subtree(r)
        ids = {n.call_id for n in nodes}
        assert r in ids
        assert c1 in ids
        assert c2 in ids
        assert g1 in ids
        assert len(nodes) == 4

    def test_subtree_missing_id(self):
        tc = _make_chain()
        assert tc.subtree("call-absent") == []


# ---------------------------------------------------------------------------
# verify (fingerprint chain integrity)
# ---------------------------------------------------------------------------

class TestToolChainVerify:
    def test_verify_passes_on_intact_chain(self):
        tc = _make_chain()
        r = tc.start("root", "agent", ring=2)
        c = tc.child("child", "agent", parent=r)
        result = tc.verify(c)
        assert result["valid"] is True
        assert result["depth"] == 2
        assert all(s["fingerprint_match"] for s in result["steps"])

    def test_verify_passes_deep_chain(self):
        tc = _make_chain()
        ids = []
        prev = ""
        for i in range(10):
            prev = tc.start(f"tool_{i}", "agent", ring=1, parent_id=prev)
            ids.append(prev)
        result = tc.verify(ids[-1])
        assert result["valid"] is True
        assert result["depth"] == 10

    def test_verify_single_call(self):
        tc = _make_chain()
        cid = tc.start("singleton", "agent_x")
        result = tc.verify(cid)
        assert result["valid"] is True
        assert result["depth"] == 1

    def test_verify_detects_tampered_fingerprint(self):
        tc = _make_chain()
        r = tc.start("root", "agent", ring=1)
        c = tc.child("child", "agent", parent=r)
        # Tamper with the child's fingerprint
        link = tc.get(c)
        link.fingerprint = link.fingerprint[:-1] + "X"
        result = tc.verify(c)
        assert result["valid"] is False
        # At least one step should mismatch
        mismatches = [s for s in result["steps"] if not s["fingerprint_match"]]
        assert len(mismatches) >= 1

    def test_verify_detects_tampered_depth(self):
        tc = _make_chain()
        r = tc.start("root", "agent", ring=1)
        c = tc.child("child", "agent", parent=r)
        link = tc.get(c)
        link.depth = 99  # tamper
        result = tc.verify(c)
        assert result["valid"] is False

    def test_verify_detects_tampered_tool_name(self):
        tc = _make_chain()
        r = tc.start("root", "agent", ring=1)
        c = tc.child("child", "agent", parent=r)
        tc.get(c).tool_name = "evil_tool"
        assert tc.verify(c)["valid"] is False


# ---------------------------------------------------------------------------
# agent_calls
# ---------------------------------------------------------------------------

class TestToolChainAgentCalls:
    def test_agent_calls_returns_matching(self):
        tc = _make_chain()
        tc.start("tool_a", "alice")
        tc.start("tool_b", "bob")
        tc.start("tool_c", "alice")
        calls = tc.agent_calls("alice")
        assert len(calls) == 2
        assert all(c.agent_id == "alice" for c in calls)

    def test_agent_calls_respects_limit(self):
        tc = _make_chain()
        for _ in range(10):
            tc.start("t", "alice")
        calls = tc.agent_calls("alice", limit=3)
        assert len(calls) == 3

    def test_agent_calls_no_matches(self):
        tc = _make_chain()
        tc.start("t", "alice")
        assert tc.agent_calls("nobody") == []


# ---------------------------------------------------------------------------
# recent
# ---------------------------------------------------------------------------

class TestToolChainRecent:
    def test_recent_returns_dicts(self):
        tc = _make_chain()
        tc.start("scan", "agent_x", ring=2)
        recent = tc.recent()
        assert len(recent) >= 1
        entry = recent[-1]
        assert "call_id" in entry
        assert "tool" in entry
        assert "agent" in entry
        assert "ring" in entry

    def test_recent_respects_limit(self):
        tc = _make_chain()
        for i in range(30):
            tc.start(f"t{i}", "a")
        assert len(tc.recent(limit=5)) == 5
        assert len(tc.recent(limit=100)) == 30  # less than total

    def test_recent_order_newest_last(self):
        tc = _make_chain()
        ids = [tc.start("t", "a") for _ in range(5)]
        recent = tc.recent(limit=5)
        assert recent[-1]["call_id"] == ids[-1]
        assert recent[0]["call_id"] == ids[0]


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class TestToolChainStats:
    def test_stats_structure(self):
        tc = _make_chain()
        s = tc.stats()
        assert "total_calls" in s
        assert "max_calls" in s
        assert "by_ring" in s

    def test_stats_counts(self):
        tc = _make_chain()
        tc.start("t1", "a", ring=1)
        tc.start("t2", "a", ring=2)
        tc.start("t3", "a", ring=2)
        s = tc.stats()
        assert s["total_calls"] == 3
        assert s["by_ring"] == {1: 1, 2: 2}

    def test_stats_max_calls(self):
        tc = _make_chain(max_calls=100)
        assert tc.stats()["max_calls"] == 100


# ---------------------------------------------------------------------------
# Fingerprint chain integrity — deep validation
# ---------------------------------------------------------------------------

class TestToolChainFingerprintIntegrity:
    def test_fingerprints_differ_per_call(self):
        tc = _make_chain()
        fp_set = set()
        ids = []
        for _ in range(10):
            cid = tc.start("t", "a")
            ids.append(cid)
            fp_set.add(tc.get(cid).fingerprint)
        assert len(fp_set) == 10  # all unique

    def test_fingerprint_links_parent_child(self):
        tc = _make_chain()
        p = tc.start("parent", "a", ring=2)
        c = tc.child("child", "a", ring=1, parent=p)
        pl = tc.get(p)
        cl = tc.get(c)
        # Child's prev_fingerprint should equal parent's fingerprint
        assert cl.prev_fingerprint == pl.fingerprint

    def test_chain_verify_tree_branch(self):
        """Build a tree with two branches and verify each leaf independently."""
        tc = _make_chain()
        root = tc.start("root", "agent", ring=3)
        # branch A
        a1 = tc.child("a1", "agent", ring=2, parent=root)
        a2 = tc.child("a2", "agent", ring=1, parent=a1)
        # branch B
        b1 = tc.child("b1", "agent", ring=2, parent=root)
        b2 = tc.child("b2", "agent", ring=1, parent=b1)

        assert tc.verify(root)["valid"] is True
        assert tc.verify(a2)["valid"] is True
        assert tc.verify(b2)["valid"] is True
        # Tamper only branch A leaf; branch B should remain valid
        tc.get(a2).fingerprint = tc.get(a2).fingerprint[:-1] + "X"
        assert tc.verify(a2)["valid"] is False
        assert tc.verify(b2)["valid"] is True

    def test_recompute_after_verify_detects_tampered_ring(self):
        tc = _make_chain()
        p = tc.start("parent", "a", ring=2)
        c = tc.child("child", "a", ring=1, parent=p)
        tc.get(c).ring = 5  # tamper
        result = tc.verify(c)
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# Trimming
# ---------------------------------------------------------------------------

class TestToolChainTrim:
    def test_trim_keeps_max_calls_watermark(self):
        """When calls exceed max_calls, they are trimmed to ~max_calls/2."""
        tc = _make_chain(max_calls=20)
        for i in range(30):
            tc.start(f"t{i}", "agent")
        s = tc.stats()
        # Should not exceed max_calls
        assert s["total_calls"] <= 20
        # After trim, should be around max_calls/2
        assert s["total_calls"] >= 5  # at least a few survive

    def test_trim_re_roots_orphaned_children(self):
        """Orphaned children have parent_id cleared and prev_fp reset."""
        tc = _make_chain(max_calls=10)
        # First call is oldest, will be trimmed
        root = tc.start("root", "agent")
        children = []
        for i in range(8):
            children.append(tc.child(f"c{i}", "agent", parent=root))
        # Trigger trim
        extra = tc.start("extra", "agent")
        _ = tc.start("extra2", "agent")

        # Check that remaining children of trimmed root were re-rooted
        remaining = [c for c in children if tc.get(c) is not None]
        for cid in remaining:
            link = tc.get(cid)
            assert link.parent_id == "", f"orphan {cid} not re-rooted"
            assert link.prev_fingerprint == "GENESIS"

    def test_trim_preserves_verify_on_re_rooted_branch(self):
        """After trimming the root, orphaned sub-chains still verify cleanly."""
        tc = _make_chain(max_calls=10)
        root = tc.start("root", "agent")
        c1 = tc.child("c1", "agent", parent=root)
        c2 = tc.child("c2", "agent", parent=c1)
        c3 = tc.child("c3", "agent", parent=c2)
        # Flood to trigger trim
        for i in range(10):
            tc.start(f"flood{i}", "agent")
        # Root may be gone; verify deepest node if it survived
        deepest = tc.get(c3)
        if deepest is not None:
            result = tc.verify(c3)
            assert result["valid"] is True, (
                f"re-rooted chain fails verify: {result}"
            )

    def test_trim_fingerprint_recomputation_cascade(self):
        """When an orphan is re-rooted, its descendants' fingerprints
        are recomputed so the entire subtree stays coherent."""
        tc = _make_chain(max_calls=8)
        root = tc.start("root", "agent")
        mid = tc.child("mid", "agent", parent=root)
        leaf = tc.child("leaf", "agent", parent=mid)

        # Pre-compute what we expect before trim
        mid_fp_before = tc.get(mid).fingerprint
        leaf_fp_before = tc.get(leaf).fingerprint

        # Flood to kick trim
        for i in range(10):
            tc.start(f"x{i}", "agent")

        mid_link = tc.get(mid)
        leaf_link = tc.get(leaf)

        if mid_link is not None and leaf_link is not None:
            # Fingerprints must have changed due to re-rooting
            assert mid_link.fingerprint != mid_fp_before, \
                "mid fingerprint should change after re-root"
            assert leaf_link.fingerprint != leaf_fp_before, \
                "leaf fingerprint should cascade after re-root"
            # Verify the new chain
            assert tc.verify(leaf)["valid"] is True

    def test_no_trim_below_max(self):
        """When under max_calls, no entries are removed."""
        tc = _make_chain(max_calls=50)
        for i in range(10):
            tc.start(f"t{i}", "agent")
        assert tc.stats()["total_calls"] == 10


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestToolChainThreadSafety:
    def test_concurrent_start(self):
        import threading
        tc = _make_chain()
        results: list[str] = []

        def worker(n: int):
            for _ in range(50):
                cid = tc.start(f"t{n}", "agent")
                results.append(cid)

        threads = [threading.Thread(target=worker, args=(i,), daemon=True)
                   for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        assert len(results) == 200
        assert len(set(results)) == 200  # no duplicates

    def test_concurrent_complete(self):
        import threading
        tc = _make_chain()
        cid = tc.start("shared", "agent")

        def completer():
            tc.complete(cid, success=True)

        threads = [threading.Thread(target=completer, daemon=True)
                   for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(2)
        # The call is marked complete (last writer wins, no crash)
        assert tc.get(cid) is not None


# ---------------------------------------------------------------------------
# Singleton integration
# ---------------------------------------------------------------------------

class TestToolChainSingleton:
    def test_get_tool_chain_returns_same_instance(self):
        from l1.kernel.tool_chain import get_tool_chain
        tc1 = get_tool_chain()
        tc2 = get_tool_chain()
        assert tc1 is tc2

    def test_reset_tool_chain_clears(self):
        from l1.kernel.tool_chain import get_tool_chain, reset_tool_chain
        tc1 = get_tool_chain()
        tc1.start("test", "agent")
        assert tc1.stats()["total_calls"] >= 1
        reset_tool_chain()
        tc2 = get_tool_chain()
        assert tc2 is not tc1
        assert tc2.stats()["total_calls"] == 0
