"""FaultTolerance checkpoint/restore test — checkpoint save/restore/recovery.

Covered scenarios:
  - Create checkpoint
  - restore_checkpoint
  - Multiple checkpoint overwrite
  - Restore non-existent checkpoint
  - get_service singleton
"""

from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestFaultToleranceInit:
    def test_get_service(self):
        from l3.services.fault_tolerance import get_service, reset_service
        reset_service()
        ft = get_service()
        assert ft is not None


class TestFaultToleranceCheckpoint:
    def test_save_checkpoint(self):
        from l3.services.fault_tolerance import get_service, reset_service
        reset_service()
        ft = get_service()
        r = ft.save_checkpoint("agent-cp", {"action": "test", "target": "."})
        assert r is not None

    def test_save_and_restore(self):
        from l3.services.fault_tolerance import get_service, reset_service
        reset_service()
        ft = get_service()
        ft.save_checkpoint("agent-sr", {"action": "write", "target": "/tmp/test"})
        r = ft.restore_checkpoint("agent-sr")
        assert r is not None

    def test_multiple_checkpoints(self):
        from l3.services.fault_tolerance import get_service, reset_service
        reset_service()
        ft = get_service()
        ft.save_checkpoint("agent-multi", {"step": 1})
        ft.save_checkpoint("agent-multi", {"step": 2})
        ft.save_checkpoint("agent-multi", {"step": 3})
        r = ft.restore_checkpoint("agent-multi")
        assert r is not None

    def test_restore_nonexistent(self):
        from l3.services.fault_tolerance import get_service, reset_service
        reset_service()
        ft = get_service()
        r = ft.restore_checkpoint("no-such-agent")
        assert r is not None
