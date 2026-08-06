"""R4Agent injection-feedback tests (P1) — last_used refresh without cache invalidation.

Covers:
  - get_lean_case_names consistency with get_lean_cases (shared cache)
  - usage-only last_used update does NOT bump the SkillManager revision
  - TTL prune spares skills refreshed by the injection feedback
  - AgentLoop._inject_extra_context refreshes last_used for injected skills
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def _reset() -> None:
    from l1.kernel.skill import reset_skill_manager

    reset_skill_manager()


class TestInjectionFeedback:
    """P1 — injection feedback loop for skill last_used."""

    def test_lean_case_names_consistent_with_cases(self):
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        sm = get_skill_manager()
        sm.create(
            name="lean_agent-1_toola",
            description="f",
            prompt="lesson-a",
            tags=["lean_case", "failure", "agent-1", "toola"],
            allowed_tools=["toola"],
            internal=True,
        )
        sm.create(
            name="lean_agent-1_toolb",
            description="f",
            prompt="lesson-b",
            tags=["lean_case", "failure", "agent-1", "toolb"],
            allowed_tools=["toolb"],
            internal=True,
        )
        r4 = R4Agent()
        cases = r4.get_lean_cases(agent_id="agent-1", cell_id="")
        names = r4.get_lean_case_names(agent_id="agent-1", cell_id="")
        assert len(cases) == len(names) == 2
        assert set(names) == {"lean_agent-1_toola", "lean_agent-1_toolb"}
        # Prompts map 1:1 to names from the same cached scan.
        by_name = dict(zip(names, cases, strict=True))
        assert by_name["lean_agent-1_toola"] == "lesson-a"

    def test_usage_only_update_keeps_revision(self):
        from l1.kernel.skill import get_skill_manager

        _reset()
        sm = get_skill_manager()
        sm.create(name="s1", description="d", prompt="p", tags=["evolved"], internal=True)
        rev_before = sm.revision()
        r = sm.update("s1", {"last_used": time.time()})
        assert r.get("success") is True
        # Usage-only bookkeeping must NOT bump the revision — otherwise the
        # R4Agent injection cache would thrash on every agent run.
        assert sm.revision() == rev_before
        # ...and must work identity-less (no write clearance needed).
        assert sm.get("s1")["last_used"] > 0

    def test_ttl_prune_spares_feedback_refreshed_skill(self):
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        sm = get_skill_manager()
        sm.create(name="evolved-1", description="d", prompt="p", tags=["evolved"], internal=True)
        sm.update("evolved-1", {"last_used": 0.0})  # mark as never used
        r4 = R4Agent()
        # Simulate the injection feedback: refresh last_used.
        sm.update("evolved-1", {"last_used": time.time()})
        pruned = r4._prune_stale_skills()
        assert pruned == 0  # refreshed skill must survive the TTL scan
        assert sm.get("evolved-1") is not None

    def test_agent_loop_injection_refreshes_last_used(self):
        from l1.kernel.skill import get_skill_manager
        from l3.agent.agent_loop import AgentLoop
        from l3.memory.r4_agent import R4Agent

        _reset()
        sm = get_skill_manager()
        sm.create(
            name="lean_agent-x_toolz",
            description="f",
            prompt="lesson",
            tags=["lean_case", "failure", "agent-x", "toolz"],
            allowed_tools=["toolz"],
            internal=True,
        )
        sm.create(name="evolved-x", description="d", prompt="p", tags=["evolved", "agent-x"], internal=True)
        R4Agent()
        loop = AgentLoop.__new__(AgentLoop)
        loop.agent_id = "agent-x"
        loop._cell_id = ""
        loop._pmu = None
        out = loop._inject_extra_context("base")
        assert "Known Failure Patterns" in out or "evolved-x" in out
        # Both injected skills must carry a fresh last_used after the run.
        assert sm.get("lean_agent-x_toolz")["last_used"] > 0
        assert sm.get("evolved-x")["last_used"] > 0


class TestSkillRefinement:
    """P2 — skill refinement loop (usage preservation, refine hints, archive-before-overwrite)."""

    def _clear_lean_dir(self) -> None:
        from l1.kernel.paths import get_paths as _gp

        lean_dir = _gp().skill_lean_dir
        os.makedirs(lean_dir, exist_ok=True)
        for f in os.listdir(lean_dir):
            if f.endswith(".json"):
                with contextlib.suppress(OSError):
                    os.remove(os.path.join(lean_dir, f))

    def test_evolve_overwrite_preserves_usage_counters(self, mocker):
        import shutil

        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        sm = get_skill_manager()
        sm.create(name="db-migration-helper", description="old", prompt="old prompt", tags=["evolved"], internal=True)
        sm.update("db-migration-helper", {"useful_count": 5, "last_used": 1000.0})
        payload = json.dumps(
            {
                "name": "db-migration-helper",
                "description": "new",
                "prompt": "new prompt",
                "tags": ["database"],
            }
        )
        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"content": payload}
        r4 = R4Agent()
        result = r4.evolve_skill("re-evolve db migration")
        assert result["success"], result
        s = sm.get("db-migration-helper")
        assert s["prompt"] == "new prompt"  # overwritten with new content
        assert s["useful_count"] == 5  # P2-1: counters preserved
        assert s["last_used"] == 1000.0
        for base in (_gp().skill_evolved_dir, _gp().skill_project_evolved_dir):
            shutil.rmtree(os.path.join(base, "db-migration-helper"), ignore_errors=True)

    def test_refine_hint_fires_for_evolved_skill_of_tool(self):
        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        sm = get_skill_manager()
        sm.create(
            name="evolved-toolr", description="d", prompt="p", tags=["evolved"], allowed_tools=["toolr"], internal=True
        )
        self._clear_lean_dir()
        trace = os.path.join(_gp().skill_lean_dir, "r4-feedback-test.json")
        with open(trace, "w", encoding="utf-8") as f:
            json.dump(
                {"tool": "toolr", "agent_id": "a1", "args": {}, "error": "boom", "turn_count": 3, "resolved": False}, f
            )
        captured = []

        class _Pmu:
            def increment(self, name):
                captured.append(name)

        r4 = R4Agent()
        r4.set_pmu(_Pmu())
        n = r4._process_failure_traces()
        assert n >= 1
        assert "skills.refine_hint" in captured  # P2-2: hint fires for evolved skill
        os.remove(trace)

    def test_refine_hint_not_fired_without_evolved_skill(self):
        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        sm = get_skill_manager()
        sm.create(
            name="lean_a1_tooln",
            description="f",
            prompt="x",
            tags=["lean_case", "failure", "a1", "tooln"],
            allowed_tools=["tooln"],
            internal=True,
        )
        self._clear_lean_dir()
        trace = os.path.join(_gp().skill_lean_dir, "r4-feedback-neg.json")
        with open(trace, "w", encoding="utf-8") as f:
            json.dump(
                {"tool": "tooln", "agent_id": "a1", "args": {}, "error": "boom", "turn_count": 1, "resolved": False}, f
            )
        captured = []

        class _Pmu:
            def increment(self, name):
                captured.append(name)

        r4 = R4Agent()
        r4.set_pmu(_Pmu())
        r4._process_failure_traces()
        assert "skills.refine_hint" not in captured  # negative: no evolved skill for tooln
        os.remove(trace)

    def test_generalize_archives_before_overwrite(self):
        import shutil
        from unittest import mock

        from l1.kernel.params.agent import R4_LEAN_GENERALIZE_THRESHOLD
        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        sm = get_skill_manager()
        sm.create(
            name="lean_toolg_lessons",
            description="Consolidated (1 cases)",
            prompt="Known failure patterns when using toolg:\n- old",
            tags=["evolved", "toolg"],
            allowed_tools=["toolg"],
            internal=True,
        )
        for i in range(R4_LEAN_GENERALIZE_THRESHOLD):
            sm.create(
                name=f"lean_a1_toolg_e{i}",
                description="f",
                prompt=f"lesson{i}",
                tags=["lean_case", "failure", "a1", "toolg"],
                allowed_tools=["toolg"],
                internal=True,
            )
        r4 = R4Agent()
        with mock.patch.object(r4, "_archive_before_evolve") as arch:
            n = r4._generalize_lean_cases(sm)
            assert n >= 1
            arch.assert_called_once()  # P2-3: old version archived before overwrite
            assert arch.call_args[0][0] == "lean_toolg_lessons"
            assert arch.call_args[0][1]["prompt"] == "Known failure patterns when using toolg:\n- old"
        shutil.rmtree(os.path.join(_gp().skill_project_evolved_dir, "lean_toolg_lessons"), ignore_errors=True)

    def test_generalize_skips_idempotent_without_archive(self):
        import shutil
        from unittest import mock

        from l1.kernel.params.agent import R4_LEAN_GENERALIZE_THRESHOLD
        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        sm = get_skill_manager()
        for i in range(R4_LEAN_GENERALIZE_THRESHOLD):
            sm.create(
                name=f"lean_a1_tooli_e{i}",
                description="f",
                prompt=f"lesson{i}",
                tags=["lean_case", "failure", "a1", "tooli"],
                allowed_tools=["tooli"],
                internal=True,
            )
        r4 = R4Agent()
        r4._generalize_lean_cases(sm)  # first pass creates + persists
        gen_name = "lean_tooli_lessons"
        # Ensure SKILL.md exists so the idempotency guard (prompt + file) holds.
        r4._persist_skill_md(
            name=gen_name,
            description="d",
            prompt=sm.get(gen_name)["prompt"],
            tags=["evolved", "tooli"],
            allowed_tools=["tooli"],
        )
        with mock.patch.object(r4, "_archive_before_evolve") as arch:
            n = r4._generalize_lean_cases(sm)
            assert n == 0  # idempotent: same cases + file exists
            arch.assert_not_called()  # negative: no archive on skip
        shutil.rmtree(os.path.join(_gp().skill_project_evolved_dir, gen_name), ignore_errors=True)


class TestLessonSummarization:
    """P3 — LLM lesson summarization (gates, quality floor, degradation, anti-downgrade)."""

    def _mk_cases(self, tool: str, n: int = 3) -> None:
        from l1.kernel.params.agent import R4_LEAN_GENERALIZE_THRESHOLD
        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        for i in range(max(n, R4_LEAN_GENERALIZE_THRESHOLD)):
            sm.create(
                name=f"lean_a1_{tool}_e{i}",
                description="f",
                prompt=f"lesson{i} for {tool}",
                tags=["lean_case", "failure", "a1", tool],
                allowed_tools=[tool],
                internal=True,
            )

    def test_llm_lesson_wins_over_baseline(self, mocker):
        import shutil

        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        self._mk_cases("toolp3")
        payload = json.dumps({"lesson": "Always verify the output schema before writing files."})
        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"content": payload}
        r4 = R4Agent()
        r4._generalize_lean_cases(get_skill_manager())
        s = get_skill_manager().get("lean_toolp3_lessons")
        assert s is not None
        assert s["prompt"] == "Always verify the output schema before writing files."
        assert "Known failure patterns" not in s["prompt"]  # LLM won over baseline
        shutil.rmtree(os.path.join(_gp().skill_project_evolved_dir, "lean_toolp3_lessons"), ignore_errors=True)

    def test_llm_failure_degrades_to_baseline(self, mocker):
        import shutil

        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        self._mk_cases("toolp3b")
        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.side_effect = RuntimeError("provider down")
        r4 = R4Agent()
        r4._generalize_lean_cases(get_skill_manager())
        s = get_skill_manager().get("lean_toolp3b_lessons")
        assert s is not None and s["prompt"].startswith("Known failure patterns")  # fallback
        shutil.rmtree(os.path.join(_gp().skill_project_evolved_dir, "lean_toolp3b_lessons"), ignore_errors=True)

    def test_short_lesson_rejected(self, mocker):
        import shutil

        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        self._mk_cases("toolp3c")
        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"content": json.dumps({"lesson": "short"})}
        r4 = R4Agent()
        r4._generalize_lean_cases(get_skill_manager())
        s = get_skill_manager().get("lean_toolp3c_lessons")
        assert s is not None and s["prompt"].startswith("Known failure patterns")  # rejected
        shutil.rmtree(os.path.join(_gp().skill_project_evolved_dir, "lean_toolp3c_lessons"), ignore_errors=True)

    def test_cooldown_returns_none(self):
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        get_skill_manager()
        r4 = R4Agent()
        r4._last_summarize["toolx"] = time.time()  # just summarized
        cases = [{"prompt": "a"}] * 3
        assert r4._summarize_tool_lessons("toolx", cases) is None  # cooldown gate

    def test_refresh_does_not_downgrade_llm_lesson(self, mocker):
        """Anti-downgrade: same case set + LLM unavailable → the fingerprint
        idempotency skips the refresh, so the LLM-refined lesson is NOT replaced
        by the rule-based baseline."""
        import shutil
        from unittest import mock

        from l1.kernel.paths import get_paths as _gp
        from l1.kernel.skill import get_skill_manager
        from l3.memory.r4_agent import R4Agent

        _reset()
        self._mk_cases("toolp3d")
        sm = get_skill_manager()
        payload = json.dumps({"lesson": "Refined lesson that must survive a refresh."})
        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"content": payload}
        r4 = R4Agent()
        r4._generalize_lean_cases(sm)
        refined = sm.get("lean_toolp3d_lessons")["prompt"]
        assert refined.startswith("Refined lesson")
        # Now the LLM is unavailable and the same case set is scanned again.
        mock_engine.return_value.generate.side_effect = RuntimeError("down")
        with mock.patch.object(r4, "_archive_before_evolve") as arch:
            n = r4._generalize_lean_cases(sm)
            assert n == 0  # fingerprint idempotency → skipped entirely
            arch.assert_not_called()
        assert sm.get("lean_toolp3d_lessons")["prompt"] == refined  # NOT downgraded
        shutil.rmtree(os.path.join(_gp().skill_project_evolved_dir, "lean_toolp3d_lessons"), ignore_errors=True)
