"""EventBus tests — SignalType, emit, on, off, history, wildcard."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestSignalType:
    def test_builtin_signals(self):
        from l1.kernel.event import SignalType
        assert SignalType.TASK_ASSIGN.name == "TASK_ASSIGN"
        assert SignalType.TOKEN_USAGE.name == "TOKEN_USAGE"
        assert SignalType.SCOUT_DONE.name == "SCOUT_DONE"

    def test_register_signal_type(self):
        from l1.kernel.event import register_signal_type, SignalType
        name = "TEST_CUSTOM"
        st = register_signal_type(name)
        assert st.name == name


class TestEventBus:
    def test_get_event_bus(self):
        from l1.kernel import get_event_bus
        bus = get_event_bus()
        assert bus is not None

    def test_on_and_emit(self):
        from l1.kernel import get_event_bus, SignalType, Signal
        bus = get_event_bus()
        captured = []
        bus.on(SignalType.TASK_ASSIGN, lambda s: captured.append(s.sender))
        n = bus.emit(Signal(type=SignalType.TASK_ASSIGN, sender="test-a", target="cell"))
        assert n >= 1
        assert "test-a" in captured

    def test_off(self):
        from l1.kernel import get_event_bus, SignalType, Signal
        bus = get_event_bus()
        captured = []
        def handler(s): captured.append(s.sender)
        bus.on(SignalType.SCOUT_DONE, handler)
        bus.emit(Signal(type=SignalType.SCOUT_DONE, sender="s1", target="cell"))
        assert "s1" in captured
        bus.off(SignalType.SCOUT_DONE, handler)
        captured.clear()
        bus.emit(Signal(type=SignalType.SCOUT_DONE, sender="s2", target="cell"))
        assert len(captured) == 0

    def test_wildcard_listener(self):
        from l1.kernel import get_event_bus, SignalType, Signal
        bus = get_event_bus()
        caught = []
        bus.on_any(lambda s: caught.append(s.type.name))
        bus.emit(Signal(type=SignalType.STATE_CHANGE, sender="a", target="b"))
        assert "STATE_CHANGE" in caught

    def test_history(self):
        from l1.kernel import get_event_bus, SignalType, Signal
        bus = get_event_bus()
        bus.emit(Signal(type=SignalType.TERRITORY_QUERY, sender="h", target="cell"))
        history = bus.history(limit=5)
        assert len(history) >= 1

    def test_repr(self):
        from l1.kernel.event import SignalType
        r = repr(SignalType.TASK_ASSIGN)
        assert "TASK_ASSIGN" in r
