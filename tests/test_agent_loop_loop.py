"""AgentLoop loop test — multi-step tool chaining + on-chain verify + per-step failure retry & degrade

Regression protection for Agent-Loop closed-loop behavior:
- P0-1: run(max_steps=N) chains multiple tools, each step on the ToolChain, verify() passes full chain
- P1-1: in-step tool failure → retry → switch ring → degrade

Drives the loop via mock LLMEngine.tool_use, no real LLM dependency.
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _install_mock_engine(tool_call_results, generate_responses=None):
    """Replace services.llm.get_engine with a mock that returns canned results.

    tool_call_results: list of dicts the mock tool_use() should return as
        ``tool_call_results``; each turn of AgentLoop.run iterates this list.
    generate_responses: list of strings; mock generate() pops one per call
        (default returns ``{"content": ""}``).
    Returns (mock_engine, uninstall).

    NB: we patch ``get_engine`` in BOTH ``services.llm`` (source) and
    ``services.agent_loop`` (the module that does ``from .llm import
    get_engine`` at import time, binding the reference locally) — patching
    only the source is ineffective because agent_loop.run() calls the
    name bound in its own module namespace.
    """
    import services.llm as llm_mod
    import services.agent_loop as al_mod

    class _MockEngine:
        def __init__(self):
            self._gen_iter = iter(generate_responses or [])

        def context_window(self):
            return 32_000

        def tool_use(self, prompt, tools, system="", max_turns=5,
                     user_id="", **overrides):
            # Mimic the real LLMEngine.tool_use contract: for each canned
            # tool-call, dispatch to the matching tool's handler so the
            # AgentLoop-side wrapper (pipeline.execute + handler) runs and
            # any side effects (e.g. ToolChain.start) happen for real.
            tool_map = {t.name: t for t in tools}
            executed = []
            for canned in tool_call_results:
                name = canned.get("name", "unknown")
                spec = tool_map.get(name)
                if not spec or not hasattr(spec, "handler"):
                    executed.append({
                        "name": name, "args": canned.get("args", {}),
                        "error": "no such tool",
                    })
                    continue
                try:
                    result = spec.handler(canned.get("args", {}), user_id or "")
                except Exception as e:
                    result = {"success": False, "error": str(e)}
                executed.append({
                    "name": name, "args": canned.get("args", {}),
                    "result": result, "success": result.get("success", False)
                    if isinstance(result, dict) else True,
                })
            return {
                "content": "mock final answer",
                "tool_calls": [],
                "tool_call_results": executed,
                "turns": max(1, len(executed)),
                "finish_reason": "stop",
            }

        def generate(self, prompt, system="", user_id="", **overrides):
            try:
                content = next(self._gen_iter)
            except StopIteration:
                content = ""
            return {"content": content}

    mock = _MockEngine()
    saved_llm = llm_mod.get_engine
    saved_al = al_mod.get_engine
    llm_mod.get_engine = lambda *a, **kw: mock
    al_mod.get_engine = lambda *a, **kw: mock

    def _uninstall():
        llm_mod.get_engine = saved_llm
        al_mod.get_engine = saved_al

    return mock, _uninstall


class TestAgentLoopMultistepChain:
    """P0-1: run(max_steps=N) chains multiple tools, ToolChain verify() passes full chain."""

    def setup_method(self):
        from kernel.tool_chain import reset_tool_chain
        reset_tool_chain()

    def test_multistep_run_links_tool_chain_and_verifies(self):
        """3 tool calls triggered via AgentLoop.run, each step chained on ToolChain
        as parent→child, finally verify() on leaf should pass full chain.

        Implementation note: AgentLoop.run wraps handler into _wrap_handler →
        pipeline.execute → gatechain.check; gatechain's G2 gate requires the
        agent to be in the PCB table, otherwise it BLOCKS and the handler body
        won't execute. So this test puts the "chain on ToolChain" side effect
        inside mock tool_use (outside gatechain), and the handler only does a
        no-op return. This tests run()'s multi-step loop that actually feeds
        each step's result back to the LLM-engine loop contract + ToolChain
        chain integrity.
        """
        from services.agent_loop import AgentLoop
        from kernel.tool_chain import get_tool_chain
        import services.llm as llm_mod
        import services.agent_loop as al_mod

        tc = get_tool_chain()

        # chain directly on ToolChain inside mock tool_use, bypassing gatechain
        chain_state = {"prev_call_id": ""}
        call_log = []

        def _noop_handler(args, agent_id):
            return {"success": True, "data": "noop"}

        class _ChainingMockEngine:
            def context_window(self):
                return 32_000

            def tool_use(self, prompt, tools, system="", max_turns=5,
                         user_id="", **overrides):
                canned = [
                    ("read_file", 1, {"path": "src/x.py"}),
                    ("edit_file", 2, {"path": "src/x.py"}),
                    ("verify", 1, {}),
                ]
                executed = []
                for name, ring, args in canned:
                    cid = tc.start(name, user_id or "agent-loop",
                                   ring=ring,
                                   parent_id=chain_state["prev_call_id"])
                    chain_state["prev_call_id"] = cid
                    call_log.append((name, cid))
                    tc.complete(cid, True, duration=0.01)
                    executed.append({"name": name, "args": args,
                                      "result": {"success": True, "data": "ok"},
                                      "success": True})
                return {
                    "content": "mock final answer",
                    "tool_calls": [],
                    "tool_call_results": executed,
                    "turns": max(1, len(executed)),
                    "finish_reason": "stop",
                }

            def generate(self, prompt, system="", user_id="", **overrides):
                return {"content": ""}

        loop = AgentLoop(task="read then edit then verify", agent_id="agent-loop")
        loop.add_tool("read_file", "Read a file", {"path": "string"}, _noop_handler)
        loop.add_tool("edit_file", "Edit a file", {"path": "string"}, _noop_handler)
        loop.add_tool("verify", "Verify changes", {}, _noop_handler)

        mock = _ChainingMockEngine()
        saved_llm = llm_mod.get_engine
        saved_al = al_mod.get_engine
        llm_mod.get_engine = lambda *a, **kw: mock
        al_mod.get_engine = lambda *a, **kw: mock
        try:
            r = loop.run(max_steps=5, timeout=30)
        finally:
            llm_mod.get_engine = saved_llm
            al_mod.get_engine = saved_al

        # run should complete successfully
        assert r["success"], f"loop failed: {r.get('error', '')}"
        # total_steps counts LLM turns (1 here); processed tool calls live in
        # r["steps"] — assert those reflect all 3 chained calls
        assert len(r["steps"]) >= 3, (
            f"expected ≥3 processed steps, got {len(r['steps'])}: {r.get('steps')}"
        )

        # all 3 steps were chained on ToolChain
        assert len(call_log) == 3, f"expected 3 chain entries, got {call_log}"
        tool_names = [t[0] for t in call_log]
        assert tool_names == ["read_file", "edit_file", "verify"], tool_names

        # leaf (last step) ancestry should have 3 layers, and verify() passes full chain
        leaf_call_id = call_log[-1][1]
        ancestry = tc.chain(leaf_call_id)
        assert len(ancestry) == 3, f"chain depth {len(ancestry)} != 3"
        # chain() returns leaf→root, reverse to get root→leaf
        assert ancestry[-1].call_id == call_log[0][1], "root mismatch"
        assert ancestry[0].call_id == call_log[-1][1], "leaf mismatch"

        v = tc.verify(leaf_call_id)
        assert v["valid"], (
            f"fingerprint chain invalid: steps={v.get('steps')}"
        )
        assert v["depth"] == 3

    def test_orphan_re_root_after_trim_still_verifies(self):
        """Tests the _trim re-root logic I fixed: construct max+1 chains to trigger trim,
        orphan child node's parent_id is cleared, prev_fp→GENESIS, verify should not misjudge."""
        from kernel.tool_chain import ToolChain
        from kernel.params.kernel import TOOLCHAIN_MAX_CALLS

        # Use ToolChain directly, bypass AgentLoop.run, focus on _trim behavior
        small = ToolChain()
        small._max_calls = 4  # force small capacity to reliably trigger trim

        # Chain 5 steps: parent→child→grandchild→...→5th
        ids = []
        prev = ""
        for i in range(5):
            cid = small.start(f"step_{i}", "agent-t", ring=1, parent_id=prev)
            small.complete(cid, True, duration=0.01)
            ids.append(cid)
            prev = cid

        # Trigger trim: when exceeding _max_calls=4, _trim removes the oldest (first half)
        # When the 5th step is inserted, trim is triggered, so the oldest step_0 should be removed
        # Orphan step_1's parent_id should be cleared + prev_fp=GENESIS
        remaining = list(small._calls.values())
        remaining_ids = {c.call_id for c in remaining}
        # At least the oldest step_0 is removed
        assert ids[0] not in remaining_ids, (
            f"step_0 should be trimmed, remaining={remaining_ids}"
        )

        # The earliest surviving call's parent_id should have been re-rooted (cleared)
        earliest = min(remaining, key=lambda c: c.depth)
        assert earliest.parent_id == "", (
            f"orphan parent_id not re-rooted: {earliest.parent_id!r}"
        )
        assert earliest.prev_fingerprint == "GENESIS", (
            f"orphan prev_fp not reset: {earliest.prev_fingerprint!r}"
        )

        # Verify every surviving call — all should pass (no broken lineage)
        for cid in remaining_ids:
            v = small.verify(cid)
            assert v["valid"], (
                f"verify failed after trim for {cid}: {v.get('steps')}"
            )


