"""AgentLoop tests — reasoning main loop + tool registration + result folding + execution"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestAgentLoopInit:
    """AgentLoop initialization"""

    def test_basic_init(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="test task", agent_id="agent-a")
        assert loop.task == "test task"
        assert loop.agent_id == "agent-a"
        assert loop._tools == []

    def test_init_with_system(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="t", system="system prompt", role="writer")
        assert loop._system == "system prompt"
        assert loop._role == "writer"


class TestAddTool:
    """Tool registration"""

    def test_add_tool_basic(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="test")
        fn = lambda args, agent: {"success": True, "data": "ok"}
        loop.add_tool("test_tool", "A test tool",
                      {"param1": "string"}, fn)
        assert len(loop._tools) == 1
        assert loop._tools[0].name == "test_tool"
        assert loop._tools[0].description == "A test tool"

    def test_add_parallel_safe(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="test")
        fn = lambda a, b: {"success": True}
        loop.add_tool("read_only", "test", {}, fn, parallel_safe=True)
        assert loop._tools[0].name == "read_only"


class TestFoldResult:
    """Result folding (Head+Tail truncation)"""

    def test_fold_long_string(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="x")
        long = "A" * 2000
        r = loop._fold_result({"data": long}, max_chars=100)
        assert "truncated" in r.get("data", "")
        assert "data_truncated" in r
        assert r["data_truncated"] > 0

    def test_fold_short_string(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="x")
        short = "hello"
        r = loop._fold_result({"data": short}, max_chars=100)
        assert r["data"] == "hello"
        assert "data_truncated" not in r

    def test_fold_list(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="x")
        big_list = list(range(100))
        r = loop._fold_result({"items": big_list})
        assert len(r["items"]) == 15  # capped at 15
        assert r["items_total"] == 100

    def test_fold_nested(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="x")
        r = loop._fold_result({"outer": {"inner": "short"}}, max_chars=100)
        assert "inner" in r.get("outer", {})

    def test_truncation_note(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="x")
        r = loop._fold_result({"data": "B" * 2000}, max_chars=100)
        assert "_truncation_note" in r


class TestRegisterTodowrite:
    """todowrite tool auto-registration"""

    def test_todowrite_auto_register(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="test", agent_id="a")
        loop._register_todowrite()
        names = [t.name for t in loop._tools]
        assert "todowrite" in names

    def test_todowrite_not_duplicated(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="test", agent_id="a")
        loop._register_todowrite()
        loop._register_todowrite()
        count = sum(1 for t in loop._tools if t.name == "todowrite")
        assert count == 1


class TestRunBasic:
    """Basic execution (mock mode)"""

    def test_run_returns_dict(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="say hello", agent_id="tester")
        fn = lambda args, agent: {"success": True, "data": "hello back"}
        loop.add_tool("greet", "Greet the user", {"name": "string"}, fn)
        r = loop.run(max_steps=2, timeout=30)
        assert isinstance(r, dict)
        assert "total_elapsed" in r
        assert "total_steps" in r

    def test_run_with_tool_executor(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="test task", agent_id="agent-x")
        results = []
        def my_handler(args, agent):
            results.append(args)
            return {"success": True}
        loop.add_tool("my_tool", "Test", {"arg": "string"}, my_handler)
        r = loop.run(max_steps=3, timeout=30)
        assert isinstance(r, dict)

    def test_run_with_verifier(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="verify test", agent_id="v")
        fn = lambda a, b: {"success": True}
        loop.add_tool("simple", "T", {}, fn)

        class FakeVerifier:
            def check(self, result, task):
                return {"pass": True}
            def consistency_check(self, results, task):
                return {"consistent": True}
            def correction_prompt(self, task, errors):
                return "fix it"

        r = loop.run(max_steps=2, timeout=30, verifier=FakeVerifier())
        assert isinstance(r, dict)
        assert "verifier_used" in r


class TestChatParamsHook:
    """Chat params hook"""

    def test_hook_modifies_kwargs(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="test", agent_id="a")

        def hook(task, agent_id, kwargs):
            kwargs["custom_param"] = "set_by_hook"
            return kwargs

        loop.register_chat_params_hook(hook)
        assert len(loop._chat_params_hooks) == 1

    def test_hook_no_duplicate(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="test")
        def h(t, a, k): return k
        loop.register_chat_params_hook(h)
        loop.register_chat_params_hook(h)
        assert len(loop._chat_params_hooks) == 1


class TestFinish:
    """_finish finalization"""

    def test_finish_adds_elapsed(self):
        from l3.agent_loop import AgentLoop
        loop = AgentLoop(task="test", agent_id="a")
        t0 = time.time()
        r = loop._finish({"success": True}, t0=t0, turns=3, corrections=1)
        assert "total_elapsed" in r
        assert r["total_steps"] == 4
        assert r["success"] is True
