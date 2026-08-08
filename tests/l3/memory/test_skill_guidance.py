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


class TestStageTodoLinkage:
    """Stage ↔ TODO linkage: materialize, verified → advance, no-ops."""

    def _staged(self) -> None:
        _mk(
            "quest-x",
            stages=[
                {"id": "a", "instructions": "A", "completion": "do A"},
                {"id": "b", "instructions": "B", "completion": "do B"},
            ],
        )

    def test_materialize_and_advance_on_verified(self, tmp_path):
        from l3.memory.skill_guidance import advance_on_stage_todo_verified, materialize_stage_todo
        from l3.services.todo_tracker import TodoTracker

        self._staged()
        sm = get_skill_manager()
        # Isolated state file: an empty state_path would fall back to the
        # global data_dir/todo_state.json and restore cross-run state.
        todo = TodoTracker(state_path=str(tmp_path / "todo.json"))
        r = materialize_stage_todo(todo, sm, "quest-x", "sess")
        assert r["materialized"] and r["status"] == "pending"
        assert r["todo"].startswith("[skill:quest-x:a]")
        # Idempotent re-materialization.
        assert materialize_stage_todo(todo, sm, "quest-x", "sess")["status"] == "pending"
        # Not yet verified → no advance.
        assert advance_on_stage_todo_verified(todo, sm, r["todo"], "sess")["advanced"] == 0
        todo.update(r["todo"], "verified")
        adv = advance_on_stage_todo_verified(todo, sm, r["todo"], "sess")
        assert adv["advanced"] == 1
        assert sm.current_stage("quest-x", "sess")["stage"]["id"] == "b"

    def test_non_stage_todo_never_advances(self, tmp_path):
        from l3.memory.skill_guidance import advance_on_stage_todo_verified
        from l3.services.todo_tracker import TodoTracker

        todo = TodoTracker(state_path=str(tmp_path / "todo.json"))
        todo.update("plain task", "add")
        todo.update("plain task", "verified")
        assert advance_on_stage_todo_verified(todo, get_skill_manager(), "plain task", "s")["advanced"] == 0

    def test_unstaged_skill_not_materialized(self, tmp_path):
        from l3.memory.skill_guidance import materialize_stage_todo
        from l3.services.todo_tracker import TodoTracker

        _mk("plain-y")
        r = materialize_stage_todo(
            TodoTracker(state_path=str(tmp_path / "todo.json")), get_skill_manager(), "plain-y", "s"
        )
        assert r["materialized"] is False


class TestGuidanceModes:
    """Guidance operating mode: small (fields inert) vs full (atomic chains)."""

    def _staged(self) -> None:
        _mk(
            "mode-x",
            stages=[
                {"id": "a", "instructions": "A", "completion": "do A"},
                {"id": "b", "instructions": "B", "completion": "do B"},
            ],
        )

    def test_full_mode_default_stage_active(self):
        self._staged()
        sm = get_skill_manager()
        assert sm.guidance_policy()["mode"] == "full"
        assert sm.current_stage("mode-x", "s")["staged"] is True

    def test_small_mode_stages_inert(self):
        self._staged()
        sm = get_skill_manager()
        sm.set_guidance_policy(mode="small")
        assert sm.current_stage("mode-x", "s")["staged"] is False
        assert sm.advance_stage("mode-x", "s")["staged"] is False

    def test_small_mode_frontier_ungated(self):
        _mk("mode-a", dependencies=["mode-b"], dependency_kind="hard")
        _mk("mode-b")
        sm = get_skill_manager()
        sm.set_guidance_policy(mode="small")
        assert "mode-a" in sm.guided_frontier(completed=[])  # no gating in small

    def test_full_mode_dep_gates(self):
        _mk("mode-c", dependencies=["mode-d"])
        _mk("mode-d")
        sm = get_skill_manager()
        assert "mode-c" not in sm.guided_frontier(completed=[])
        assert "mode-c" in sm.guided_frontier(completed=["mode-d"])

    def test_invalid_mode_rejected(self):
        assert get_skill_manager().set_guidance_policy(mode="bogus")["success"] is False