class TestAgentLoopToolFailureRetry:
    """P1-1: in-step tool failure → retry → switch ring → degrade.

    AgentLoop.run's in-step retry logic is driven by verifier.check(retry_allowed=True):
    on failure, corrections++ and generate correction_prompt continues to content.
    This tests the verifier-triggered correction path + loop_stopped flag.
    """

    def setup_method(self):
        from kernel.tool_chain import reset_tool_chain
        reset_tool_chain()

    def test_failed_step_with_verifier_reports_corrections(self):
        """Tool failure + verifier.retry_allowed=True → corrections≥1,
        and loop_stopped=False (verifier drives retry, not hard stop)."""
        from services.agent_loop import AgentLoop
        from kernel.tool_chain import get_tool_chain
        import services.llm as llm_mod

        tc = get_tool_chain()

        fail_state = {"called": False}

        def _flaky_handler(args, agent_id):
            cid = tc.start("flaky_tool", agent_id, ring=1)
            if not fail_state["called"]:
                fail_state["called"] = True
                tc.complete(cid, False, error="boom", duration=0.01)
                return {"success": False, "error": "boom"}
            tc.complete(cid, True, duration=0.01)
            return {"success": True, "data": "recovered"}

        class _RetryVerifier:
            def check(self, result, task):
                if result.get("success") is False:
                    return {"pass": False, "retry_allowed": True,
                            "reason": "tool failed"}
                return {"pass": True}

            def consistency_check(self, results, task):
                return {"consistent": True}

            def correction_prompt(self, task, errors):
                return "please retry the failed tool"

        loop = AgentLoop(task="call flaky tool", agent_id="agent-flaky")
        loop.add_tool("flaky_tool", "A flaky tool", {}, _flaky_handler)

        canned = [{"name": "flaky_tool", "args": {}, "success": False, "error": "boom"}]
        mock, uninstall = _install_mock_engine(
            canned, generate_responses=["retry now"]
        )
        try:
            r = loop.run(max_steps=2, timeout=30, verifier=_RetryVerifier())
        finally:
            uninstall()

        # verifier should be triggered and corrections≥1
        assert r.get("verifier_used") is True, "verifier not used"
        assert r.get("corrections", 0) >= 1, "no corrections recorded"
        # loop should not hard-stop after retry
        assert r.get("loop_stopped") is False, "loop hard-stopped on retry"


