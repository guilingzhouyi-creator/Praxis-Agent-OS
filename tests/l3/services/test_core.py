"""Service layer tests — cache, llm, agent_loop, cell, scout."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestFileCache:
    def test_agent_isolation(self):
        from l3.memory.cache import get_file_cache
        c = get_file_cache("test-cell")
        c.clear()
        c.set("/project/a.py", "content-a", scope="agent", agent_id="agent_a", ring=1)
        c.set("/project/b.py", "content-b", scope="agent", agent_id="agent_b", ring=2)
        a = c.get("/project/a.py", scope="agent", agent_id="agent_a", ring=1)
        b = c.get("/project/b.py", scope="agent", agent_id="agent_b", ring=2)
        ba = c.get("/project/a.py", scope="agent", agent_id="agent_b", ring=2)
        assert a is not None, "agent A should hit own cache"
        assert b is not None, "agent B should hit own cache"
        assert ba is None, "agent A should miss B cache"

    def test_cell_scope_sharing(self):
        from l3.memory.cache import get_file_cache
        c = get_file_cache("test-cell")
        c.clear()
        c.set("/project/shared.py", "shared", scope="cell")
        sa = c.get("/project/shared.py", scope="cell", agent_id="agent_a")
        sb = c.get("/project/shared.py", scope="cell", agent_id="agent_b")
        assert sa is not None, "cell scope should be visible to A"
        assert sb is not None, "cell scope should be visible to B"

    def test_invalidation(self):
        from l3.memory.cache import get_file_cache
        c = get_file_cache("test-cell")
        c.clear()
        c.set("/project/a.py", "content-a", scope="agent", agent_id="agent_a", ring=1)
        c.invalidate("/project/a.py")
        ai = c.get("/project/a.py", scope="agent", agent_id="agent_a", ring=1)
        assert ai is None, "invalidate should remove entry"

    def test_tag_invalidation(self):
        from l3.memory.cache import get_file_cache
        c = get_file_cache("test-cell")
        c.clear()
        c.set("/project/b.py", "content-b", scope="agent", agent_id="agent_b", ring=2)
        c.invalidate_by_tag("agent:agent_b")
        bi = c.get("/project/b.py", scope="agent", agent_id="agent_b", ring=2)
        assert bi is None, "tag invalidation should remove entry"

    def test_stats_hit_rate(self):
        from l3.memory.cache import get_file_cache
        c = get_file_cache("test-cell")
        c.clear()
        stats = c.stats()
        assert stats["hit_rate"] >= 0


class TestContextRegister:
    def test_store_and_get(self):
        from l3.memory.cache import get_context_register
        ctx = get_context_register("test-cell")
        ctx.clear()
        ctx.store("analysis", {"count": 42}, agent_id="agent_a", entry_type="thought")
        val = ctx.get("analysis")
        assert val is not None and val["count"] == 42

    def test_recent(self):
        from l3.memory.cache import get_context_register
        ctx = get_context_register("test-cell")
        ctx.clear()
        ctx.store("k1", "v1", agent_id="a", entry_type="thought")
        recent = ctx.recent(5)
        assert len(recent) >= 1

    def test_clear(self):
        from l3.memory.cache import get_context_register
        ctx = get_context_register("test-cell")
        ctx.clear()
        assert len(ctx.recent(5)) == 0


class TestLLMEngine:
    def test_mock_generate(self):
        from l1.kernel.settings import get_settings
        from l4.llm import LLMConfig, get_engine, reset_engine
        s = get_settings()
        s.set("llm.provider", "mock")
        try:
            cfg = LLMConfig(provider="mock")
            reset_engine()
            engine = get_engine(cfg)
            r = engine.generate("say hi", system="")
            assert bool(r.get("content", "")), "mock llm should generate content"
            assert r.get("tokens", 0) >= 0
        finally:
            # Clear the L3 override so it doesn't leak into other tests
            # (config_loader's test_llm_handler reads llm.provider).
            # reset() restores the default (ollama), which is fine here.
            s.reset("llm.provider")


class TestAgentLoop:
    def test_run(self):
        from l3.agent.agent_loop import AgentLoop
        calls = []
        def tool_fn(args, agent):
            calls.append(args)
            return {"result": "ok"}
        loop = AgentLoop(task="call test_tool", agent_id="test")
        loop.add_tool("test_tool", "test", {"x": "string"}, tool_fn)
        r = loop.run(max_steps=3)
        assert r.get("success"), "agentloop should run"
        assert bool(r.get("answer", "")), "agentloop should produce answer"


class TestCardBuilder:
    def test_build_card(self):
        from l3.card.card_builder import build_card
        card = build_card("c-001", "build the project", "src/core", priority=5)
        assert card is not None
        assert len(card.phases) >= 1
        # CardUnified: count tasks across all phases
        total_tasks = sum(len(p.tasks) for p in card.phases)
        assert total_tasks >= 1

    def test_fix_card_detected(self):
        from l3.card.card_builder import build_card
        card = build_card("c-002", "fix bug in login", "src/api")
        assert "investigate" in [p.name for p in card.phases]


class TestCardYaml:
    def test_load_card(self, tmp_path):
        yaml_content = """
