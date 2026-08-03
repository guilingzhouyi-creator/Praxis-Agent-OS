"""DialogueSession — multi-turn dialogue tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestDialogueSession:
    def test_create_session(self):
        from l3.card.dialogue_session import DialogueSession, SessionConfig
        config = SessionConfig(max_turns=10, max_context_tokens=2048)
        session = DialogueSession(agent_id="test-agent", task="test", config=config)
        assert session.agent_id == "test-agent"

    def test_create_with_default_config(self):
        from l3.card.dialogue_session import DialogueSession
        session = DialogueSession(agent_id="test-agent", task="test")
        assert session.agent_id == "test-agent"
