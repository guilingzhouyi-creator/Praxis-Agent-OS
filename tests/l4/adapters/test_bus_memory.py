"""Adapter: MemoryBusAdapter tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMemoryBusAdapter:
    """MemoryBusAdapter — emit/subscribe/unsubscribe/stats/clear."""

    def test_subscribe_and_emit(self):
        from l1.kernel.event import Signal, SignalType
        from l4.adapters.bus_memory import MemoryBusAdapter
        bus = MemoryBusAdapter()
        received = []

        def handler(sig):
            received.append(sig)

        # pattern=None subscribes to ALL events
        sub_id = bus.subscribe(handler=handler)
        bus.emit(Signal(type=SignalType.TASK_ASSIGN, data={"msg": "hello"}))
        assert len(received) == 1

    def test_unsubscribe(self):
        from l1.kernel.event import Signal, SignalType
        from l4.adapters.bus_memory import MemoryBusAdapter
        bus = MemoryBusAdapter()
        received = []

        def handler(sig):
            received.append(sig)

        sub_id = bus.subscribe(handler=handler)
        bus.unsubscribe(sub_id)
        bus.emit(Signal(type=SignalType.TASK_ASSIGN, data={"msg": "gone"}))
        assert len(received) == 0

    def test_subscribe_returns_string_id(self):
        from l4.adapters.bus_memory import MemoryBusAdapter
        bus = MemoryBusAdapter()
        sub_id = bus.subscribe()
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0

    def test_stats(self):
        from l4.adapters.bus_memory import MemoryBusAdapter
        bus = MemoryBusAdapter()
        st = bus.stats()
        assert isinstance(st, dict)

    def test_clear(self):
        from l4.adapters.bus_memory import MemoryBusAdapter
        bus = MemoryBusAdapter()
        bus.clear()
        st = bus.stats()
        assert isinstance(st, dict)
