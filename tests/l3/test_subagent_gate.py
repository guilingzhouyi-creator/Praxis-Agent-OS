"""Tests for subagent_gate.py — card type classification + spec builder."""
from __future__ import annotations

from l3.agent.subagent_gate import classify_card, build_spec


def test_classify_explore_empty():
    """An empty or no-phase card is classified as 'explore'."""
    assert classify_card({"phases": []}) == "explore"


def test_classify_explore_read_tools():
    """A card with only read tools is 'explore'."""
    from dataclasses import dataclass, field
    @dataclass
    class DummyTask:
        action: str = ""
        agent: str = ""

    @dataclass
    class DummyPhase:
        tasks: list = field(default_factory=list)

    card = {"phases": [DummyPhase(tasks=[DummyTask(action="read_file")])]}
    assert classify_card(card) == "explore"


def test_classify_execute_write_tool():
    """A card with a write tool is 'execute'."""
    from dataclasses import dataclass, field
    @dataclass
    class DummyTask:
        action: str = ""

    @dataclass
    class DummyPhase:
        tasks: list = field(default_factory=list)

    card = {"phases": [DummyPhase(tasks=[DummyTask(action="write_file")])]}
    assert classify_card(card) == "execute"


def test_classify_execute_writer_role():
    """A card with a 'writer' role agent is 'execute'."""
    from dataclasses import dataclass, field
    @dataclass
    class DummyTask:
        action: str = ""
        agent: str = ""

    @dataclass
    class DummyPhase:
        tasks: list = field(default_factory=list)

    card = {"phases": [DummyPhase(tasks=[DummyTask(action="read_file", agent="writer")])]}
    assert classify_card(card) == "execute"


def test_build_spec_explore():
    """build_spec('explore') returns a read-only spec with 5 max_steps."""
    spec = build_spec("explore", spec_name="test-explorer")
    assert spec.read_only is True
    assert spec.max_steps == 5
    assert spec.name == "test-explorer"


def test_build_spec_execute():
    """build_spec('execute') returns a read-write spec with 10 max_steps."""
    spec = build_spec("execute", spec_name="test-executor")
    assert spec.read_only is False
    assert spec.max_steps == 10
    assert spec.name == "test-executor"


def test_build_spec_explore_default_name():
    """build_spec('explore') without spec_name uses default name."""
    spec = build_spec("explore")
    assert spec.name == "explore-assistant"
