"""Agent persist — save/load agent state tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestAgentPersist:
    def test_save_snapshot_importable(self):
        from l3.agent.agent_persist import save_snapshot
        assert callable(save_snapshot)

    def test_append_transcript_importable(self):
        from l3.agent.agent_persist import append_transcript
        assert callable(append_transcript)