card:
  id: "test-yaml"
  intent: "test"
  domain: "."
  mode: EXECUTE
phases:
  - name: test
    mode: SEQUENTIAL
    steps:
      - action: think
        agent: reader
        target: "test"
"""
        tmp = str(tmp_path / "_test_card.yaml")
        with open(tmp, "w") as f:
            f.write(yaml_content)
        from l3.card.card_yaml import load_card
        lr = load_card(tmp)
        os.remove(tmp)
        assert lr.get("success"), "yaml card should load"
        if lr.get("success"):
            # CardUnified: count tasks across all phases
            total = sum(len(p.tasks) for p in lr["card"].phases)
            assert total >= 1


class TestScoutPool:
    def test_stats(self):
        from l3.agent.scout import get_pool
        pool = get_pool()
        stats = pool.stats()
        assert stats.get("max_total", 0) > 0

    def test_commission(self):
        from l3.agent.scout import get_pool
        pool = get_pool()
        r = pool.commission("test-agent", "say hello")
        assert r.get("success") or r.get("error"), "scout should return or error"


class TestAgentTerminal:
    def test_boot_and_process(self):
        import time

        # Ensure LLM mock mode so keepalive thread won't block
        from l1.kernel.settings import get_settings
        s = get_settings()
        s.set("llm.provider", "mock")
        s.set("llm.model", "test")
        try:
            from l4.llm import get_engine, reset_engine
            reset_engine()
            # Force-create engine with mock config
            _ = get_engine()
            from l1.kernel.process import get_table as _pt
            from l3.agent_terminal import TerminalCard, get_terminal, reset_terminals
            pcb = _pt().spawn("test-agent-term", role="test", ring=1)
            pcb.identity_verified = True
            term = get_terminal("test-agent-term", role="test", territory=[".", ".."], cell_id="test")
            boot_r = term.boot()
            assert boot_r.get("success"), "agent terminal should boot"
            # Poll for terminal readiness instead of fixed sleep
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if term.status and term.status.name == "IDLE":
                    break
                time.sleep(0.05)
            card = TerminalCard(action="read_file", target=__file__,
                                params={}, sender="test")
            cid = term.dispatch(card)
            result = term.wait_for_result(cid, timeout=5)
            assert result is not None and result.success, "agent terminal should process card"
            tools = term.list_tools()
            assert isinstance(tools, list)
            report = term.status_report()
            assert report.get("alive"), "terminal status should show alive"
            term.shutdown()
            reset_terminals()
        finally:
            # Clear the L3 overrides so they don't leak into other tests
            # (config_loader's test_llm_handler reads llm.provider).
            # reset() restores the defaults (ollama / qwen2.5-coder:7b).
            s.reset("llm.provider")
            s.reset("llm.model")
