"""Skill posture tests — productive vs offensive gating.

Covers:
  - frontmatter parsing: posture from SKILL.md (valid / invalid → default)
  - create() posture normalization (default-deny on invalid values)
  - list_skills exposes posture
  - _persist_skill_md round-trip frontmatter (posture written when offensive)
  - AgentLoop._inject_extra_context posture gate: offensive skills are only
    injected when the driving card nature authorizes them (L3A decision layer)
  - SkillCatalogHook never advertises offensive skills in the session catalog
"""

from __future__ import annotations

import os

import pytest

from l1.kernel.params.system import (
    SKILL_OFFENSIVE_AUTHORIZED_NATURES,
    SKILL_POSTURE_DEFAULT,
    SKILL_POSTURE_OFFENSIVE,
    SKILL_POSTURE_PRODUCTIVE,
)
from l1.kernel.skill import get_skill_manager


def _reset() -> None:
    from l1.kernel.skill import reset_skill_manager as _rsm

    _rsm()
    # R4Agent keeps a (revision-keyed) skill cache; resetting the manager
    # restarts the revision counter, so stale entries from a prior test can
    # collide. Clear the cache to keep tests isolated.
    try:
        from l3.memory.r4_agent import get_r4_agent

        get_r4_agent()._skill_cache.clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _skills():
    _reset()
    yield get_skill_manager()
    _reset()


def _write_skill(tmp_path, name: str, posture: str | None = None, extra: str = "") -> str:
    """Write a SKILL.md under tmp_path/skills/<name>/ and return its dir path."""
    d = tmp_path / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    meta = [f"name: {name}", "description: test skill", "disable-model-invocation: false"]
    if posture is not None:
        meta.append(f"posture: {posture}")
    body = f"\nYou are a test skill.\n{extra}\n"
    (d / "SKILL.md").write_text("---\n" + "\n".join(meta) + "\n---\n" + body, encoding="utf-8")
    return str(d)


class TestPostureSchema:
    def test_frontmatter_parses_offensive(self, tmp_path, _skills):
        sm = _skills
        sm.load_dir(_write_skill(tmp_path, "rev-lab", posture="offensive"))
        s = sm.get("rev-lab")
        assert s is not None
        assert s["posture"] == SKILL_POSTURE_OFFENSIVE

    def test_frontmatter_defaults_productive(self, tmp_path, _skills):
        sm = _skills
        sm.load_dir(_write_skill(tmp_path, "builder", posture=None))
        assert sm.get("builder")["posture"] == SKILL_POSTURE_PRODUCTIVE

    def test_frontmatter_invalid_falls_back(self, tmp_path, _skills):
        sm = _skills
        sm.load_dir(_write_skill(tmp_path, "weird", posture="super-dangerous"))
        assert sm.get("weird")["posture"] == SKILL_POSTURE_DEFAULT

    def test_create_normalizes_posture(self, _skills):
        sm = _skills
        sm.create(name="off1", description="d", prompt="p", posture="offensive", internal=True)
        sm.create(name="bad1", description="d", prompt="p", posture="totally-not-valid", internal=True)
        sm.create(name="plain", description="d", prompt="p", internal=True)
        assert sm.get("off1")["posture"] == SKILL_POSTURE_OFFENSIVE
        assert sm.get("bad1")["posture"] == SKILL_POSTURE_PRODUCTIVE
        assert sm.get("plain")["posture"] == SKILL_POSTURE_PRODUCTIVE

    def test_list_skills_exposes_posture(self, _skills):
        sm = _skills
        sm.create(name="off2", description="d", prompt="p", posture="offensive", internal=True)
        rows = sm.list_skills()
        by_name = {r["name"]: r for r in rows}
        assert by_name["off2"]["posture"] == SKILL_POSTURE_OFFENSIVE


