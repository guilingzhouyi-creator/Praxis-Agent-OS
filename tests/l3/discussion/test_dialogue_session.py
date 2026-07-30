"""DialogueSession + SessionExport 持久化测试。"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestDialogueSession:
    def test_init(self):
        from l3.dialogue_session import DialogueSession
        s = DialogueSession(agent_id="test-agent", task="test task")
        assert s is not None
        assert s.state is not None

    def test_start_transitions(self):
        from l3.dialogue_session import DialogueSession
        s = DialogueSession(agent_id="start-agent", task="start test")
        s.start()
        assert s.state.name == "ACTIVE"

    def test_record_turn(self):
        from l3.dialogue_session import DialogueSession
        s = DialogueSession(agent_id="turn-agent", task="turn test")
        s.start()
        s.record_turn("hello", "response ok", [])
        assert s.state.name == "ACTIVE"

    def test_complete(self):
        from l3.dialogue_session import DialogueSession
        s = DialogueSession(agent_id="complete-agent", task="complete test")
        s.start()
        s.complete()
        assert s.state.name == "COMPLETED"

    def test_push_context(self):
        from l3.dialogue_session import DialogueSession
        s = DialogueSession(agent_id="ctx-agent", task="ctx test")
        s.start()
        s.push_context("observation", "test context")
        assert True


class TestSessionExport:
    def test_export_dataclass(self):
        from l3.session_export import SessionExport
        se = SessionExport(session_id="sess-1", agent_id="agent-x")
        d = se.to_dict()
        assert isinstance(d, dict)
        assert d["session_id"] == "sess-1"
        assert d["agent_id"] == "agent-x"

    def test_export_with_messages(self):
        from l3.session_export import SessionExport
        se = SessionExport(session_id="sess-2", agent_id="agent-y",
                           messages=[{"role": "user", "content": "hello"}],
                           turn_count=1)
        assert len(se.messages) == 1
