"""Skill audience routing tests — domain-based dynamic supply.

Strategy skills (L3A central) vs execution skills (Cell peer agents) vs
universal (system knowledge). Skills are supplied on demand via
use_skill/list_skills within the agent's own domain, not blanket-injected.
"""

from __future__ import annotations

import pytest

from l1.kernel.skill import (
    SkillManager,
    audience_of,
    get_skill_manager,
    reset_skill_manager,
    skill_visible,
)
from l3.tools._skills import list_skills, use_skill


@pytest.fixture(autouse=True)
def _skills():
    reset_skill_manager()
    sm = get_skill_manager()
    sm.load_dir("config/skills")
    yield sm
    reset_skill_manager()


class TestAudience:
    def test_audience_of(self):
        assert audience_of("l3a") == "strategy"
        assert audience_of("agent-http") == "execution"
        assert audience_of("agent-reader") == "execution"

    def test_untagged_is_universal(self, _skills):
        card = _skills.get("card")
        assert skill_visible(card, "l3a") is True
        assert skill_visible(card, "agent-http") is True

    def test_tagged_split(self, _skills):
        grill = _skills.get("grill-me")
        tdd = _skills.get("tdd")
        assert skill_visible(grill, "l3a") is True
        assert skill_visible(grill, "agent-http") is False
        assert skill_visible(tdd, "agent-http") is True
        assert skill_visible(tdd, "l3a") is False


class TestListSkills:
    def test_l3a_sees_strategy_not_execution(self):
        r = list_skills({}, "l3a")
        assert r["success"]
        names = {s["name"] for s in r["skills"]}
        assert {"grill-me", "handoff", "writing-for-agents"} <= names
        assert "tdd" not in names
        assert "code-review" not in names

    def test_cell_sees_execution_not_strategy(self):
        r = list_skills({}, "agent-http")
        names = {s["name"] for s in r["skills"]}
        assert {"tdd", "code-review", "diagnosing-bugs",
                "domain-modeling", "resolving-merge-conflicts"} <= names
        assert "grill-me" not in names
        assert "handoff" not in names

    def test_universal_visible_to_both(self):
        r1 = {s["name"] for s in list_skills({}, "l3a")["skills"]}
        r2 = {s["name"] for s in list_skills({}, "agent-http")["skills"]}
        assert "card" in r1 and "card" in r2
        assert "kernel" in r1 and "kernel" in r2


class TestUseSkill:
    def test_cross_domain_refused(self):
        r = use_skill({"name": "tdd"}, "l3a")
        assert not r["success"]
        assert "strategy domain" in r["error"]
        r2 = use_skill({"name": "grill-me"}, "agent-http")
        assert not r2["success"]
        assert "execution domain" in r2["error"]

    def test_within_domain_allowed(self):
        r = use_skill({"name": "grill-me"}, "l3a")
        assert r["success"]
        assert "interviewer" in r["prompt"]
        r2 = use_skill({"name": "tdd"}, "agent-http")
        assert r2["success"]
        assert "red" in r2["prompt"]

    def test_universal_allowed_everywhere(self):
        assert use_skill({"name": "card"}, "l3a")["success"]
        assert use_skill({"name": "card"}, "agent-http")["success"]

    def test_unknown_skill(self):
        r = use_skill({"name": "nope"}, "l3a")
        assert not r["success"]
