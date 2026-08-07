"""Tests for HTN-B / L3B bus / L3B message pool — cross-cell routing infra."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestHTNB:
    def test_create_htn_b(self):
        from l3.bus.htn_b import create_htn_b

        planner = create_htn_b("cell-1", "cell-2")
        assert planner is not None
        assert "cell-1" in planner.name
        assert "cell-2" in planner.name

    def test_route_forward(self):
        from l3.bus.htn_b import _decompose_route_forward
        from l3.bus.htn_planner import Task, TaskType

        root = Task(id="t1", name="route", task_type=TaskType.PRIMITIVE, domain="app")
        tasks = _decompose_route_forward(root, "cell-1", "cell-2")
        assert isinstance(tasks, list)
        assert len(tasks) >= 1

    def test_merge_result(self):
        from l3.bus.htn_b import _decompose_merge_result
        from l3.bus.htn_planner import Task, TaskType

        root = Task(id="t2", name="merge", task_type=TaskType.PRIMITIVE, domain="app")
        tasks = _decompose_merge_result(root, "cell-1", "cell-2")
        assert isinstance(tasks, list)


class TestL3BBus:
    def test_init(self):
        from l3.bus.l3b_bus import L3BBus

        bus = L3BBus()
        assert bus is not None

    def test_register_mailbox(self):
        from l3.bus.l3b_bus import L3BBus

        bus = L3BBus()
        bus.register("comp-1")
        bus.register("comp-1")  # idempotent

    def test_read_empty(self):
        from l3.bus.l3b_bus import L3BBus

        bus = L3BBus()
        bus.register("comp-a")
        msgs = bus.read("comp-a")
        assert isinstance(msgs, list)
        assert len(msgs) == 0

    def test_stats(self):
        from l3.bus.l3b_bus import L3BBus

        bus = L3BBus()
        bus.register("c1")
        s = bus.stats()
        assert isinstance(s, dict)

    def test_send_unknown_target(self):
        from l3.bus.l3b_bus import L3BBus, L3BMessageType

        bus = L3BBus()
        bus.register("comp-x")
        r = bus.send("comp-x", "ghost", L3BMessageType.STATUS_CHECK, {})
        assert not r.get("success")


class TestL3BMessagePool:
    def test_init(self):
        from l3.bus.l3b_message_pool import L3BMessagePool

        pool = L3BMessagePool("comp-test", hot_size=50)
        assert pool is not None

    def test_push_pop(self):
        from l3.bus.l3b_message_pool import L3BMessagePool

        pool = L3BMessagePool("comp-pop", hot_size=50)
        pool.push("msg-1", "CARD_FORWARD", "sender", "target", '{"data":1}')
        pool.push("msg-2", "CARD_FORWARD", "sender", "target", '{"data":2}')
        popped = pool.pop(limit=5)
        assert len(popped) >= 2

    def test_pop_empty(self):
        from l3.bus.l3b_message_pool import L3BMessagePool

        pool = L3BMessagePool("comp-empty", hot_size=10)
        popped = pool.pop(limit=5)
        assert isinstance(popped, list)
        assert len(popped) == 0

    def test_hot_usage(self):
        from l3.bus.l3b_message_pool import L3BMessagePool

        pool = L3BMessagePool("comp-usage", hot_size=10)
        usage = pool.hot_usage()
        assert isinstance(usage, float)
        assert 0.0 <= usage <= 1.0

    def test_peek(self):
        from l3.bus.l3b_message_pool import L3BMessagePool

        pool = L3BMessagePool("comp-peek", hot_size=10)
        pool.push("p1", "STATUS_CHECK", "a", "b", "{}")
        peeked = pool.peek(limit=5)
        assert isinstance(peeked, list)
        assert len(peeked) >= 1

    def test_stats(self):
        from l3.bus.l3b_message_pool import L3BMessagePool

        pool = L3BMessagePool("comp-stats", hot_size=10)
        s = pool.stats()
        assert isinstance(s, dict)
        assert "hot_size" in s
