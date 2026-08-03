"""Prompt Engine integration test — context assembly + layered Prompt + API"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tempfile


class TestContextAssembler:
    """Context assembler"""

    def test_empty(self):
        from l3.services.prompt_engine import ContextAssembler
        ca = ContextAssembler()
        assert ca.assemble() == ""

    def test_add_string(self):
        from l3.services.prompt_engine import ContextAssembler
        ca = ContextAssembler()
        ca.add_string("hello world", source="test")
        result = ca.assemble()
        assert "hello world" in result
        stats = ca.stats()
        assert stats["total_items"] == 1

    def test_priority_sort(self):
        from l3.services.prompt_engine import ContextAssembler
        ca = ContextAssembler()
        ca.add_string("low priority", source="a", priority=0.1)
        ca.add_string("HIGH PRIORITY", source="b", priority=0.9)
        result = ca.assemble()
        # HIGH PRIORITY should come first
        assert result.index("HIGH PRIORITY") < result.index("low priority")

    def test_token_budget(self):
        from l3.services.prompt_engine import ContextAssembler
        ca = ContextAssembler()
        ca.add_string("A" * 4000, source="big", priority=0.5)
        ca.add_string("B" * 4000, source="big2", priority=0.5)
        result = ca.assemble(max_tokens=500)
        # Should be truncated
        assert len(result) < 8000

    def test_add_file_context(self):
        from l3.services.prompt_engine import ContextAssembler
        ca = ContextAssembler()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("def test():\n    pass\n")
            tmp = f.name
        try:
            ca.add_file_context([tmp], max_chars_per_file=2000)
            result = ca.assemble()
            assert "def test()" in result
        finally:
            os.unlink(tmp)

    def test_reset(self):
        from l3.services.prompt_engine import ContextAssembler
        ca = ContextAssembler()
        ca.add_string("data", source="test")
        ca.reset()
        assert ca.assemble() == ""


class TestPromptBuilder:
    """Layered Prompt construction"""

    def test_build_default(self):
        from l3.services.prompt_engine import PromptBuilder
        pb = PromptBuilder()
        pt = pb.build(role="default", task="fix bug", context="some context")
        full = pt.build()
        assert "fix bug" in full
        assert "NOMOS Praxis" in full
        assert pt.estimate_tokens() > 0

    def test_build_l3a(self):
        from l3.services.prompt_engine import PromptBuilder
        pb = PromptBuilder()
        pt = pb.build(role="l3a", task="parse this")
        full = pt.build()
        assert "L3A" in full
        assert "parse this" in full

    def test_constraints(self):
        from l3.services.prompt_engine import PromptBuilder
        pb = PromptBuilder()
        pt = pb.build(role="default", task="task", constraints=["no_test_modification"])
        full = pt.build()
        assert "Do NOT modify any test files" in full

    def test_register_template(self):
        from l3.services.prompt_engine import PromptBuilder
        pb = PromptBuilder()
        r = pb.register_template("custom_role", "You are a custom agent.")
        assert r["success"]
        pt = pb.build(role="custom_role", task="do it")
        full = pt.build()
        assert "custom agent" in full
        assert "do it" in full

    def test_list_templates(self):
        from l3.services.prompt_engine import PromptBuilder
        pb = PromptBuilder()
        pb.register_template("custom_role", "You are a custom agent.")
        r = pb.list_templates()
        assert r["success"]
        assert "custom_role" in r["templates"]
        assert r["count"] >= 1


class TestPromptEngine:
    """Full PromptEngine"""

    def test_build_prompt_basic(self):
        from l3.services.prompt_engine import PromptEngine
        engine = PromptEngine()
        r = engine.build_prompt(task="fix login bug", role="default")
        assert r["success"]
        assert "fix login bug" in r["prompt"]
        assert r["estimated_tokens"] > 0

    def test_build_context_only(self):
        from l3.services.prompt_engine import PromptEngine
        engine = PromptEngine()
        r = engine.build_context_only(file_paths=None)
        assert r["success"]
        assert r["context"] == ""  # no files given

    def test_get_templates(self):
        from l3.services.prompt_engine import PromptEngine
        engine = PromptEngine()
        engine.register_template("custom_role", "You are a custom agent.")
        r = engine.get_templates()
        assert r["success"]
        assert "custom_role" in r["templates"]
        assert r["count"] >= 1


class TestApiHandlers:
    """API Handler function-level test"""

    def test_handle_prompt_build(self):
        from l3.services.prompt_engine import handle_prompt_build
        r = handle_prompt_build({"task": "refactor auth", "role": "default"})
        assert r["success"]
        assert "refactor auth" in r["prompt"]

    def test_handle_prompt_context(self):
        from l3.services.prompt_engine import handle_prompt_context
        r = handle_prompt_context({})
        assert r["success"]

    def test_handle_prompt_templates(self):
        from l3.services.prompt_engine import handle_prompt_templates
        r = handle_prompt_templates()
        assert r["success"]

    def test_handle_prompt_template_register(self):
        from l3.services.prompt_engine import handle_prompt_template_register
        r = handle_prompt_template_register({"name": "my_role", "template": "You are my role."})
        assert r["success"]

    def test_handle_prompt_template_missing(self):
        from l3.services.prompt_engine import handle_prompt_template_register
        r = handle_prompt_template_register({"name": ""})
        assert not r["success"]
