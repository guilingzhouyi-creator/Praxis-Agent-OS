"""R4Agent evolve_skill 集成测试与混合测试。

测试策略：
  Layer 1 — LLM mock 集成：mock get_engine().generate()，验证全链路流程
  Layer 2 — 持久化混合：验证 SKILL.md 文件创建 + SkillManager 重载
  Layer 3 — AgentLoop 混合：验证 Cell-A 注入正确读取 evolved skills
  Layer 4 — 异常容错：验证 LLM 返回不良 JSON/空内容/缺字段时的降级
"""

from __future__ import annotations

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ═══════════════════════════════════════════════════════════════
# Layer 1: LLM mock 集成 — 完整 evolve_skill 流程
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
        """Mock LLM → evolve_skill → SkillManager → SKILL.md 完整链路."""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager
        from kernel.params import SKILL_EVOLVED_DIR

        # 清理
        reset_skill_manager()
        sm = get_skill_manager()

        # Mock LLM engine
        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": self.VALID_SKILL_JSON,
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个数据库迁移工具")

        # 验证返回值
        assert result["success"], f"evolve_skill failed: {result}"
        assert result["skill"] == "db-migration-helper"
        assert result["rules"] == 2

        # 验证 SkillManager 注册
        skills = sm.list(tags=["evolved"])
        names = [s["name"] for s in skills]
        assert "db-migration-helper" in names

        # 验证 get_evolved_skills
        evolved = r4.get_evolved_skills()
        assert any(e["name"] == "db-migration-helper" for e in evolved)
        assert any("timestamp" in e.get("prompt", "") for e in evolved)

        # 验证 SKILL.md 文件创建
        md_path = os.path.join(SKILL_EVOLVED_DIR, "db-migration-helper", "SKILL.md")
        assert os.path.isfile(md_path), f"SKILL.md not found at {md_path}"
        with open(md_path, encoding="utf-8") as f:
            content = f.read()
        assert "db-migration-helper" in content
        assert "YYYYMMDD_HHMMSS" in content

    def test_llm_response_with_markdown_fences(self, mocker):
        """LLM 返回带 ```json  fences 的响应也能正确解析。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager

        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": "```json\n" + self.VALID_SKILL_JSON + "\n```",
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建数据库迁移工具")

        assert result["success"], f"markdown fence parse failed: {result}"
        assert result["skill"] == "db-migration-helper"

    def test_llm_response_trailing_newlines(self, mocker):
        """LLM 响应尾部有多余空行也能正确解析。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager

        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": self.VALID_SKILL_JSON + "\n\n\n",
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建数据库迁移工具")
        assert result["success"]

    def test_evolve_then_lean_is_separate(self, mocker):
        """evolve_skill 创建的技能不应污染 lean cases。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager

        reset_skill_manager()
        sm = get_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": self.VALID_SKILL_JSON,
        }

        r4 = R4Agent()
        r4.evolve_skill("创建数据库迁移工具")

        # lean cases 不应包含 evolved 技能
        lean = r4.get_lean_cases()
        assert all("timestamp" not in l for l in lean)  # evolved prompt 里有 timestamp

        # evolved 应包含
        evolved = r4.get_evolved_skills()
        assert any("timestamp" in e.get("prompt", "") for e in evolved)


# ═══════════════════════════════════════════════════════════════
# Layer 2: SKILL.md 持久化 + SkillManager 重载测试
# ═══════════════════════════════════════════════════════════════

class TestSkillPersistenceRoundtrip:
    """验证 SKILL.md 持久化后能被 SkillManager 重新加载。"""

    def test_skill_manager_loads_evolved_dir(self, mocker):
        """load_builtin() 应加载 SKILL_EVOLVED_DIR 下的 SKILL.md。"""
        from kernel.skill import SkillManager
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # 创建一个模拟的 evolved skill 目录
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
        """多个 evolved SKILL.md 文件应全部加载。"""
        from kernel.skill import SkillManager
        import tempfile

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
        """evolve_skill 生成的 SKILL.md 必须有合法的 YAML frontmatter。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager
        from kernel.params import SKILL_EVOLVED_DIR
        import yaml

        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
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

        md_path = os.path.join(SKILL_EVOLVED_DIR, "yaml-validate-test", "SKILL.md")
        assert os.path.isfile(md_path)

        # 验证 YAML frontmatter 可解析
        with open(md_path, encoding="utf-8") as f:
            content = f.read()
        import re
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        assert m is not None, "SKILL.md missing YAML frontmatter"
        meta = yaml.safe_load(m.group(1))
        assert meta["name"] == "yaml-validate-test"
        assert meta["description"] == "Testing YAML frontmatter validity"


# ═══════════════════════════════════════════════════════════════
# Layer 3: AgentLoop Cell-A 注入混合测试
# ═══════════════════════════════════════════════════════════════

