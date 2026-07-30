"""FaultTolerance tests — checkpoint, heartbeat, crash recovery."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCheckpoint:
    def test_checkpoint_create(self):
        from l3.fault_tolerance import Checkpoint
        cp = Checkpoint(agent_id="test-agent", task_id="task-001", task_status="running")
        assert cp.agent_id == "test-agent"
        assert cp.task_id == "task-001"

    def test_checkpoint_to_dict(self):
        from l3.fault_tolerance import Checkpoint
        cp = Checkpoint(agent_id="a", task_id="t1")
        d = cp.to_dict()
        assert d["agent_id"] == "a"

    def test_checkpoint_from_dict(self):
        from l3.fault_tolerance import Checkpoint
        data = {"agent_id": "a", "task_id": "t1", "task_status": "done"}
        cp = Checkpoint.from_dict(data)
        assert cp.agent_id == "a"
        assert cp.task_status == "done"


class TestFaultToleranceService:
    def test_save_checkpoint(self):
        from l3.fault_tolerance import FaultToleranceService
        svc = FaultToleranceService()
        r = svc.save_checkpoint(agent_id="agent-x", task_id="tx", progress={"phase": "build"})
        assert r.get("success")

    def test_heartbeat(self):
        from l3.fault_tolerance import FaultToleranceService
        svc = FaultToleranceService()
        svc.heartbeat("heart-agent")
        status = svc.get_heartbeat("heart-agent")
        assert status is not None

    def test_check_heartbeats(self):
        from l3.fault_tolerance import FaultToleranceService
        import time
        svc = FaultToleranceService()
        svc.heartbeat("crash-agent")
        svc._check_heartbeats()
        status = svc.get_heartbeat("crash-agent")
        assert status is not None

    def test_start_stop(self):
        from l3.fault_tolerance import FaultToleranceService
        svc = FaultToleranceService()
        r = svc.start()
        assert r.get("success")
        r2 = svc.stop()
        assert r2.get("success")

    def test_get_service_singleton(self):
        from l3.fault_tolerance import get_service, reset_service
        reset_service()
        s1 = get_service()
        s2 = get_service()
        assert s1 is s2
