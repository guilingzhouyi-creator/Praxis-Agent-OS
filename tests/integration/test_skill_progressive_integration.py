"""Integration tests: progressive disclosure, staged skills and guidance engine.

Cross-layer coverage with REAL components (no pipeline mocks):
  L1 SkillManager (disclosure depth / stages / guidance DAG)
  x L3 SkillCatalogHook (audience-aware two-level catalog, L3A capability view)
  x L3 use_skill (per-stage disclosure)
  x L3 card-completion bridge (skill_guidance)
  x L4 API handlers (/api/v2/skills/disclosure + pipeline)
  x L2 Shell (/skills disclosure + pipeline)

Uses the REAL builtin catalog (config/skills): tdd is staged
(red/green/refactor) and diagnosing-bugs points forward to tdd, so the
guidance chain and stage disclosure run against production data.
"""

from __future__ import annotations

import pytest

from l1.kernel.skill import get_skill_manager, reset_skill_manager


@pytest.fixture(autouse=True)
def _reset_and_load_builtins():
    """Fresh SkillManager with the real builtin catalog for every test."""
    reset_skill_manager()
    get_skill_manager().load_dir("config/skills")
    yield
    reset_skill_manager()


def _session(task: str, agent_id: str) -> str:
    """Run a real SkillCatalogHook session (L3 hook chain stage)."""
    from l3.services.hook import SkillCatalogHook

    return SkillCatalogHook().session_start(task, agent_id)


def _catalog_lines(out: str) -> list[str]:
    """Extract the curated catalog lines from a session output."""
    if "Available skills (use_skill to invoke):" not in out:
        return []
    section = out.split("Available skills (use_skill to invoke):", 1)[1]
    return [line for line in section.splitlines() if line.startswith("  ")]


class TestBuiltinRoundTrip:
    """New frontmatter fields survive loading from the real builtin catalog."""

    def test_tdd_staged_and_forward(self):
        skill = get_skill_manager().get("tdd")
        assert skill["disclosure"] == "full"
        assert skill["next"] == ["code-review"]
        assert [s["id"] for s in skill["stages"]] == ["red", "green", "refactor"]

    def test_diagnosing_bugs_forward_chain(self):
        assert get_skill_manager().get("diagnosing-bugs")["next"] == ["tdd"]

    def test_all_builtins_have_valid_disclosure(self):
        for s in get_skill_manager().list_skills():
            assert s["disclosure"] in ("full", "index", "none")


class TestCatalogAudienceAndDisclosure:
    """L3 SkillCatalogHook: audience routing + two-level index + capability view."""

    def test_peer_session_excludes_strategy_skills(self):
        out = _session("do the thing", "agent-writer")
        assert "ask-matt" not in out  # strategy-tagged skill hidden from peers
        assert _catalog_lines(out), "peer session should have a curated catalog"

    def test_peer_catalog_capped_at_curated_slots(self):
        out = _session("do the thing", "agent-writer")
        assert 0 < len(_catalog_lines(out)) <= 5

    def test_l3a_session_sees_strategy_and_capability_view(self):
        out = _session("plan a feature", "l3a")
        assert "handoff" in out  # strategy-tagged skill visible to the decision layer
        assert "ask-matt" not in out  # curated slots follow load order, not alphabetical
        assert "Peer capabilities" in out  # capability view appended
        assert "[peer-capability]" in out

    def test_full_index_lists_beyond_curated_slots(self):
        sm = get_skill_manager()
        sm.set_disclosure_policy(full_index_enabled=True, full_index_limit=50)
        out = _session("do the thing", "agent-writer")
        assert len(_catalog_lines(out)) > 5

    def test_disclosure_policy_can_toggle_audience_filter(self):
        sm = get_skill_manager()
        sm.set_disclosure_policy(full_index_enabled=True, full_index_limit=50)
        # Audience filter ON → strategy skills absent from the peer catalog.
        assert "ask-matt" not in _session("do the thing", "agent-writer")
        # Audience filter OFF → strategy skills surface in the full index.
        sm.set_disclosure_policy(audience_filter_enabled=False)
        assert "ask-matt" in _session("do the thing", "agent-writer")