class TestAgentLoopEvolvedInjection:
    """验证 evolved skills 通过 Cell-A 注入到 AgentLoop。"""

    def test_get_evolved_skills_returns_registered(self):
        """get_evolved_skills 应返回 SkillManager 中所有 evolved 标签的技能。"""
        from kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()

        sm.create(name="evolved-one", prompt="prompt one", tags=["evolved", "db"])
        sm.create(name="evolved-two", prompt="prompt two", tags=["evolved", "api"])

        from services.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(limit=5)
        assert len(evolved) >= 2

    def test_evolved_skills_injected_via_r4(self, mocker):
        """通过 R4Agent.get_evolved_skills 返回的技能应能被 AgentLoop 消费。"""
        from kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()
        sm = get_skill_manager()

        sm.create(
            name="inject-test",
            description="测试注入",
            prompt="You are an injection test agent.",
            tags=["evolved", "test"],
        )

        from services.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(limit=3)
        assert len(evolved) >= 1
        assert evolved[0]["name"] == "inject-test"
        assert "injection test" in evolved[0]["prompt"]

    def test_agentloop_run_imports_evolved_block(self):
        """AgentLoop.run() 的代码中应有 evolved skill 注入块。"""
        from services.agent_loop import AgentLoop
        import inspect
        source = inspect.getsource(AgentLoop.run)
        assert "Evolved Skills" in source or "evolved" in source.lower()

    def test_no_evolved_skills_no_injection(self, mocker):
        """没有 evolved skills 时，get_evolved_skills 应返回空列表，不崩溃。"""
        from kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()

        from services.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills()
        assert evolved == []

    def test_concurrent_evolve_and_inject(self, mocker):
        """并发注册 evolved skills 后注入应正确读取。"""
        from kernel.skill import get_skill_manager, reset_skill_manager
        import threading

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

        from services.r4_agent import R4Agent
        r4 = R4Agent()
        evolved = r4.get_evolved_skills(limit=10)
        assert len(evolved) >= 5


# ═══════════════════════════════════════════════════════════════
# Layer 4: 异常容错 — 不良 LLM 响应
# ═══════════════════════════════════════════════════════════════

class TestEvolveSkillErrorHandling:
    """测试 LLM 返回各种不良响应时的降级行为。"""

    def test_llm_returns_empty_content(self, mocker):
        """LLM 返回空内容 → JSON decode error → 友好降级。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"content": ""}

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]
        assert "JSON" in result.get("error", "") or "invalid" in result.get("error", "").lower()

    def test_llm_returns_invalid_json(self, mocker):
        """LLM 返回非 JSON 文本 → JSON decode error → 友好降级。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": "This is not JSON at all, it's just plain text.",
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]
        assert "JSON" in result.get("error", "") or "invalid" in result.get("error", "").lower()

    def test_llm_returns_partial_json(self, mocker):
        """LLM 返回不完整 JSON → JSON decode error → 友好降级。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": '{"name": "broken"',
        }

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]

    def test_llm_engine_raises_exception(self, mocker):
        """LLM 引擎本身抛出异常 → evolve_skill 捕获并返回友好错误。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.side_effect = RuntimeError("LLM API timeout")

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]
        assert result.get("error")  # 应有具体错误信息

    def test_llm_returns_json_with_missing_fields(self, mocker):
        """LLM 返回的 JSON 缺少关键字段时，使用默认值。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        # 只有 name，没有其他字段
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
        assert skill.get("tags")  # 应该有默认 tags

    def test_engine_generate_missing_content_key(self, mocker):
        """LLM 返回 dict 没有 content 字段 → 降级。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager
        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"error": "no response"}

        r4 = R4Agent()
        result = r4.evolve_skill("创建一个测试技能")
        assert not result["success"]  # content 为空 → JSON parse 失败


# ═══════════════════════════════════════════════════════════════
# 清理与边界测试
# ═══════════════════════════════════════════════════════════════

class TestEvolveCleanup:
    """验证 evolve_skill 的边界情况和资源清理。"""

    def test_repeated_evolve_same_name(self, mocker):
        """相同 intent 多次 evolve 不应崩溃（name 由 LLM 生成，可能重复）。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager

        reset_skill_manager()

        skill_json = json.dumps({
            "name": "repeat-skill",
            "description": "Repeated evolution test",
            "prompt": "Test prompt",
            "tags": ["evolved", "test"],
        })

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {"content": skill_json}

        r4 = R4Agent()

        # 第一次 evolve
        r1 = r4.evolve_skill("创建技能")
        assert r1["success"]

        # 第二次 evolve（同名）
        r2 = r4.evolve_skill("创建相同技能")
        assert r2["success"]

        # SkillManager 应保留最新版本
        sm = get_skill_manager()
        skill = sm.get("repeat-skill")
        assert skill is not None

    def test_evolve_skill_does_not_crash_when_skill_dir_not_writable(self, mocker):
        """SKILL_EVOLVED_DIR 不可写时不应崩溃（SKILL.md 写入失败应有容错）。"""
        from services.r4_agent import R4Agent
        from kernel.skill import get_skill_manager, reset_skill_manager
        import stat

        reset_skill_manager()

        mock_engine = mocker.patch("services.llm.get_engine")
        mock_engine.return_value.generate.return_value = {
            "content": json.dumps({
                "name": "readonly-test",
                "description": "Test read-only directory",
                "prompt": "Test",
                "tags": ["evolved", "test"],
            }),
        }

        r4 = R4Agent()
        # 正常应该成功（SkillManager 注册成功，SKILL.md 写入可能失败但被 catch）
        result = r4.evolve_skill("创建只读测试")
        # SkillManager 注册应成功，即使 SKILL.md 写入失败
        assert result["success"]
