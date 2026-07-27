"""Tests for subagent_dispatcher.py — @mention parsing and task dispatch."""
from __future__ import annotations

import pytest
from l3.subagent_dispatcher import SubAgentDispatcher
from l3.subagent_spec import SubAgentSpec
from l3.subagent_task import SubAgentTask


def test_dispatcher_creation():
    """SubAgentDispatcher can be created with default state."""
    d = SubAgentDispatcher()
    assert d is not None
    assert len(d._specs) == 0


def test_register_spec():
    """A SubAgentSpec can be registered with the dispatcher."""
    d = SubAgentDispatcher()
    spec = SubAgentSpec(name="auditor", description="Security auditor")
    d.register_spec(spec)
    assert len(d._specs) == 1
    assert d._specs[0].name == "auditor"


def test_register_multiple_specs():
    """Multiple specs can be registered."""
    d = SubAgentDispatcher()
    d.register_spec(SubAgentSpec(name="spec-a", description="A"))
    d.register_spec(SubAgentSpec(name="spec-b", description="B"))
    assert len(d._specs) == 2


def test_get_spec_by_name():
    """A spec can be retrieved by its @mention name."""
    d = SubAgentDispatcher()
    d.register_spec(SubAgentSpec(name="helper", description="Helper agent"))
    spec = d.get_spec("helper")
    assert spec is not None
    assert spec.name == "helper"


def test_get_spec_not_found():
    """get_spec returns None for unknown names."""
    d = SubAgentDispatcher()
    assert d.get_spec("nonexistent") is None


def test_list_specs():
    """list_specs returns all registered spec names."""
    d = SubAgentDispatcher()
    d.register_spec(SubAgentSpec(name="alpha", description="Alpha"))
    d.register_spec(SubAgentSpec(name="beta", description="Beta"))
    names = d.list_specs()
    assert "alpha" in names
    assert "beta" in names


def test_parse_mention():
    """@mention strings are parsed correctly."""
    d = SubAgentDispatcher()
    result = d._parse_mention("@security-auditor")
    assert result == "security-auditor"


def test_parse_mention_no_match():
    """Strings without @ are returned as-is."""
    d = SubAgentDispatcher()
    result = d._parse_mention("plain text")
    assert result == "plain text"