class TestStagedUseSkillIntegration:
    """L3 use_skill: per-stage disclosure follows the quest-style progression."""

    def test_use_skill_discloses_active_stage(self):
        from l3.tools._skills import use_skill

        sm = get_skill_manager()
        r = use_skill({"name": "tdd"}, "agent-writer")
        assert r["success"] and r["staged"] and r["stage_id"] == "red"
        assert "failing test" in r["prompt"].lower()

        sm.advance_stage("tdd", "agent-writer")
        r2 = use_skill({"name": "tdd"}, "agent-writer")
        assert r2["stage_id"] == "green"

        sm.advance_stage("tdd", "agent-writer")
        r3 = use_skill({"name": "tdd"}, "agent-writer")
        assert r3["stage_id"] == "refactor" and r3["next_stage"] is None

    def test_unstaged_skill_returns_full_prompt(self):
        from l3.tools._skills import use_skill

        r = use_skill({"name": "kernel"}, "agent-writer")
        assert r["success"] and not r.get("staged") and r["prompt"]


class TestGuidanceEngineOnBuiltins:
    """L1 guidance DAG over the real builtin catalog."""

    def test_builtin_graph_acyclic(self):
        r = get_skill_manager().validate_guidance_graph()
        assert r["acyclic"] is True
        assert r["nodes"] >= 3  # tdd→code-review, diagnosing-bugs→tdd, architecture→kernel…

    def test_frontier_unlocks_dependency_free_skills(self):
        frontier = get_skill_manager().guided_frontier(completed=[])
        assert "tdd" in frontier  # no dependencies → unlocked

    def test_forward_next_creates_edges(self):
        graph = get_skill_manager()._guidance_graph()
        assert "tdd" in graph.get("diagnosing-bugs", set())  # diagnosing-bugs → tdd
        assert "code-review" in graph.get("tdd", set())  # tdd → code-review


class TestApiHandlers:
    """L4 API surface: disclosure + pipeline policy round-trip."""

    def test_disclosure_get_and_set(self, mocker):
        from l4.api_handlers.api_handlers_skills import (
            handle_skills_disclosure_get,
            handle_skills_disclosure_set,
        )

        sm = get_skill_manager()
        mocker.patch.object(sm, "authorize_write", return_value=(True, "test"))
        r = handle_skills_disclosure_set({"full_index_enabled": True, "full_index_limit": 40, "role": "developer"})
        assert r["success"] and r["full_index_enabled"] is True and r["full_index_limit"] == 40
        g = handle_skills_disclosure_get()
        assert g["policy"]["full_index_enabled"] is True

    def test_pipeline_handlers(self, mocker):
        from l4.api_handlers.api_handlers_skills import (
            handle_skills_pipeline_get,
            handle_skills_pipeline_set,
        )

        sm = get_skill_manager()
        mocker.patch.object(sm, "authorize_write", return_value=(True, "test"))
        r = handle_skills_pipeline_set({"retrieval": False, "role": "developer"})
        assert r["retrieval"] is False
        assert handle_skills_pipeline_get()["policy"]["retrieval"] is False


class TestL2ShellControl:
    """L2 Shell: /skills disclosure + pipeline runtime control."""

    def test_disclosure_status_and_set(self):
        from l2.l2_shell.commands.system import _cmd_skills

        r = _cmd_skills(["disclosure", "status"])
        assert r["success"] and "full_index_enabled" in r["policy"]
        r2 = _cmd_skills(["disclosure", "set", "full_index_enabled", "on"])
        assert r2["success"] and r2["full_index_enabled"] is True

    def test_pipeline_toggle(self):
        from l2.l2_shell.commands.system import _cmd_skills

        r = _cmd_skills(["pipeline", "set", "retrieval", "off"])
        assert r["success"] and r["retrieval"] is False
        assert _cmd_skills(["pipeline", "status"])["policy"]["retrieval"] is False