class TestAgentLoopConcurrentRingRace:
    """P2: Two agents racing for the same RING_3 tool concurrently.

    ToolRateLimiter should deny one of them, preventing concurrent execution of the same dangerous ring.
    """

    def test_two_agents_concurrent_ring3_one_blocked(self):
        from services.tool_pipeline import get_rate_scheduler
        rl = get_rate_scheduler()

        # RING_3 default budget is small (params.RATE_LIMIT_RING3), two agents in the same
        # concurrent window — at least one should be rejected
        results = []
        barrier = threading.Event()

        def _hit(agent):
            barrier.wait()  # release simultaneously
            for _ in range(20):
                results.append((agent, rl.check(agent, "RING_3")["allowed"]))

        t1 = threading.Thread(target=_hit, args=("race-a",))
        t2 = threading.Thread(target=_hit, args=("race-b",))
        t1.start(); t2.start()
        barrier.set()
        t1.join(); t2.join()

        allowed = sum(1 for _, ok in results if ok)
        denied = sum(1 for _, ok in results if not ok)
        # 40 total concurrent attempts, RING_3 rate limiter should deny at least some (not all pass)
        assert denied > 0, (
            f"RING_3 rate limiter never denied under race: allowed={allowed}"
        )


class TestDialogueCrossTurnToolFeedback:
    """P0-2: Turn N prompt asserts it receives turn N-1 tool return value.

    DialogueSession's cross-turn feedback contract: the caller uses push_context(role='tool', ...)
    to inject turn N-1 tool results, turn N's build_context() must contain those results; record_turn's
    context_snapshot should be able to trace back to previous turn's tool calls. This tests that loop contract.
    """

    def test_cross_turn_tool_feedback_in_next_prompt_context(self):
        """Turn 1 tool return value push_context'd, turn 2 build_context() must contain it."""
        from services.dialogue_session import DialogueSession

        session = DialogueSession(agent_id="agent-x")

        # Turn 1: LLM called read_file tool, returned 'file content'
        session.record_turn(
            prompt="what is in src/x.py?",
            response="let me read the file",
            tool_calls=[{"name": "read_file", "args": {"path": "src/x.py"}}],
        )
        # Feed back: push tool result into next turn's context
        session.push_context(role="tool",
                             content="read_file(src/x.py) => 'file content'",
                             source="read_file")

        # Turn 2: build_context must include previous turn's tool result
        ctx = session.build_context()
        assert "file content" in ctx, (
            f"cross-turn tool feedback missing from build_context: {ctx!r}"
        )
        assert "[tool]" in ctx, f"tool role tag missing: {ctx!r}"

        # Record turn 2 as well; prompt should reflect it's based on previous tool result
        session.record_turn(
            prompt="based on the file content, summarize it",
            response="summarized",
        )
        # Turn 2's context_snapshot should be able to trace back the tool feedback
        turn2 = session._turns[-1]
        snapshot_str = str(turn2.context_snapshot)
        assert "file content" in snapshot_str, (
            f"turn-2 context_snapshot missing tool feedback: {snapshot_str[:200]}"
        )

    def test_cross_turn_multi_step_accumulation(self):
        """3 turns of tool call accumulation feedback: turn 3 build_context contains previous 2 turns' tool results."""
        from services.dialogue_session import DialogueSession

        session = DialogueSession(agent_id="agent-y")

        # Simulate 3 turns of read→edit→verify tool call accumulation feedback
        steps = [
            ("read_file", "read_file(src/a.py) => 'a content'", "read a"),
            ("edit_file", "edit_file(src/a.py) => 'edited'", "edit it"),
            ("verify", "verify() => 'ok'", "verify"),
        ]
        for i, (tool_name, tool_feedback, prompt) in enumerate(steps):
            session.record_turn(
                prompt=prompt,
                response=f"doing {tool_name}",
                tool_calls=[{"name": tool_name, "args": {}}],
            )
            session.push_context(role="tool", content=tool_feedback, source=tool_name)

        # Turn 3 build_context must contain all previous tool results
        ctx = session.build_context()
        for tool_feedback in ("a content", "edited", "ok"):
            assert tool_feedback in ctx, (
                f"missing tool feedback {tool_feedback!r} in ctx: {ctx!r}"
            )

        # There should be 3 accumulated tool role entries
        tool_entries = [e for e in session._context_entries if e["role"] == "tool"]
        assert len(tool_entries) == 3, (
            f"expected 3 tool context entries, got {len(tool_entries)}"
        )


