"""Tests for Constitution engine — rules parsing, territory management, check/enforce."""

from __future__ import annotations

import os
import tempfile

from l1.kernel.constitution import (
    TerritoryConstitution,
    diff_territory,
    get_constitution,
    load_territory,
    merge_proposal,
    parse_territory,
    render_territory,
    reset_constitution,
    save_territory,
    update_territory,
)

# ═══════════════════════════════════════════════════════════════════
# TerritoryConstitution
# ═══════════════════════════════════════════════════════════════════


class TestTerritoryConstitution:
    def test_default_values(self):
        tc = TerritoryConstitution()
        assert tc.territories == {}
        assert tc.version == 1
        assert tc.default_reputation > 0
        assert tc.token_budget > 0

    def test_is_blank_true(self):
        tc = TerritoryConstitution()
        assert tc.is_blank()

    def test_is_blank_false(self):
        tc = TerritoryConstitution()
        tc.territories["agent_a"] = ["src/"]
        assert not tc.is_blank()


# ═══════════════════════════════════════════════════════════════════
# parse_territory / render_territory
# ═══════════════════════════════════════════════════════════════════


class TestParseTerritory:
    def test_parse_minimal(self):
        text = "# Version: 1\n# Defaults\ndefault_reputation: 0.85\ntoken_budget: 73000\n"
        tc = parse_territory(text)
        assert tc.version == 1
        assert tc.territories == {}

    def test_parse_with_agents(self):
        text = """# Version: 1
G1: allowed_tools
G5: report_decision
# Defaults
default_reputation: 0.85
token_budget: 73000

agent_alpha: src/, docs/
agent_beta: tests/
"""
        tc = parse_territory(text)
        assert "agent_alpha" in tc.territories
        assert "agent_beta" in tc.territories

    def test_parse_with_gate_rules(self):
        text = """# Version: 1
G1: allowed_tools
G3: territory_check
G5: report_decision
# Defaults
default_reputation: 0.85
token_budget: 73000
"""
        tc = parse_territory(text)
        assert tc.gate_rules.get("G1") == "allowed_tools"
        assert tc.gate_rules.get("G3") == "territory_check"

    def test_render_roundtrip(self):
        text = """# Version: 1
G1: allowed_tools
G5: report_decision
# Defaults
default_reputation: 0.85
token_budget: 73000

agent_alpha: src/
agent_beta: tests/
"""
        tc = parse_territory(text)
        rendered = render_territory(tc)
        assert "agent_alpha" in rendered
        assert "agent_beta" in rendered
        assert "0.85" in rendered
        assert "73000" in rendered


# ═══════════════════════════════════════════════════════════════════
# save_territory / load_territory
# ═══════════════════════════════════════════════════════════════════


class TestSaveLoadTerritory:
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "territory.yaml")
            tc = TerritoryConstitution()
            tc.territories["agent_a"] = ["src/"]
            tc.gate_rules["G1"] = "allowed_tools"
            save_territory(tc, path)
            assert os.path.exists(path)
            loaded = load_territory(path)
            assert loaded.territories == tc.territories
            assert loaded.gate_rules == tc.gate_rules


# ═══════════════════════════════════════════════════════════════════
# update_territory / merge_proposal / diff_territory
# ═══════════════════════════════════════════════════════════════════


class TestUpdateTerritory:
    def test_update_single(self):
        tc = TerritoryConstitution()
        r = update_territory(tc, "agent_x", ["src/"])
        assert r["success"]
        assert tc.territories["agent_x"] == ["src/"]
        assert tc.version == 2


class TestMergeProposal:
    def test_merge(self):
        tc = TerritoryConstitution()
        proposal = {"agent_a": ["src/"], "agent_b": ["tests/"]}
        r = merge_proposal(tc, proposal)
        assert r["success"]
        assert tc.territories["agent_a"] == ["src/"]
        assert "agent_b" in tc.territories


class TestDiffTerritory:
    def test_diff_added(self):
        old = TerritoryConstitution()
        old.territories["agent_a"] = ["src/"]
        new = TerritoryConstitution()
        new.territories["agent_a"] = ["src/", "docs/"]
        d = diff_territory(old, new)
        assert d["changed"]
        assert "agent_a" in d.get("changes", {})


# ═══════════════════════════════════════════════════════════════════
# Constitution — check / is_allowed
# ═══════════════════════════════════════════════════════════════════


class TestConstitution:
    def setup_method(self):
        reset_constitution()

    def test_get_constitution_singleton(self):
        c1 = get_constitution()
        c2 = get_constitution()
        assert c1 is c2

    def test_is_allowed_no_rules(self):
        c = get_constitution()
        r = c.is_allowed("read_file", "agent-a", target="/x")
        # Without any blocking rules, should be allowed
        assert r["allowed"]

    def test_is_allowed_returns_dict(self):
        c = get_constitution()
        r = c.is_allowed("write_file", "agent-b", target="/project/foo.py")
        assert isinstance(r, dict)
        assert "allowed" in r
        assert "decision" in r
        assert "blocks" in r

    def test_check_returns_list(self):
        c = get_constitution()
        reports = c.check("read_file", "agent-a", target="/x")
        assert isinstance(reports, list)

    def test_summary(self):
        c = get_constitution()
        s = c.summary()
        assert isinstance(s, str)
        assert "Constitution Rules" in s
        assert "MUST" in s

    def test_to_dict(self):
        c = get_constitution()
        d = c.to_dict()
        assert isinstance(d, dict)
        assert "rules" in d

    def test_rules_list(self):
        c = get_constitution()
        rules = c.rules_list()
        assert isinstance(rules, list)


class TestConstitutionRules:
    def setup_method(self):
        reset_constitution()

    def test_load_blank(self):
        c = get_constitution()
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("")
            path = f.name
        try:
            r = c.load(path)
            assert r["success"]
            s = c.summary()
            # summary() returns a human-readable string (LLM context), not a dict
            assert isinstance(s, str)
            assert "MUST" in s  # built-in rules remain after loading blank file
        finally:
            os.unlink(path)

    def test_load_minimal_markdown(self):
        c = get_constitution()
        text = """# NOMOS Constitution
# Version: 1

agent_alpha: src/
agent_beta: tests/

default_reputation: 0.85
token_budget: 73000
"""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(text)
            path = f.name
        try:
            r = c.load(path)
            assert r["success"]
            s = c.summary()
            assert isinstance(s, str)
            assert len(s) > 0
        finally:
            os.unlink(path)

    def test_clear_custom_rules(self):
        c = get_constitution()
        r = c.clear_custom_rules()
        assert r["success"]