class TestCardCompletionLinkage:
    """L3 skill_guidance bridge: card completion advances staged skills."""

    def test_wire_and_advance_on_card_completion(self):
        from l3.memory.skill_guidance import _on_card_complete, wire_card_guidance

        sm = get_skill_manager()
        assert sm.current_stage("tdd", "card:card-9")["stage_index"] == 0
        assert wire_card_guidance()["success"]
        _on_card_complete("card-9", "COMPLETED", None)
        assert sm.current_stage("tdd", "card:card-9")["stage_index"] == 1

    def test_other_card_sessions_unaffected(self):
        sm = get_skill_manager()
        _ = sm.current_stage("tdd", "card:card-a")
        assert sm.current_stage("tdd", "card:card-b")["stage_index"] == 0


class TestDisclosureBoundaries:
    """Disclosure depth edge cases: none/index/invalid round-trip."""

    def test_none_skill_hidden_from_catalog_but_explicitly_usable(self):
        from l3.tools._skills import use_skill

        sm = get_skill_manager()
        sm.create(name="hidden-skill", description="d", prompt="secret instructions", disclosure="none", internal=True)
        assert "hidden-skill" not in _session("do the thing", "agent-writer")
        r = use_skill({"name": "hidden-skill"}, "agent-writer")
        assert r["success"] and "secret" in r["prompt"]

    def test_index_skill_listed_but_content_loaded_on_demand(self):
        from l3.tools._skills import use_skill

        sm = get_skill_manager()
        sm.create(name="indexed-skill", description="indexed", prompt="full body", disclosure="index", internal=True)
        sm.set_disclosure_policy(full_index_enabled=True, full_index_limit=50)
        assert "indexed-skill" in _session("do the thing", "agent-writer")
        r = use_skill({"name": "indexed-skill"}, "agent-writer")
        assert r["success"] and "full body" in r["prompt"]

    def test_invalid_disclosure_falls_back_full(self):
        sm = get_skill_manager()
        sm.create(name="bad-disc", description="d", prompt="p", disclosure="banana", internal=True)
        assert sm.get("bad-disc")["disclosure"] == "full"


class TestStageBoundaries:
    """Quest-style stage edge cases: bounds, malformed stages, session isolation."""

    def test_advance_past_last_stage_keeps_done(self):
        sm = get_skill_manager()
        sm.create(
            name="two-stage",
            description="d",
            prompt="p",
            stages=[{"id": "a", "instructions": "A"}, {"id": "b", "instructions": "B"}],
            internal=True,
        )
        assert sm.advance_stage("two-stage", "s")["stage_index"] == 1
        r = sm.advance_stage("two-stage", "s")
        assert r["done"] and r["stage_index"] == 1  # no overflow past last stage
        assert sm.current_stage("two-stage", "s")["stage_index"] == 1

    def test_single_stage_skill_stays_at_zero(self):
        sm = get_skill_manager()
        sm.create(
            name="one-stage", description="d", prompt="p", stages=[{"id": "only", "instructions": "X"}], internal=True
        )
        assert sm.current_stage("one-stage", "s")["done"] is True
        assert sm.advance_stage("one-stage", "s")["stage_index"] == 0

    def test_non_dict_stages_filtered(self):
        sm = get_skill_manager()
        sm.create(
            name="junk-stages",
            description="d",
            prompt="p",
            stages=[{"id": "ok", "instructions": "fine"}, "not-a-dict", 42],
            internal=True,
        )
        assert len(sm.get("junk-stages")["stages"]) == 1

    def test_concurrent_sessions_advance_independently(self):
        sm = get_skill_manager()
        sm.create(
            name="multi-sess",
            description="d",
            prompt="p",
            stages=[{"id": s, "instructions": s} for s in ("a", "b", "c")],
            internal=True,
        )
        sm.advance_stage("multi-sess", "sess-1")
        sm.advance_stage("multi-sess", "sess-1")
        sm.advance_stage("multi-sess", "sess-2")
        assert sm.current_stage("multi-sess", "sess-1")["stage_index"] == 2
        assert sm.current_stage("multi-sess", "sess-2")["stage_index"] == 1


