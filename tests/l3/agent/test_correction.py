"""AgentLoop self-correction test — loop detector/todo tracker/verify cadence.

Lightweight smoke test: verify each detector module can be imported, initialized, and basic calls do not crash.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestAgentLoopInit:
    """AgentLoop creation and basic attributes"""

    def test_init(self):
        from l3.agent.agent_loop import AgentLoop
        loop = AgentLoop(task="test task", agent_id="test-agent",
                         system="You are a test agent.")
        assert loop is not None
        assert loop.agent_id == "test-agent"


class TestLoopDetectors:
    """Loop detector importable and initializable"""

    def test_tool_loop_detector_importable(self):
        from l3.agent.loop_detectors import ToolLoopDetector
        d = ToolLoopDetector()
        assert d is not None

    def test_tool_loop_detector_check_called(self):
        from l3.agent.loop_detectors import ToolLoopDetector
        d = ToolLoopDetector()
        result = d.check("read_file", {"path": "/x"}, {"data": "ok"})
        # Don't assume return type — just verify the call doesn't crash
        assert result is not None

    def test_coarse_repeat_detector_importable(self):
        from l3.agent.loop_detectors import CoarseRepeatDetector
        d = CoarseRepeatDetector()
        assert d is not None

    def test_coarse_repeat_detector_check_called(self):
        from l3.agent.loop_detectors import CoarseRepeatDetector
        d = CoarseRepeatDetector()
        result = d.check("read_file")
        assert result is not None


class TestTodoTracker:
    """TodoTracker initialization"""

    def test_todo_tracker_importable(self):
        from l3.services.todo_tracker import TodoTracker
        t = TodoTracker()
        assert t is not None

    def test_todo_tracker_has_todos(self):
        from l3.services.todo_tracker import TodoTracker
        t = TodoTracker()
        # TodoTracker uses update(), not list()
        result = t.update("sample task", "pending")
        assert isinstance(result, str) or result is not None

    def test_todo_tracker_stats(self):
        from l3.services.todo_tracker import TodoTracker
        t = TodoTracker()
        stats = t.stats()
        assert isinstance(stats, dict)


class TestVerifyCadence:
    """VerifyCadence importable and initializable"""

    def test_verify_cadence_importable(self):
        from l3.agent.verify_cadence import VerifyCadence
        vc = VerifyCadence()
        assert vc is not None

    def test_verify_cadence_check_called(self):
        from l3.agent.verify_cadence import VerifyCadence
        vc = VerifyCadence()
        # VerifyCadence uses nudge() and record_edit()
        vc.record_edit("/test/path")
        nudge = vc.nudge()
        assert nudge is None or isinstance(nudge, str)
