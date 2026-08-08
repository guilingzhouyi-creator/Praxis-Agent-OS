"""Tests for skill disclosure depth, staged skills and the guidance engine."""

from __future__ import annotations

import pytest

from l1.kernel.skill import get_skill_manager, reset_skill_manager


@pytest.fixture(autouse=True)
def _reset_skills():
    """Isolate skill-manager state between tests (singleton pollution)."""
    reset_skill_manager()
    yield
    reset_skill_manager()


def _mk(name: str, **kw) -> None:
    """Create a skill programmatically (internal = no write-gate identity)."""
    defaults = {"description": "d", "prompt": "p"}
    defaults.update(kw)
    get_skill_manager().create(name=name, internal=True, **defaults)


class TestDisclosureNormalization:
    """Disclosure depth field: default full, invalid falls back full."""

    def test_default_full(self):
        _mk("disc-full")
        assert get_skill_manager().get("disc-full")["disclosure"] == "full"

    def test_invalid_falls_back_full(self):
        _mk("disc-bad", disclosure="banana")
        assert get_skill_manager().get("disc-bad")["disclosure"] == "full"

    def test_none_persisted(self):
        _mk("disc-none", disclosure="none")
        assert get_skill_manager().get("disc-none")["disclosure"] == "none"


class TestStagedSkills:
    """Quest-style stage state: per-session current/advance."""

    def test_current_stage_and_advance(self):
        _mk(
            "quest-a",
            stages=[
                {"id": "s1", "name": "One", "instructions": "do one"},
                {"id": "s2", "name": "Two", "instructions": "do two"},
            ],
        )
        sm = get_skill_manager()
        cur = sm.current_stage("quest-a", "sess-1")
        assert cur["staged"] and cur["stage_index"] == 0 and cur["next_stage"] == "s2"
        adv = sm.advance_stage("quest-a", "sess-1")
        assert adv["stage_index"] == 1 and adv["done"]
        assert sm.current_stage("quest-a", "sess-1")["stage_index"] == 1
        # A different session is unaffected (per-session state).
        assert sm.current_stage("quest-a", "sess-2")["stage_index"] == 0

    def test_unstaged(self):
        _mk("plain-a")
        assert get_skill_manager().current_stage("plain-a")["staged"] is False


class TestGuidanceGraph:
    """Guided-path engine: frontier unlock + prerequisite path + cycle check."""

    def test_frontier_and_path(self):
        _mk("g-kernel")
        _mk("g-sync", dependencies=["g-kernel"])
        _mk("g-ipc", dependencies=["g-sync"])
        sm = get_skill_manager()
        assert sm.guided_frontier(completed=[]) == ["g-kernel"]
        assert sm.guided_frontier(completed=["g-kernel"]) == ["g-kernel", "g-sync"]
        assert sm.guided_path("g-ipc") == ["g-kernel", "g-sync", "g-ipc"]

    def test_cycle_detection(self):
        _mk("c-a", dependencies=["c-b"])
        _mk("c-b", dependencies=["c-a"])
        r = get_skill_manager().validate_guidance_graph()
        assert r["acyclic"] is False and r["cycles"]

    def test_forward_next_field(self):
        _mk("f-one", next_skills=["f-two"])
        _mk("f-two")
        assert get_skill_manager().guided_path("f-two") == ["f-two"]
        r = get_skill_manager().validate_guidance_graph()
        assert r["acyclic"] is True
