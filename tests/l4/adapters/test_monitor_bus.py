"""Adapter: MonitorBusAdapter tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMonitorBusAdapter:
    """MonitorBusAdapter — emit, query."""

    def test_emit(self):
        from l4.adapters.monitor_bus import MonitorBusAdapter
        bus = MonitorBusAdapter()
        bus.emit(type_="test.metric", source="agent-x",
                 severity="info", message="hello", data={"value": 42})

    def test_query(self):
        from l4.adapters.monitor_bus import MonitorBusAdapter
        bus = MonitorBusAdapter()
        bus.emit(type_="cpu.usage", source="agent-x",
                 severity="info", message="cpu at 80", data={"percent": 80})
        results = bus.query("cpu.usage")
        assert isinstance(results, list)
