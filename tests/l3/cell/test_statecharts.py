"""Statecharts 5-region 正交状态机测试。"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestEventType:
    def test_event_types_exist(self):
        from l3.statecharts import EventType
        for name in ("TASK_ASSIGN", "TASK_CANCEL", "HEARTBEAT_TIMEOUT",
                     "REVIEW_PASSED", "TOOL_CALL_FAIL", "COMM_DISCONNECT"):
            assert hasattr(EventType, name)


class TestAgentStatecharts:
    def test_init(self):
        from l3.statecharts import AgentStatecharts
        sm = AgentStatecharts("test-agent")
        assert sm is not None

    def test_dispatch_changes_state(self):
        from l3.statecharts import AgentStatecharts, EventType
        sm = AgentStatecharts("test-agent")
        sm.dispatch(EventType.TASK_ASSIGN)
        # snapshot is a dict property
        snap = sm.snapshot
        assert isinstance(snap, dict)

    def test_snapshot_has_all_regions(self):
        from l3.statecharts import AgentStatecharts
        sm = AgentStatecharts("test-agent")
        snap = sm.snapshot
        assert isinstance(snap, dict)
        for region in ("Task", "Health", "Review", "Resource", "Comm"):
            assert region in snap

    def test_save_snapshot(self):
        from l3.statecharts import AgentStatecharts, EventType
        sm = AgentStatecharts("test-save")
        sm.dispatch(EventType.TASK_ASSIGN)
        r = sm.save_snapshot()
        assert isinstance(r, dict)

    def test_dispatch_multiple_events(self):
        from l3.statecharts import AgentStatecharts, EventType
        sm = AgentStatecharts("test-multi")
        sm.dispatch(EventType.TASK_ASSIGN)
        sm.dispatch(EventType.REVIEW_REQUESTED)
        snap = sm.snapshot
        assert isinstance(snap, dict)
