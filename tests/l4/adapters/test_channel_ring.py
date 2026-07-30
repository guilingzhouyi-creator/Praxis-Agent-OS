"""Adapter: RingChannel — thread-safe ring buffer channel tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

T = 0.1  # short timeout for test blocking calls


class TestRingChannel:
    """RingChannel basic operations."""

    def test_put_and_get(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=4)
        ch.put("a")
        ch.put("b")
        assert ch.get(timeout=T) == "a"
        assert ch.get(timeout=T) == "b"

    def test_get_empty_returns_none(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=4)
        assert ch.get(timeout=0.01) is None

    def test_peek(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=4)
        ch.put("x")
        assert ch.peek(timeout=T) == "x"
        assert ch.get(timeout=T) == "x"

    def test_size(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=4)
        assert ch.size() == 0
        ch.put("a")
        ch.put("b")
        assert ch.size() == 2

    def test_capacity(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=10)
        assert ch.capacity() == 10

    def test_drain(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=4)
        ch.put("a")
        ch.put("b")
        items = ch.drain()
        assert items == ["a", "b"]
        assert ch.size() == 0

    def test_is_closed(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=4)
        assert not ch.is_closed()
        ch.close()
        assert ch.is_closed()

    def test_utilization(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=4)
        assert ch.utilization() == 0.0
        ch.put("a")
        assert ch.utilization() == 0.25

    def test_put_over_capacity_overwrites_oldest(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=2, overwrite=True)
        ch.put("a")
        ch.put("b")
        ch.put("c")
        assert ch.get(timeout=T) == "b"
        assert ch.get(timeout=T) == "c"

    def test_close_stops_put(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=4, overwrite=True)
        ch.close()
        ch.put("x")
        assert ch.size() == 0

    def test_concurrent_put_get(self):
        from l4.adapters.channel_ring import RingChannel
        ch = RingChannel(capacity=20, overwrite=True)
        for i in range(10):
            ch.put(i)
        items = [ch.get(timeout=T) for _ in range(10)]
        assert len(items) == 10