class TestPosturePersistence:
    def test_persist_md_writes_posture_when_offensive(self, tmp_path):
        from l3.memory.r4_agent import R4Agent

        r4 = R4Agent()
        from l1.kernel.paths import get_paths as _gp

        base = _gp().skill_evolved_dir
        r4._persist_skill_md(
            name="rev-md", description="d", prompt="p", tags=["evolved"], posture="offensive", scope="global"
        )
        md = os.path.join(base, "rev-md", "SKILL.md")
        assert os.path.exists(md)
        with open(md, encoding="utf-8") as f:
            content = f.read()
        assert "posture: offensive" in content

    def test_persist_md_omits_default_posture(self, tmp_path):
        from l3.memory.r4_agent import R4Agent

        r4 = R4Agent()
        from l1.kernel.paths import get_paths as _gp

        base = _gp().skill_evolved_dir
        r4._persist_skill_md(name="plain-md", description="d", prompt="p", tags=["evolved"], scope="global")
        with open(os.path.join(base, "plain-md", "SKILL.md"), encoding="utf-8") as f:
            content = f.read()
        assert "posture:" not in content

    def test_persist_invalid_posture_falls_back(self, tmp_path):
        from l3.memory.r4_agent import R4Agent

        r4 = R4Agent()
        from l1.kernel.paths import get_paths as _gp

        base = _gp().skill_evolved_dir
        r4._persist_skill_md(
            name="bad-md", description="d", prompt="p", tags=["evolved"], posture="hax", scope="global"
        )
        with open(os.path.join(base, "bad-md", "SKILL.md"), encoding="utf-8") as f:
            content = f.read()
        assert "posture:" not in content


class TestAgentLoopPostureGate:
    """Offensive skills must not be injected unless the card nature authorizes them."""

    def _mk_loop(self, nature: str = ""):
        from l3.agent.agent_loop import AgentLoop
        from l3.memory.r4_agent import R4Agent

        R4Agent()
        loop = AgentLoop.__new__(AgentLoop)
        loop.agent_id = "agent-x"
        loop._cell_id = ""
        loop._pmu = None
        loop._card_nature = nature
        loop._card_tags = []
        return loop

    def test_offensive_skill_not_injected_by_default(self, _skills):
        sm = _skills
        sm.create(
            name="rev-helper", description="d", prompt="attack helper",
            tags=["evolved", "agent-x"], posture="offensive", internal=True,
        )
        out = self._mk_loop(nature="")._inject_extra_context("base")
        assert "rev-helper" not in out

    def test_offensive_skill_injected_when_card_nature_authorizes(self, _skills):
        sm = _skills
        sm.create(
            name="rev-helper2", description="d", prompt="attack helper",
            tags=["evolved", "agent-x"], posture="offensive", internal=True,
        )
        out = self._mk_loop(nature=SKILL_OFFENSIVE_AUTHORIZED_NATURES[0])._inject_extra_context("base")
        assert "rev-helper2" in out

    def test_productive_skill_injected_regardless(self, _skills):
        sm = _skills
        sm.create(
            name="plain-helper", description="d", prompt="build helper",
            tags=["evolved", "agent-x"], posture="productive", internal=True,
        )
        out = self._mk_loop(nature="")._inject_extra_context("base")
        assert "plain-helper" in out


class TestSkillCatalogHookPosture:
    def test_offensive_skill_not_in_catalog(self, _skills):
        from l3.services.hook import SkillCatalogHook

        sm = _skills
        sm.create(
            name="rev-cat", description="d", prompt="p", tags=["evolved"], posture="offensive", internal=True,
        )
        sm.create(
            name="plain-cat", description="d", prompt="p", tags=["evolved"], posture="productive", internal=True,
        )
        out = SkillCatalogHook().session_start("task", "agent-x")
        assert "rev-cat" not in out
        assert "plain-cat" in out


class TestOffensivePolicy:
    """Runtime offensive-policy: default-deny + configurable natures + soft bypass."""

    def test_default_policy_enabled(self, _skills):
        pol = _skills.offensive_policy()
        assert pol["enabled"] is True
        assert pol["natures"] == ["offensive"]

    def test_authorized_only_for_allowed_natures(self, _skills):
        assert _skills.offensive_authorized("offensive") is True
        assert _skills.offensive_authorized("build") is False
        assert _skills.offensive_authorized("") is False

    def test_set_natures_replaces_allowlist(self, _skills):
        _skills.set_offensive_policy(natures=["redteam", "offensive"])
        assert _skills.offensive_authorized("redteam") is True
        assert _skills.offensive_authorized("offensive") is True
        assert _skills.offensive_authorized("build") is False

    def test_disable_bypasses_gate(self, _skills):
        _skills.set_offensive_policy(enabled=False)
        assert _skills.offensive_authorized("") is True
        assert _skills.offensive_authorized("anything") is True

    def test_enable_restores_gate(self, _skills):
        _skills.set_offensive_policy(enabled=False)
        assert _skills.offensive_authorized("") is True
        _skills.set_offensive_policy(enabled=True)
        assert _skills.offensive_authorized("") is False