class TestGuidanceBoundaries:
    """Guidance engine edge cases: missing deps, unknown targets, cycles."""

    def test_missing_dependency_locks_skill(self):
        sm = get_skill_manager()
        sm.create(name="needs-ghost", description="d", prompt="p", dependencies=["ghost-dep"], internal=True)
        assert "needs-ghost" not in sm.guided_frontier(completed=[])
        assert "needs-ghost" in sm.guided_frontier(completed=["ghost-dep"])

    def test_unknown_target_path_returns_empty(self):
        assert get_skill_manager().guided_path("no-such-skill") == []

    def test_cycle_skills_still_registered(self):
        sm = get_skill_manager()
        sm.create(name="cyc-a", description="d", prompt="p", dependencies=["cyc-b"], internal=True)
        sm.create(name="cyc-b", description="d", prompt="p", dependencies=["cyc-a"], internal=True)
        assert sm.validate_guidance_graph()["acyclic"] is False
        assert sm.get("cyc-a") is not None and sm.get("cyc-b") is not None  # registry unaffected


class TestLinkageBoundaries:
    """Card-completion linkage edge cases."""

    def test_non_completed_state_does_not_advance(self):
        from l3.memory.skill_guidance import _on_card_complete

        sm = get_skill_manager()
        _ = sm.current_stage("tdd", "card:fail-1")  # register the session
        _on_card_complete("fail-1", "FAILED", None)
        assert sm.current_stage("tdd", "card:fail-1")["stage_index"] == 0

    def test_unregistered_card_session_not_advanced(self):
        from l3.memory.skill_guidance import _on_card_complete

        sm = get_skill_manager()
        _on_card_complete("ghost-9", "COMPLETED", None)  # no prior stage read
        assert sm.current_stage("tdd", "card:ghost-9")["stage_index"] == 0

    def test_repeated_completion_advances_once_per_event(self):
        from l3.memory.skill_guidance import _on_card_complete

        sm = get_skill_manager()
        _ = sm.current_stage("tdd", "card:rep-1")
        _on_card_complete("rep-1", "COMPLETED", None)
        _on_card_complete("rep-1", "COMPLETED", None)  # second event → 1 → 2 (refactor)
        assert sm.current_stage("tdd", "card:rep-1")["stage_index"] == 2


class TestControlBoundaries:
    """L2/API control surface edge cases (invalid input, write gate)."""

    def test_l2_invalid_disclosure_field_returns_error(self):
        from l2.l2_shell.commands.system import _cmd_skills

        assert _cmd_skills(["disclosure", "set", "bogus_field", "on"])["success"] is False

    def test_l2_invalid_numeric_value_rejected(self):
        from l2.l2_shell.commands.system import _cmd_skills

        assert _cmd_skills(["pipeline", "set", "contrib_min_ratio", "abc"])["success"] is False

    def test_api_write_gate_denies_anonymous(self):
        from l4.api_handlers.api_handlers_skills import handle_skills_disclosure_set

        # No role/agent identity → the real authorize_write gate denies.
        r = handle_skills_disclosure_set({"full_index_enabled": True})
        assert r["success"] is False and "permission" in r["error"].lower()

    def test_full_index_limit_zero_yields_no_extra_lines(self):
        sm = get_skill_manager()
        sm.set_disclosure_policy(full_index_enabled=True, full_index_limit=0)
        out = _session("do the thing", "agent-writer")
        assert len(_catalog_lines(out)) <= 5
