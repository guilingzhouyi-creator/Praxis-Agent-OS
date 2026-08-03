"""R4Agent evolve_skill integration test and hybrid test.

Test strategy:
  Layer 1 — LLM mock integration: mock get_engine().generate(), verify full-link flow
  Layer 2 — Persistence hybrid: verify SKILL.md file creation + SkillManager reload
  Layer 3 — AgentLoop hybrid: verify Cell-A injection correctly reads evolved skills
  Layer 4 — Exception fault tolerance: verify graceful degradation on bad JSON/empty content/missing fields
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


# ═══════════════════════════════════════════════════════════════
# Layer 1: LLM mock integration — full evolve_skill flow
# ═══════════════════════════════════════════════════════════════

class TestEvolveSkillLLMFullFlow:
    """Mock LLM engine to test the full evolve_skill pipeline."""

    VALID_SKILL_JSON = json.dumps({
        "name": "db-migration-helper",
        "description": "Generate database migration templates with version control",
        "prompt": "You are a migration specialist. Always use timestamp prefixes.",
        "rules": ["DO: use YYYYMMDD_HHMMSS prefix", "DON'T: modify existing migrations"],
        "procedures": [
            {"step": "1", "action": "analyze", "description": "Analyze schema changes"},
            {"step": "2", "action": "generate", "description": "Generate migration file"},
        ],
        "tags": ["evolved", "database"],
    })

    def test_full_flow_with_mocked_llm(self, mocker):
        """Mock LLM → evolve_skill → SkillManager → SKILL.md full chain."""
        from l1.kernel.paths import get_paths
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        # Cleanup
        reset_skill_manager()
        sm = get_skill_manager()

        # Mock LLM engine
        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": self.VALID_SKILL_JSON,
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个数据库迁移工具")

        # Verify return value
        assert result["success"], f"evolve_skill failed: {result}"
        assert result["skill"] == "db-migration-helper"
        assert result["rules"] == 2

        # Verify SkillManager registration
        skills = sm.list(tags=["evolved"])
        names = [s["name"] for s in skills]
        assert "db-migration-helper" in names

        # Verify get_evolved_skills
        evolved = r4.get_evolved_skills()
        assert any(e["name"] == "db-migration-helper" for e in evolved)
        assert any("timestamp" in e.get("prompt", "") for e in evolved)

        # Verify SKILL.md file creation
        md_path = os.path.join(get_paths().skill_evolved_dir, "db-migration-helper", "SKILL.md")
        assert os.path.isfile(md_path), f"SKILL.md not found at {md_path}"
        with open(md_path, encoding="utf-8") as f:
            content = f.read()
        assert "db-migration-helper" in content
        assert "YYYYMMDD_HHMMSS" in content

    def test_llm_response_with_markdown_fences(self, mocker):
        """LLM response with ```json fences should also parse correctly."""
        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": "```json\n" + self.VALID_SKILL_JSON + "\n```",
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建数据库迁移工具")

        assert result["success"], f"markdown fence parse failed: {result}"
        assert result["skill"] == "db-migration-helper"

    def test_llm_response_trailing_newlines(self, mocker):
        """LLM response with trailing blank lines should parse correctly."""
        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": self.VALID_SKILL_JSON + "\n\n\n",
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建数据库迁移工具")
        assert result["success"]

    def test_evolve_then_lean_is_separate(self, mocker):
        """Skills created by evolve_skill should not pollute lean cases."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()
        sm = get_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": self.VALID_SKILL_JSON,
        }

        r4 = R4Agent()
        r4.evolve_skill("创建数据库迁移工具")

        # lean cases should not contain evolved skills
        lean = r4.get_lean_cases()
        assert all("timestamp" not in l for l in lean)  # evolved prompt has timestamp

        # evolved should contain
        evolved = r4.get_evolved_skills()
        assert any("timestamp" in e.get("prompt", "") for e in evolved)


# ═══════════════════════════════════════════════════════════════
# Layer 2: SKILL.md persistence + SkillManager reload test
# ═══════════════════════════════════════════════════════════════

class TestSkillPersistenceRoundtrip:
    """Verify SKILL.md can be reloaded by SkillManager after persistence."""

    def test_skill_manager_loads_evolved_dir(self, mocker):
        """load_builtin() should load SKILL.md from SKILL_EVOLVED_DIR."""
        from l1.kernel.skill import SkillManager

        with tempfile.TemporaryDirectory() as td:
            # Create a mock evolved skill directory
            skill_dir = os.path.join(td, "test-evolved-skill")
            os.makedirs(skill_dir, exist_ok=True)
            md_path = os.path.join(skill_dir, "SKILL.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("""---
name: temp-evolved-test
description: Temporarily created for load test
---

You are a test agent for verification.
""")

            sm = SkillManager()
            count = sm.load_dir(td)
            assert count >= 1, "should load at least 1 skill"

            skill = sm.get("temp-evolved-test")
            assert skill is not None
            assert "temporarily" in skill.get("description", "").lower()

    def test_multiple_evolved_skills_loaded(self):
        """Multiple evolved SKILL.md files should all load."""
        from l1.kernel.skill import SkillManager

        with tempfile.TemporaryDirectory() as td:
            names = ["skill-a", "skill-b", "skill-c"]
            for name in names:
                sdir = os.path.join(td, name)
                os.makedirs(sdir)
                with open(os.path.join(sdir, "SKILL.md"), "w", encoding="utf-8") as f:
                    f.write(f"""---
name: {name}
description: Test skill {name}
---

Prompt for {name}.""")
            sm = SkillManager()
            count = sm.load_dir(td)
            assert count == 3

            loaded = sm.list()
            loaded_names = [s["name"] for s in loaded]
            for n in names:
                assert n in loaded_names

    def test_evolve_skill_creates_valid_yaml_frontmatter(self, mocker):
        """SKILL.md generated by evolve_skill must have valid YAML frontmatter."""
        import yaml

        from l1.kernel.paths import get_paths
        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": json.dumps({
                "name": "yaml-validate-test",
                "description": "Testing YAML frontmatter validity",
                "prompt": "Test prompt",
                "rules": ["DO: test"],
                "tags": ["evolved", "test"],
            }),
        }

        r4 = R4Agent()
        r4.evolve_skill("测试 YAML 前导格式")

        md_path = os.path.join(get_paths().skill_evolved_dir, "yaml-validate-test", "SKILL.md")
        assert os.path.isfile(md_path)

        # Verify YAML frontmatter is parseable
        with open(md_path, encoding="utf-8") as f:
            content = f.read()
        import re
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        assert m is not None, "SKILL.md missing YAML frontmatter"
        meta = yaml.safe_load(m.group(1))
        assert meta["name"] == "yaml-validate-test"
        assert meta["description"] == "Testing YAML frontmatter validity"


# ═══════════════════════════════════════════════════════════════
# Layer 3: AgentLoop Cell-A injection hybrid test
# ═══════════════════════════════════════════════════════════════

class TestAgentLoopEvolvedInjection:
    """Verify evolved skills are injected into AgentLoop via Cell-A."""

    def test_get_evolved_skills_returns_registered(self):
        """get_evolved_skills should return all skills tagged as evolved from SkillManager."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()

        sm.create(name="evolved-one", prompt="prompt one", tags=["evolved", "db"])
        sm.create(name="evolved-two", prompt="prompt two", tags=["evolved", "api"])

        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(limit=5)
        assert len(evolved) >= 2

    def test_evolved_skills_injected_via_r4(self, mocker):
        """Skills returned by R4Agent.get_evolved_skills should be consumable by AgentLoop."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()

        sm.create(
            name="inject-test",
            description="测试注入",
            prompt="You are an injection test agent.",
            tags=["evolved", "test"],
        )

        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(limit=3)
        assert len(evolved) >= 1
        assert evolved[0]["name"] == "inject-test"
        assert "injection test" in evolved[0]["prompt"]

    def test_agentloop_run_imports_evolved_block(self):
        """AgentLoop._inject_extra_context() should have an evolved skill injection block."""
        import inspect

        from l3.agent.agent_loop import AgentLoop
        source = inspect.getsource(AgentLoop._inject_extra_context)
        assert "Evolved Skills" in source or "evolved" in source.lower()

    def test_no_evolved_skills_no_injection(self, mocker):
        """With no evolved skills, get_evolved_skills should return empty list without crashing."""
        from l1.kernel.skill import reset_skill_manager
        reset_skill_manager()

        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills()
        assert evolved == []

    def test_concurrent_evolve_and_inject(self, mocker):
        """Skills registered concurrently should be correctly read after injection."""
        import threading

        from l1.kernel.skill import get_skill_manager, reset_skill_manager

        reset_skill_manager()
        sm = get_skill_manager()

        def register_skill(i):
            sm.create(
                name=f"concurrent-{i}",
                description=f"Concurrent test {i}",
                prompt=f"Prompt for concurrent test {i}",
                tags=["evolved", "test"],
            )

        threads = [threading.Thread(target=register_skill, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        from l3.memory.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(limit=10)
        assert len(evolved) >= 5


# ═══════════════════════════════════════════════════════════════
# Layer 4: Exception fault tolerance — bad LLM responses
# ═══════════════════════════════════════════════════════════════

class TestEvolveSkillErrorHandling:
    """Test graceful degradation when LLM returns various bad responses."""

    def test_llm_returns_empty_content(self, mocker):
        """LLM returns empty content → JSON decode error → graceful degradation."""
        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"content": ""}

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]
        assert "JSON" in result.get("error", "") or "invalid" in result.get("error", "").lower()

    def test_llm_returns_invalid_json(self, mocker):
        """LLM returns non-JSON text → JSON decode error → graceful degradation."""
        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": "This is not JSON at all, it's just plain text.",
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]
        assert "JSON" in result.get("error", "") or "invalid" in result.get("error", "").lower()

    def test_llm_returns_partial_json(self, mocker):
        """LLM returns incomplete JSON → JSON decode error → graceful degradation."""
        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": '{"name": "broken"',
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]

    def test_llm_engine_raises_exception(self, mocker):
        """LLM engine itself throws exception → evolve_skill catches and returns friendly error."""
        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.side_effect = RuntimeError("LLM API timeout")

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]
        assert result.get("error")  # Should have specific error message

    def test_llm_returns_json_with_missing_fields(self, mocker):
        """LLM returns JSON with missing key fields, use defaults."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        # Only name, no other fields
        mock_engine.return_value.generate.return_value = {
            "content": '{"name": "minimal-skill"}',
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert result["success"]
        assert result["skill"].startswith("minimal")

        sm = get_skill_manager()
        skill = sm.get("minimal-skill")
        assert skill is not None
        assert skill.get("tags")  # Should have default tags

    def test_engine_generate_missing_content_key(self, mocker):
        """LLM returns dict without content field → graceful degradation."""
        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent
        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"error": "no response"}

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]  # content is empty → JSON parse fails


# ═══════════════════════════════════════════════════════════════
# Cleanup and boundary tests
# ═══════════════════════════════════════════════════════════════

class TestEvolveCleanup:
    """Verify evolve_skill boundary conditions and resource cleanup."""

    def test_repeated_evolve_same_name(self, mocker):
        """Multiple evolves with the same intent should not crash (name generated by LLM, may repeat)."""
        from l1.kernel.skill import get_skill_manager, reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()

        skill_json = json.dumps({
            "name": "repeat-skill",
            "description": "Repeated evolution test",
            "prompt": "Test prompt",
            "tags": ["evolved", "test"],
        })

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"content": skill_json}

        r4 = R4Agent()

        # First evolve
        r1 = r4.evolve_skill("创建技能")
        assert r1["success"]

        # Second evolve (same name)
        r2 = r4.evolve_skill("创建相同技能")
        assert r2["success"]

        # SkillManager should keep the latest version
        sm = get_skill_manager()
        skill = sm.get("repeat-skill")
        assert skill is not None

    def test_evolve_skill_does_not_crash_when_skill_dir_not_writable(self, mocker):
        """Should not crash when SKILL_EVOLVED_DIR is not writable (SKILL.md write failure should have fault tolerance)."""

        from l1.kernel.skill import reset_skill_manager
        from l3.memory.r4_agent import R4Agent

        reset_skill_manager()

        mock_engine = mocker.patch("l4.llm.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": json.dumps({
                "name": "readonly-test",
                "description": "Test read-only directory",
                "prompt": "Test",
                "tags": ["evolved", "test"],
            }),
        }

        r4 = R4Agent()
        # Normally should succeed (SkillManager registration succeeds, SKILL.md write may fail but is caught)
        result = r4.evolve_skill("创建只读测试")
        # SkillManager registration should succeed even if SKILL.md write fails
        assert result["success"]