class TestRuntimeToggle:
    """AgentLoop injection + catalog react to the runtime policy switch."""

    def _mk_loop(self, nature: str = ""):
        from l3.agent.agent_loop import AgentLoop
        from l3.memory.r4_agent import R4Agent

        R4Agent()
        loop = AgentLoop.__new__(AgentLoop)
        loop.agent_id = "agent-x"
        loop._cell_id = ""
        loop._pmu = None
        loop._card_nature = nature
        loop._card_tags = []
        return loop

    def test_offensive_blocked_when_enabled(self, _skills):
        _skills.create(
            name="rev-t", description="d", prompt="attack helper",
            tags=["evolved", "agent-x"], posture="offensive", internal=True,
        )
        out = self._mk_loop(nature="")._inject_extra_context("base")
        assert "rev-t" not in out

    def test_offensive_injected_when_disabled(self, _skills):
        _skills.create(
            name="rev-t2", description="d", prompt="attack helper",
            tags=["evolved", "agent-x"], posture="offensive", internal=True,
        )
        _skills.set_offensive_policy(enabled=False)
        out = self._mk_loop(nature="")._inject_extra_context("base")
        assert "rev-t2" in out

    def test_catalog_hides_offensive_when_enabled(self, _skills):
        from l3.services.hook import SkillCatalogHook

        _skills.create(name="rev-c1", description="d", prompt="p", tags=["evolved"], posture="offensive", internal=True)
        _skills.create(name="plain-c1", description="d", prompt="p", tags=["evolved"], internal=True)
        out = SkillCatalogHook().session_start("task", "agent-x")
        assert "rev-c1" not in out
        assert "plain-c1" in out

    def test_catalog_shows_offensive_when_disabled(self, _skills):
        from l3.services.hook import SkillCatalogHook

        _skills.create(name="rev-c2", description="d", prompt="p", tags=["evolved"], posture="offensive", internal=True)
        _skills.set_offensive_policy(enabled=False)
        # The constitution §9.2 gate is the highest authority: even with the
        # skill-layer policy disabled, offensive skills are only advertised
        # when the system posture is full-power attack.
        from l1.kernel.constitution import set_posture_provider
        from l3.tool_system.security_mode import get_posture, set_security_mode

        set_posture_provider(get_posture)
        set_security_mode("security-test", confirmed=True)
        out = SkillCatalogHook().session_start("task", "agent-x")
        assert "rev-c2" in out


class TestUseSkillPostureGate:
    """use_skill refuses offensive skills without card authorization."""

    def test_offensive_refused_without_nature(self, _skills):
        from l3.tools._skills import use_skill

        _skills.create(name="rev-u1", description="d", prompt="attack helper", posture="offensive", internal=True)
        r = use_skill({"name": "rev-u1"}, "agent-x")
        assert not r["success"]
        assert "offensive-posture" in r["error"]

    def test_offensive_allowed_with_authorized_nature(self, _skills):
        from l3.tools._skills import use_skill

        _skills.create(name="rev-u2", description="d", prompt="attack helper", posture="offensive", internal=True)
        r = use_skill({"name": "rev-u2", "_card_nature": "offensive"}, "agent-x")
        assert r["success"]

    def test_offensive_allowed_when_gate_disabled(self, _skills):
        from l3.tools._skills import use_skill

        _skills.create(name="rev-u3", description="d", prompt="attack helper", posture="offensive", internal=True)
        _skills.set_offensive_policy(enabled=False)
        r = use_skill({"name": "rev-u3"}, "agent-x")
        assert r["success"]


class TestOffensivePolicyApi:
    """GET/POST /api/skills/offensive-policy handlers."""

    def test_get_policy(self, _skills):
        from l4.api_handlers.api_handlers_skills import handle_skills_offensive_policy_get

        r = handle_skills_offensive_policy_get()
        assert r["success"]
        assert r["policy"]["enabled"] is True

    def test_post_policy_developer_only(self, _skills):
        from l4.api_handlers.api_handlers_skills import handle_skills_offensive_policy_set

        # No identity → refused by the developer write gate.
        r = handle_skills_offensive_policy_set({"enabled": False})
        assert not r["success"]
        assert "permission denied" in r["error"]

    def test_post_policy_applies(self, _skills):
        from l4.api_handlers.api_handlers_skills import handle_skills_offensive_policy_set

        r = handle_skills_offensive_policy_set({"enabled": False, "agent_id": "l3a", "role": "l3"})
        assert r["success"]
        assert r["enabled"] is False
        # Runtime effect: gate bypassed.
        assert _skills.offensive_authorized("") is True