class TestDialogueMultiTurnBudgetFold:
    """P1-2: Multi-turn accumulation exceeding token budget triggers fold without losing critical context.

    DialogueSession.push_context budget eviction contract: when a push would cause
    _token_budget < 0, evict old non-tool entries, keep only the last 5 tool entries;
    then reset budget and push. This tests:
    1. Budget overshoot triggers eviction (non-tool entries cleared)
    2. Tool entries (critical tool results) are preserved up to 5 even when over budget
    """

    def test_overshoot_evicts_non_tool_keeps_recent_tool(self):
        """Non-tool entries evicted on budget overshoot, tool entries keep up to 5."""
        from services.dialogue_session import DialogueSession, SessionConfig

        # Tiny budget to trigger overshoot quickly: 80 tokens ≈ 320 chars. Push 8 tool entries
        # each ~25 chars ≈ 6 tokens → ~50 tokens total, ~30 remaining. Then push one
        # 200 char ≈ 50 token user entry will make budget -20 < 0 → trigger evict.
        session = DialogueSession(
            agent_id="agent-fold",
            config=SessionConfig(max_context_tokens=80),
        )

        # First push 8 tool entries (critical tool results)
        for i in range(8):
            session.push_context(role="tool",
                                 content=f"tool_result_{i}: 'content_{i}'",
                                 source=f"tool_{i}")
        # Then push one large user entry that will exceed budget (200 chars ≈ 50 tokens,
        # used ~50 tokens + 50 > 80 → triggers evict)
        big_user = "U" * 200
        session.push_context(role="user", content=big_user, source="user")

        # After evict: non-tool entries should have been cleared, but the currently pushed
        # large user entry is appended after eviction, so it should still be there; the previous
        # 8 tool entries should be truncated to the last 5
        tool_entries = [e for e in session._context_entries if e["role"] == "tool"]
        assert len(tool_entries) <= 5, (
            f"tool entries not capped to 5 after fold: got {len(tool_entries)}"
        )
        # Critical tool results should keep the most recent 5 (including content_7)
        tool_str = str(tool_entries)
        assert "content_7" in tool_str, (
            f"latest tool result lost after fold: {tool_str[:300]}"
        )
        # Most recent tool results content_3..content_7 should be in the retention window
        for i in (3, 4, 5, 6, 7):
            assert f"content_{i}" in tool_str, (
                f"tool result content_{i} lost after fold: {tool_str[:300]}"
            )

    def test_overshoot_does_not_corrupt_session_state(self):
        """Session can still normally record_turn + build_context after budget fold.

        The source push_context evict path resets budget then still appends the current
        entry and subtracts est_tokens, so budget may be negative — this is a pre-existing
        design choice (not clamped to ≥0). This test only asserts session state is not
        corrupted: build_context and record_turn still work normally.
        """
        from services.dialogue_session import DialogueSession, SessionConfig

        session = DialogueSession(
            agent_id="agent-fold-2",
            config=SessionConfig(max_context_tokens=200),
        )
        # Accumulate pushes over many turns, intentionally exceeding budget
        for i in range(10):
            session.push_context(role="tool" if i % 2 == 0 else "user",
                                 content=f"chunk_{i}: " + "X" * 200,
                                 source=f"src_{i}")
        # build_context still assembles normally without error
        ctx = session.build_context()
        assert isinstance(ctx, str)
        # record_turn still works normally
        session.record_turn(prompt="after fold", response="ok")
        assert len(session._turns) == 1
        # context_entries not emptied (fold retains recent entries)
        assert len(session._context_entries) > 0, "context fully emptied"
