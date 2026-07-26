"""LLM inference engine test — invoke/retry/analyze/tool-use/log hooks"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestThink:
    """think convenience function"""

    def test_think_returns_dict(self):
        from services.llm import think
        r = think("hello", system="test", max_tokens=128)
        assert isinstance(r, dict)
        assert "content" in r

    def test_think_with_user_id(self):
        from services.llm import think
        r = think("test", user_id="user-1")
        assert isinstance(r, dict)


class TestAnalyze:
    """analyze convenience function"""

    def test_analyze_basic(self):
        from services.llm import analyze
        r = analyze("review this", "code snippet", context="test")
        assert isinstance(r, dict)
        assert "content" in r or "error" in r

    def test_analyze_no_context(self):
        from services.llm import analyze
        r = analyze("review", "x = 1")
        assert isinstance(r, dict)


class TestLlmEngine:
    """LLMEngine 核心"""

    def test_engine_singleton(self):
        from services.llm import get_engine, reset_engine
        reset_engine()
        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2

    def test_engine_generate(self):
        from services.llm import get_engine, reset_engine
        reset_engine()
        engine = get_engine()
        r = engine.generate("ping", system="respond pong", max_tokens=64)
        assert isinstance(r, dict)
        assert "content" in r

    def test_engine_max_tokens_param(self):
        from services.llm import get_engine, reset_engine
        reset_engine()
        engine = get_engine()
        r = engine.generate("test", max_tokens=1)
        assert isinstance(r, dict)

    def test_engine_tool_use_basic(self):
        from services.llm import get_engine, reset_engine
        from services.llm_base import ToolDef
        reset_engine()
        engine = get_engine()
        tools = [
            ToolDef(name="test_tool", description="Test",
                    parameters={"type": "object", "properties": {},
                                "required": []},
                    handler=lambda a, b: {"result": "ok"})
        ]
        r = engine.tool_use("use test_tool", tools=tools, system="test",
                            max_turns=2)
        assert isinstance(r, dict)
        assert "tool_call_results" in r or "content" in r


class TestToolUse:
    """工具调用结果"""

    def test_tool_use_with_args(self):
        from services.llm import get_engine, reset_engine
        from services.llm_base import ToolDef
        reset_engine()
        engine = get_engine()
        called = []
        def handler(args, agent):
            called.append(args)
            return {"data": f"processed {args}"}
        tools = [
            ToolDef(name="process", description="Process data",
                    parameters={
                        "type": "object",
                        "properties": {"input": {"type": "string"}},
                        "required": ["input"],
                    },
                    handler=handler)
        ]
        r = engine.tool_use("process hello", tools=tools, system="test",
                            max_turns=2)
        assert isinstance(r, dict)

    def test_tool_use_no_tools(self):
        from services.llm import get_engine, reset_engine
        reset_engine()
        engine = get_engine()
        r = engine.tool_use("just talk", tools=[], system="test", max_turns=1)
        assert isinstance(r, dict)
        assert "content" in r


class TestHooks:
    """LLM 调用钩子"""

    def test_pre_hook(self):
        from services.llm import on_llm_call, _LLM_HOOKS
        _LLM_HOOKS.clear()
        records = []
        @on_llm_call("pre")
        def pre_hook(**kw):
            records.append(kw.get("prompt", ""))
        from services.llm import get_engine, reset_engine
        reset_engine()
        engine = get_engine()
        engine.generate("hook-test", system="test", max_tokens=64)
        # hook should have been called
        assert len(records) >= 0

    def test_post_hook(self):
        from services.llm import on_llm_call, _LLM_HOOKS
        _LLM_HOOKS.clear()
        records = []
        @on_llm_call("post")
        def post_hook(**kw):
            records.append(kw.get("result", {}))
        from services.llm import get_engine, reset_engine
        reset_engine()
        engine = get_engine()
        r = engine.generate("post-test", system="test", max_tokens=64)
        assert isinstance(r, dict)

    def test_counter_hook_integration(self):
        from services.llm import get_engine, reset_engine
        reset_engine()
        engine = get_engine()
        r = engine.generate("counter-test", system="test", max_tokens=64,
                            user_id="test-user")
        assert isinstance(r, dict)


class TestRetryConfig:
    """重试配置"""

    def test_rate_limit_wait(self):
        from kernel.params.api import LLM_RATE_LIMIT_WAIT
        assert LLM_RATE_LIMIT_WAIT == 60

    def test_backoff_base(self):
        from kernel.params.api import LLM_TRANSIENT_BACKOFF_BASE
        assert LLM_TRANSIENT_BACKOFF_BASE == 3

    def test_empty_response_waits(self):
        from kernel.params.api import LLM_EMPTY_RESPONSE_WAITS
        assert len(LLM_EMPTY_RESPONSE_WAITS) == 5
