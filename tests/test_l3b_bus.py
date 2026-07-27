"""Tests for l3b_bus.py — L3B communication bus."""
from __future__ import annotations

from l3.l3b_bus import get_bus, reset_bus, L3BMessageType


def setup_method():
    reset_bus()


def test_bus_register():
    """A composite can be registered on the bus."""
    reset_bus()
    bus = get_bus()
    r = bus.register("l3b-test-a-b")
    assert r["success"]
    assert "l3b-test-a-b" in r["composite_id"]


def test_bus_send_adjacent():
    """Adjacent composites can communicate directly."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-cell-1-cell-2")
    bus.register("l3b-cell-2-cell-3")
    r = bus.send("l3b-cell-1-cell-2", "l3b-cell-2-cell-3", L3BMessageType.HEARTBEAT, {"ping": True})
    assert r["success"]


def test_bus_read():
    """Reading from a mailbox returns sent messages."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-cell-1-cell-2")
    bus.send("l3b-cell-1-cell-2", "l3b-cell-1-cell-2", L3BMessageType.CARD_FORWARD, {"task": "test"})
    msgs = bus.read("l3b-cell-1-cell-2", limit=5)
    assert len(msgs) >= 1
    assert msgs[0]["msg_type"] == "CARD_FORWARD"


def test_bus_stats():
    """Bus has readable statistics."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-test-x-y")
    stats = bus.stats()
    assert "registered_composites" in stats
    assert stats["registered_composites"] >= 1


def test_bus_send_backpressure():
    """BACKPRESSURE signal can be sent between composites."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-a-b")
    bus.register("l3b-b-c")
    r = bus.send_backpressure("l3b-a-b", "l3b-b-c", reason="queue full")
    assert r["success"]
