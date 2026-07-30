"""Tests for memory_quality.py — memory quality heuristics module."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def test_score_importance():
    from l3.memory.memory_quality import _score_importance
    s = _score_importance("fixed bug in login route, changed port from 8080 to 3000", "decision")
    assert 0.0 <= s <= 1.0
    assert s > 0.5  # decision + path + port → high score


def test_is_good_memory():
    from l3.memory.memory_quality import _is_good_memory
    ok, reason = _is_good_memory("specific fix: updated config.py line 42", "observation")
    assert ok, f"expected good, got: {reason}"


def test_is_good_memory_vague():
    from l3.memory.memory_quality import _is_good_memory
    ok, reason = _is_good_memory("there is a file", "observation")
    assert not ok, "should reject vague"


def test_is_good_memory_too_short():
    from l3.memory.memory_quality import _is_good_memory
    ok, reason = _is_good_memory("hi", "observation")
    assert not ok, "should reject too short"


def test_is_good_memory_always_save():
    from l3.memory.memory_quality import _is_good_memory
    ok, reason = _is_good_memory("anything", "decision")
    assert ok, "decision type always saves"


def test_suggest_compact():
    from l3.memory.memory_quality import _suggest_compact
    class MockEntry:
        def __init__(self, eid, agent, tags, content):
            self.id = eid; self.agent_id = agent; self.tags = tags; self.content = content
    entries = [MockEntry("e1", "agent-a", ["test"], "a"), MockEntry("e2", "agent-a", ["test"], "b"),
               MockEntry("e3", "agent-a", ["test"], "c")]
    suggestions = _suggest_compact(entries)
    assert len(suggestions) >= 1
    assert suggestions[0]["agent_id"] == "agent-a"


def test_import_module():
    from l3.memory.memory_quality import _MIN_CONTENT_LEN, _ALWAYS_SAVE
    assert _MIN_CONTENT_LEN == 30
    assert "decision" in _ALWAYS_SAVE
