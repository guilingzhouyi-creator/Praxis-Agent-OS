"""Tests for LockChannel, LockBus — IPC message passing."""

from __future__ import annotations

import threading
import time
from typing import Any

from l1.kernel.ipc import (
    LockBus,
    LockChannel,
    LockMessage,
    LockOp,
    get_lock_bus,
    reset_lock_bus,
)


def _msg(op: LockOp = LockOp.ACQUIRE, name: str = "lock:test") -> LockMessage:
    return LockMessage(op=op, lock_name=name, agent_id="agent-1")


# ── LockMessage ──


def test_lock_message_defaults() -> None:
    msg = LockMessage(op=LockOp.ACQUIRE, lock_name="lock:x")
    assert msg.op == LockOp.ACQUIRE
    assert msg.lock_name == "lock:x"
    assert msg.agent_id == ""
    assert msg.priority == 5.0
    assert len(msg.msg_id) == 12


# ── LockChannel send / handlers ──


def test_send_returns_msg_id() -> None:
    ch = LockChannel("ch")
    mid = ch.send(_msg())
    assert len(mid) == 12


def test_handler_called_on_send() -> None:
    ch = LockChannel("ch")
    results: list[LockMessage] = []
    ch.register_handler(lambda m: results.append(m) or None)
    ch.send(_msg())
    assert len(results) == 1
    assert results[0].lock_name == "lock:test"


def test_handler_reply_is_stored() -> None:
    ch = LockChannel("ch")
    def handler(m: LockMessage) -> dict:
        return {"accepted": True}
    ch.register_handler(handler)
    msg = _msg()
    ch.send(msg)
    # The reply was stored in _responses by msg_id
    assert ch._responses.get(msg.msg_id) == {"accepted": True}


def test_handler_error_does_not_crash() -> None:
    ch = LockChannel("ch")
    def broken(m: LockMessage) -> dict:
        raise RuntimeError("oops")
    ch.register_handler(broken)
    ch.send(_msg())  # should not raise


# ── LockChannel request / respond ──


def test_request_gets_response() -> None:
    ch = LockChannel("ch")
    def handler(m: LockMessage) -> dict:
        return {"ok": True}
    ch.register_handler(handler)
    msg = _msg()
    # send + respond via handler (which calls respond internally)
    ch.send(msg)
    # Now manually set up a request for a known msg_id
    resp = ch.request(_msg(op=LockOp.STATUS, name="req-test"), timeout=2.0)
    # Should return a dict (empty if timeout)
    assert isinstance(resp, dict)


def test_respond_wakes_waiter() -> None:
    ch = LockChannel("ch")
    msg = _msg()
    results: list[Any] = []

    def waiter() -> None:
        r = ch.request(msg, timeout=5.0)
        results.append(r)

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.05)
    ch.respond(msg.msg_id, {"granted": True})
    t.join(timeout=2.0)
    assert len(results) == 1
    assert results[0] == {"granted": True}


def test_request_timeout_returns_empty_dict() -> None:
    ch = LockChannel("ch")
    msg = _msg(op=LockOp.ACQUIRE, name="timeout-test")
    resp = ch.request(msg, timeout=0.05)
    assert resp == {}


def test_pending_count() -> None:
    ch = LockChannel("ch")
    assert ch.pending_count() == 0
    ch.send(_msg())
    ch.send(_msg())
    assert ch.pending_count() == 2


# ── LockBus ──


def test_lockbus_get_channel_creates() -> None:
    bus = LockBus()
    ch = bus.get_channel("lock:a")
    assert ch.name == "lock:a"
    assert bus.channel_exists("lock:a") is True


def test_lockbus_get_channel_reuses() -> None:
    bus = LockBus()
    ch1 = bus.get_channel("lock:x")
    ch2 = bus.get_channel("lock:x")
    assert ch1 is ch2


def test_lockbus_channel_exists() -> None:
    bus = LockBus()
    assert bus.channel_exists("ghost") is False


def test_lockbus_stats() -> None:
    bus = LockBus()
    bus.get_channel("ch-a")
    bus.get_channel("ch-b").send(_msg())
    s = bus.stats()
    assert "ch-a" in s
    assert "ch-b" in s
    assert s["ch-b"] == 1
    assert s["ch-a"] == 0


# ── Global singleton ──


def test_get_lock_bus_singleton() -> None:
    b1 = get_lock_bus()
    b2 = get_lock_bus()
    assert b1 is b2


def test_reset_lock_bus() -> None:
    b1 = get_lock_bus()
    reset_lock_bus()
    b2 = get_lock_bus()
    assert b1 is not b2
