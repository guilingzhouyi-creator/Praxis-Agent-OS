"""Pager/PagerBridge/Swapper integration test."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestPager:
    def test_init(self):
        from l3.pager import ContextPager
        p = ContextPager()
        assert p is not None

    def test_fetch(self):
        from l3.pager import ContextPager
        p = ContextPager()
        r = p.fetch("chunk-test", agent_id="agent-p")
        assert isinstance(r, dict)

    def test_flush(self):
        from l3.pager import ContextPager
        p = ContextPager()
        r = p.flush("chunk-test")
        assert isinstance(r, dict)


class TestPagerBridge:
    def test_get_bridge(self):
        from l3.pager_bridge import get_pager_bridge, reset_pager_bridge
        reset_pager_bridge()
        b = get_pager_bridge()
        assert b is not None

    def test_pin_unpin(self):
        from l3.pager_bridge import get_pager_bridge, reset_pager_bridge
        reset_pager_bridge()
        b = get_pager_bridge()
        b.pin_chunk("test-chunk")
        assert b.is_pinned("test-chunk")
        b.unpin_chunk("test-chunk")
        assert not b.is_pinned("test-chunk")

    def test_on_swap_out(self):
        from l3.pager_bridge import get_pager_bridge, reset_pager_bridge
        reset_pager_bridge()
        b = get_pager_bridge()
        pinned = b.on_swap_out(["e1", "e2", "e3"], 3, 1)
        assert isinstance(pinned, list)

    def test_stats(self):
        from l3.pager_bridge import get_pager_bridge, reset_pager_bridge
        reset_pager_bridge()
        b = get_pager_bridge()
        s = b.stats()
        assert isinstance(s, dict)


class TestSwapper:
    def test_get_swapper(self):
        from l1.kernel.swapper import get_swapper, reset_swapper
        reset_swapper()
        s = get_swapper()
        assert s is not None

    def test_swap_in(self):
        from l1.kernel.swapper import get_swapper, reset_swapper
        from l3.memory import get_memory, reset_memory
        reset_swapper()
        reset_memory()
        mem = get_memory()
        mem.remember("agent-swap", "decision",
                      "Important decision data that is long enough for quality validation test.",
                      ring=3)
        s = get_swapper()
        s.set_memory(mem)
        entries = mem.recall(agent_id="agent-swap", limit=5)
        if entries:
            r = s.swap_in(entries[0].id)
            assert isinstance(r, dict)

    def test_stats(self):
        from l1.kernel.swapper import get_swapper, reset_swapper
        reset_swapper()
        s = get_swapper()
        stats = s.stats()
        assert isinstance(stats, dict)
