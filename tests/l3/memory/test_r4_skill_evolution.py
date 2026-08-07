"""R4Agent skill evolution tests — dedup, TTL pruning, orphan cleanup.

Covers the new skill-evolution features:
  1. Lean case deduplication in _process_failure_traces
  2. _prune_stale_skills TTL check
  3. _clean_orphan_traces orphan file cleanup
  4. get_evolved_skills agent_id filter
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from l1.kernel.skill import get_skill_manager, reset_skill_manager


class TestLeanCaseDedup:
    def test_duplicate_trace_marks_resolved_without_new_skill(self):
        """A second trace for the same tool+agent must not create a second skill."""
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()
        sm = get_skill_manager()
        r4 = R4Agent()

        td = tempfile.mkdtemp()
        old_dir = os.environ.get("PRAXIS_DATA_DIR")
        os.environ["PRAXIS_DATA_DIR"] = td
        from l1.kernel.paths import reset_paths
        reset_paths()
        try:
            # First trace → generates lean case
            r4._track_failure("agent-a", "bash", {"cmd": "x"}, "boom", [])
            assert r4._process_failure_traces() >= 1
            count_after_first = len(sm.list_skills(tags=["lean_case"]))

            # Second trace for same tool+agent → deduped (no new skill)
            r4._track_failure("agent-a", "bash", {"cmd": "y"}, "boom2", [])
            r4._process_failure_traces()
            count_after_second = len(sm.list_skills(tags=["lean_case"]))
            assert count_after_second == count_after_first
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)
            reset_paths()
            if old_dir is None:
                del os.environ["PRAXIS_DATA_DIR"]
            else:
                os.environ["PRAXIS_DATA_DIR"] = old_dir

    def test_lean_case_readable_name(self):
        """Generated lean case uses lean_{agent}_{tool} naming."""
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()
        sm = get_skill_manager()
        r4 = R4Agent()

        td = tempfile.mkdtemp()
        old_dir = os.environ.get("PRAXIS_DATA_DIR")
        os.environ["PRAXIS_DATA_DIR"] = td
        from l1.kernel.paths import reset_paths
        reset_paths()
        try:
            r4._track_failure("agent-b", "grep", {}, "not found", [])
            r4._process_failure_traces()
            names = [s["name"] for s in sm.list_skills(tags=["lean_case"])]
            assert any(n.startswith("lean_agent-b_grep") for n in names)
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)
            reset_paths()
            if old_dir is None:
                del os.environ["PRAXIS_DATA_DIR"]
            else:
                os.environ["PRAXIS_DATA_DIR"] = old_dir


class TestPruneStaleSkills:
    def test_old_unused_skill_pruned(self):
        """Evolved skill with ancient loaded_at and no last_used is pruned."""
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()
        sm = get_skill_manager()
        r4 = R4Agent()

        sm.create(name="ancient", prompt="p", tags=["evolved"], internal=True)
        sm.update("ancient", {"loaded_at": 0.0}, internal=True)
        sm.create(name="fresh", prompt="p", tags=["evolved"], internal=True)

        pruned = r4._prune_stale_skills()
        assert pruned >= 1
        assert sm.get("ancient") is None
        assert sm.get("fresh") is not None

    def test_lean_cases_never_pruned(self):
        """Lean case skills are exempt from TTL pruning."""
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()
        sm = get_skill_manager()
        r4 = R4Agent()

        sm.create(name="lean-keep", prompt="p", tags=["lean_case", "failure"], internal=True)
        sm.update("lean-keep", {"loaded_at": 0.0}, internal=True)

        r4._prune_stale_skills()
        assert sm.get("lean-keep") is not None


class TestOrphanCleanup:
    def test_old_unresolved_trace_removed(self):
        """A trace file older than 24h that is still unresolved is deleted."""
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()
        r4 = R4Agent()

        td = tempfile.mkdtemp()
        old_dir = os.environ.get("PRAXIS_DATA_DIR")
        os.environ["PRAXIS_DATA_DIR"] = td
        from l1.kernel.paths import reset_paths
        reset_paths()
        try:
            lean_dir = os.path.join(td, "skills", "lean")
            os.makedirs(lean_dir, exist_ok=True)
            fp = os.path.join(lean_dir, "agent_x_tool_y_1.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump({"resolved": False, "tool": "y"}, f)
            # Backdate mtime beyond 24h
            import time
            old = time.time() - 90000
            os.utime(fp, (old, old))

            cleaned = r4._clean_orphan_traces()
            assert cleaned == 1
            assert not os.path.exists(fp)
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)
            reset_paths()
            if old_dir is None:
                del os.environ["PRAXIS_DATA_DIR"]
            else:
                os.environ["PRAXIS_DATA_DIR"] = old_dir

    def test_fresh_trace_kept(self):
        """A recent unresolved trace is not deleted."""
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()
        r4 = R4Agent()

        td = tempfile.mkdtemp()
        old_dir = os.environ.get("PRAXIS_DATA_DIR")
        os.environ["PRAXIS_DATA_DIR"] = td
        from l1.kernel.paths import reset_paths
        reset_paths()
        try:
            lean_dir = os.path.join(td, "skills", "lean")
            os.makedirs(lean_dir, exist_ok=True)
            fp = os.path.join(lean_dir, "agent_x_tool_y_2.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump({"resolved": False, "tool": "y"}, f)

            cleaned = r4._clean_orphan_traces()
            assert cleaned == 0
            assert os.path.exists(fp)
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)
            reset_paths()
            if old_dir is None:
                del os.environ["PRAXIS_DATA_DIR"]
            else:
                os.environ["PRAXIS_DATA_DIR"] = old_dir


class TestEvolvedSkillFilter:
    def test_get_evolved_skills_filters_by_agent(self):
        """get_evolved_skills(agent_id=...) only returns that agent's skills."""
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()
        sm = get_skill_manager()
        r4 = R4Agent()

        sm.create(name="mine", prompt="p", tags=["evolved", "agent-1"], internal=True)
        sm.create(name="theirs", prompt="p", tags=["evolved", "agent-2"], internal=True)

        mine = r4.get_evolved_skills(agent_id="agent-1")
        names = [e["name"] for e in mine]
        assert "mine" in names
        assert "theirs" not in names

    def test_evolved_skills_include_useful_count_order(self):
        """Without agent filter, evolved skills come back sorted by recency."""
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()
        sm = get_skill_manager()
        r4 = R4Agent()

        sm.create(name="older", prompt="p", tags=["evolved"], internal=True)
        sm.create(name="newer", prompt="p", tags=["evolved"], internal=True)
        evolved = r4.get_evolved_skills()
        names = [e["name"] for e in evolved]
        assert names[0] == "newer"
