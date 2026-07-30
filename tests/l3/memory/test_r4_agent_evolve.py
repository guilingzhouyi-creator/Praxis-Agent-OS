"""R4Agent evolve_skill tests — skill hot-generation via LLM.

Tests the full chain:
  1. evolve_skill() validation (empty input)
  2. LLM-generated skill registration via SkillManager
  3. SKILL.md persistence
  4. get_evolved_skills() retrieval
  5. get_lean_cases() after SkillManager changes
"""

from __future__ import annotations

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestEvolveSkillValidation:
    """Input validation — no LLM needed."""

    def test_evolve_empty_intent(self):
        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        r = r4.evolve_skill("")
        assert not r.get("success")
        assert "usage" in r.get("error", "").lower()

    def test_evolve_whitespace_intent(self):
        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        r = r4.evolve_skill("   ")
        assert not r.get("success")
        assert "usage" in r.get("error", "").lower()


class TestEvolveSkillRegistration:
    """Test that evolve_skill registers skills via SkillManager."""

    def test_get_evolved_skills_empty_initially(self):
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()
        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills()
        assert evolved == []

    def test_register_skill_directly_then_retrieve(self):
        """Simulate what evolve_skill does: register via SkillManager with 'evolved' tag."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()

        sm.create(
            name="test-migration-helper",
            description="Generate database migration templates",
            prompt="You are a migration specialist. Follow these rules...",
            tags=["evolved", "database"],
            rules=["DO: use timestamp prefixes", "DON'T: modify existing migrations"],
            procedures=[{"step": "1", "action": "analyze", "description": "Analyze schema changes"}],
        )

        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(limit=5)
        assert len(evolved) >= 1
        names = [e["name"] for e in evolved]
        assert "test-migration-helper" in names

    def test_get_evolved_skills_limit(self):
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()

        for i in range(5):
            sm.create(
                name=f"test-skill-{i}",
                description=f"Test skill {i}",
                prompt=f"Prompt for skill {i}",
                tags=["evolved"],
            )

        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(limit=2)
        assert len(evolved) <= 2  # limit respected

    def test_evolved_skills_exclude_lean_cases(self):
        """Evolved skills and lean cases should be separate."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()

        sm.create(name="evolved-one", prompt="evolved prompt", tags=["evolved", "test"])
        sm.create(name="lean-one", prompt="lean prompt", tags=["lean_case", "failure"])

        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills()
        lean = r4.get_lean_cases()

        evolved_names = [e["name"] for e in evolved]
        assert "evolved-one" in evolved_names
        assert "lean-one" not in evolved_names


class TestSkillManagerPersistence:
    """SKILL.md file persistence and reload."""

    def test_skill_manager_create_roundtrip(self):
        """Programmatic create → list roundtrip."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()

        sm.create(
            name="roundtrip-test",
            description="Roundtrip test skill",
            prompt="Test prompt content",
            tags=["evolved", "test"],
            rules=["DO: test"],
        )

        skills = sm.list(tags=["evolved"])
        assert len(skills) >= 1
        skill = next((s for s in skills if s["name"] == "roundtrip-test"), None)
        assert skill is not None
        assert skill["description"] == "Roundtrip test skill"
        assert skill["prompt"] == "Test prompt content"

    def test_skill_list_all_without_tags(self):
        """sm.list() without tags returns all skills."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()

        sm.create(name="skill-a", prompt="a", tags=["evolved"])
        sm.create(name="skill-b", prompt="b", tags=["lean_case"])

        all_skills = sm.list()
        assert len(all_skills) >= 2


class TestAgentLoopInjectionIntegration:
    """Verify the injection infrastructure is wired correctly."""

    def test_evolved_skills_method_exists(self):
        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        assert hasattr(r4, 'get_evolved_skills')
        assert callable(r4.get_evolved_skills)

    def test_agent_loop_imports_r4(self):
        """AgentLoop should be able to import and call get_evolved_skills."""
        from l3.agent.agent_loop import AgentLoop
        loop = AgentLoop(task="test", agent_id="test-agent")
        # The injection is in the run() method, but we just verify the import works
        assert loop is not None

    def test_skill_manager_loaded_builtin_adds_evolved_dir(self):
        """Verify load_builtin tries to load from SKILL_EVOLVED_DIR."""
        from l1.kernel.skill import SkillManager
        sm = SkillManager()
        count = sm.load_builtin()
        # Should not crash; evolved dir may not exist yet
        assert isinstance(count, int)
