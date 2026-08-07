"""Tests for subagent_dispatcher.py — @mention parsing and task dispatch."""

from __future__ import annotations

from l3.agent.subagent_dispatcher import SubAgentDispatcher
from l3.agent.subagent_spec import BUILTIN_SUBAGENTS, SubAgentSpec


def test_dispatcher_creation():
    """SubAgentDispatcher can be created with builtin specs."""
    d = SubAgentDispatcher()
    assert d is not None
    assert len(d._specs) == len(BUILTIN_SUBAGENTS)


def test_register_spec():
    """A SubAgentSpec can be registered with the dispatcher."""
    d = SubAgentDispatcher()
    spec = SubAgentSpec(name="auditor", description="Security auditor")
    d.register_spec(spec)
    assert d._specs["auditor"].name == "auditor"


def test_register_multiple_specs():
    """Multiple specs can be registered."""
    d = SubAgentDispatcher()
    d.register_spec(SubAgentSpec(name="spec-a", description="A"))
    d.register_spec(SubAgentSpec(name="spec-b", description="B"))
    assert "spec-a" in d._specs
    assert "spec-b" in d._specs


def test_get_spec_by_name():
    """A spec can be retrieved by its @mention name."""
    d = SubAgentDispatcher()
    d.register_spec(SubAgentSpec(name="helper", description="Helper agent"))
    spec = d._specs.get("helper")
    assert spec is not None
    assert spec.name == "helper"


def test_get_spec_not_found():
    """_specs returns None for unknown names."""
    d = SubAgentDispatcher()
    assert d._specs.get("nonexistent") is None


def test_list_specs():
    """list_specs returns all registered spec names."""
    d = SubAgentDispatcher()
    d.register_spec(SubAgentSpec(name="alpha", description="Alpha"))
    d.register_spec(SubAgentSpec(name="beta", description="Beta"))
    r = d.list_specs()
    assert "alpha" in r["specs"]
    assert "beta" in r["specs"]


def test_parse_mention():
    """@mention strings are parsed correctly."""
    d = SubAgentDispatcher()
    mentions = d.parse_mentions("@security-auditor")
    assert len(mentions) == 1
    assert mentions[0][0] == "security-auditor"


def test_parse_mention_no_match():
    """Strings without a known @mention return no matches."""
    d = SubAgentDispatcher()
    assert d.parse_mentions("plain text") == []
