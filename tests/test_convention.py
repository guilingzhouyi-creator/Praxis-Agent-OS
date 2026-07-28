"""Convention protocol tests — round management, transcripts, speaker order."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestConventionData:
    def test_transcript_create(self):
        from l3.card.convention import ConventionTranscript
        t = ConventionTranscript(speaker="agent-a", target="agent-b", statement="Why?")
        assert t.speaker == "agent-a"
        assert t.target == "agent-b"
        assert t.statement == "Why?"

    def test_round_create(self):
        from l3.card.convention import ConventionRound
        r = ConventionRound(round_num=1, speaker_order=["a", "b", "c"])
        assert r.round_num == 1
        assert r.speaker_order == ["a", "b", "c"]
        assert r.current_index == 0

    def test_next_speaker(self):
        from l3.card.convention import ConventionRound
        r = ConventionRound(round_num=1, speaker_order=["a", "b", "c"])
        idx = r.current_index
        assert r.speaker_order[idx] == "a"

    def test_add_transcript(self):
        from l3.card.convention import ConventionRound, ConventionTranscript
        r = ConventionRound(round_num=1, speaker_order=["a"])
        r.transcripts.append(ConventionTranscript(speaker="a", target="b", statement="test"))
        assert len(r.transcripts) == 1

    def test_max_rounds_constant(self):
        from l1.kernel.params.agent import CONVENTION_MAX_ROUNDS
        assert CONVENTION_MAX_ROUNDS >= 1

    def test_max_agents_constant(self):
        from l1.kernel.params.agent import CONVENTION_MAX_AGENTS
        assert CONVENTION_MAX_AGENTS >= 3
