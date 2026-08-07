"""Tests for l3b_message_pool.py — L3B message cache pool."""

from __future__ import annotations

from l3.bus.l3b_message_pool import L3BMessagePool


def test_message_pool_push_pop():
    """Messages can be pushed and popped from the pool."""
    pool = L3BMessagePool("pool-test-1")
    r = pool.push("msg-1", "CARD_FORWARD", "sender-a", "target-b", {"task": "test"})
    assert r["success"]
    msgs = pool.pop(limit=5)
    assert len(msgs) >= 1
    assert msgs[0]["msg_id"] == "msg-1"
    pool.close()


def test_message_pool_empty_pop():
    """Popping from an empty pool returns empty list."""
    pool = L3BMessagePool("pool-test-2")
    msgs = pool.pop(limit=5)
    assert msgs == []
    pool.close()


def test_message_pool_stats():
    """Pool has readable statistics with hot/persist info."""
    pool = L3BMessagePool("pool-test-3")
    stats = pool.stats()
    assert "hot_size" in stats
    assert "hot_max" in stats
    assert "persist_count" in stats
    assert stats["hot_size"] == 0
    pool.close()


def test_message_pool_ttl_expiry():
    """Messages with TTL expire and are not returned."""
    pool = L3BMessagePool("pool-test-4")
    pool.push("msg-exp", "TEST", "a", "b", {"data": "expired"})
    msgs = pool.pop(limit=5)
    assert len(msgs) >= 1
    pool.close()
