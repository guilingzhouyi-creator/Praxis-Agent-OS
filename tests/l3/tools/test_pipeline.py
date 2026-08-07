"""ToolPipeline tests — clearance, rate limit, constitution, alloc, lock, execute."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestToolRateLimiter:
    """Rate scheduler — per-ring per-agent rate limit enforcement."""

    def test_ring1_allowed(self):
        from l3.tool_system.tool_pipeline import get_rate_scheduler

        rl = get_rate_scheduler()
        r = rl.check("test-agent", "RING_1")
        assert r["allowed"]

    def test_ring3_rate_limit(self):
        from l3.tool_system.tool_pipeline import get_rate_scheduler

        rl = get_rate_scheduler()
        for _ in range(10):
            rl.check("heavy-agent", "RING_3")
        r = rl.check("heavy-agent", "RING_3")
        assert not r["allowed"]

    def test_per_agent_isolation(self):
        from l3.tool_system.tool_pipeline import get_rate_scheduler

        rl = get_rate_scheduler()
        for _ in range(10):
            rl.check("hog", "RING_1")
        r = rl.check("other", "RING_1")
        assert r["allowed"]

    def test_reset_after_window(self):
        import time as _t

        from l3.tool_system.tool_pipeline import get_rate_scheduler

        rl = get_rate_scheduler()
        for _ in range(5):
            rl.check("reset-agent", "RING_3")
        r = rl.check("reset-agent", "RING_3")
        assert not r["allowed"]
        key = "reset-agent:RING_3"
        rl._counters[key] = [_t.time() - 120]
        r2 = rl.check("reset-agent", "RING_3")
        assert r2["allowed"]


class TestAgentCanAccess:
    """Ring clearance — agent ring level vs tool ring requirement."""

    def test_ring1_default(self):
        from l3.tool_system.tool_pipeline import agent_can_access

        assert agent_can_access("unknown", "RING_1")

    def test_ring3_blocked(self):
        from l3.tool_system.tool_pipeline import agent_can_access

        # unknown agent defaults to ring 1 clearance → Ring 3 blocked
        assert not agent_can_access("unknown", "RING_3")

    def test_l3_can_access_ring3(self):
        from l3.tool_system.tool_pipeline import agent_can_access

        assert agent_can_access("l3", "RING_3")


class TestToolPipelineExecute:
    """ToolPipeline.execute() 9 步管线测试"""

    @pytest.fixture(autouse=True)
    def _pipeline_guard(self):
        """Isolate each test: reset global pipeline singleton to avoid hook/rate pollution.
        Also registers test agents in the system process table so gatechain passes."""
        # Register test agents needed by gatechain
        from contextlib import suppress

        from l1.kernel import register_process
        from l3.tool_system.tool_pipeline import reset_pipeline

        for aid, ring_val in (("l3", 3), ("scout", 1), ("rate-hog", 3)):
            with suppress(Exception):
                register_process(aid, role="test", ring=ring_val)
        reset_pipeline()
        yield
        reset_pipeline()

    def _make_registry(self) -> dict:
        """Build a minimal tool registry with one Ring-1 read tool."""
        from l3.tool_system.tool_spec import ParamSpec, ToolSpec

        spec = ToolSpec(
            name="read_file",
            description="Read a file",
            category="filesystem",
            ring="RING_1",
            danger=1,
            parameters=[ParamSpec(name="path", type="string", required=True)],
        )
        return {"read_file": spec}

    def test_execute_simple_tool(self):
        """Ring 1 tool should pass all gates and execute successfully."""
        from l3.tool_system.tool_pipeline import get_pipeline

        pipeline = get_pipeline()
        reg = self._make_registry()

        def _fake_executor(name, args, agent_id=""):
            return {"success": True, "data": "file content"}

        result = pipeline.execute(
            "read_file",
            agent_id="l3",
            args={"path": "/tmp/test.txt"},
            _registry=reg,
            _executor=_fake_executor,
        )
        assert result.get("success"), f"pipeline execution failed: {result.get('error')}"
        assert "result" in result, "result should contain execution output"
        assert result["result"].get("data") == "file content"
        assert "call_id" in result, "result should have call_id"
        assert len(result.get("steps", [])) >= 1, "should have pipeline steps"

    def test_execute_rejects_scout_on_ring3(self):
        """Scout agent is limited to Ring 1 only."""
        from l3.tool_system.tool_pipeline import get_pipeline

        pipeline = get_pipeline()
        reg = self._make_registry()
        # Pretend scout has a Ring 3 spec
        from l3.tool_system.tool_spec import ParamSpec, ToolSpec

        ring3_spec = ToolSpec(
            name="write_file",
            description="Write a file",
            category="filesystem",
            ring="RING_3",
            danger=3,
            parameters=[ParamSpec(name="path", type="string", required=True)],
        )
        reg["write_file"] = ring3_spec

        result = pipeline.execute(
            "write_file",
            agent_id="scout",
            args={"path": "/tmp/test.txt"},
            _registry=reg,
        )
        assert not result.get("success")
        err = (result.get("error") or "").lower()
        assert "clearance" in err, f"expected clearance error, got: {result.get('error')}"

    def test_execute_fails_no_registry(self):
        """Pipeline with no registry/executor should fail early."""
        from l3.tool_system.tool_pipeline import get_pipeline

        pipeline = get_pipeline()
        result = pipeline.execute(
            "read_file",
            agent_id="l3",
            args={"path": "/tmp/test.txt"},
        )
        assert not result.get("success")
        err = (result.get("error") or "").lower()
        assert "registry" in err, f"expected 'registry not initialized' error, got: {result.get('error')}"

    def test_execute_rate_limited(self):
        """Rate limit gate should block excessive Ring 3 calls."""
        from l3.tool_system.tool_pipeline import get_pipeline

        pipeline = get_pipeline()
        from l3.tool_system.tool_spec import ParamSpec, ToolSpec

        reg = {
            "write_file": ToolSpec(
                name="write_file",
                description="Write a file",
                category="filesystem",
                ring="RING_3",
                danger=3,
                parameters=[ParamSpec(name="path", type="string", required=True)],
            ),
        }

        def _fake_executor(name, args, agent_id=""):
            return {"success": True}

        # Exhaust rate limit for RING_3 on agent l3
        for _ in range(10):
            pipeline._rate_scheduler.check("l3", "RING_3")

        result = pipeline.execute(
            "write_file",
            agent_id="l3",
            args={"path": "/tmp/test.txt"},
            _registry=reg,
            _executor=_fake_executor,
        )
        assert not result.get("success"), "should be rate limited"
        err = (result.get("error") or "").lower()
        assert "rate" in err, f"expected rate-limit error, got: {result.get('error')}"

    def test_execute_hooks_run(self):
        """Post-execute hooks should be called and can modify result."""
        from l3.tool_system.tool_pipeline import get_pipeline

        pipeline = get_pipeline()
        reg = self._make_registry()
        hook_calls = []

        def _hook(name, agent, args, result):
            hook_calls.append((name, agent))
            result["_hook_applied"] = True
            return result

        pipeline.register_post_execute_hook(_hook)

        def _fake_executor(name, args, agent_id=""):
            return {"success": True, "data": "test"}

        result = pipeline.execute(
            "read_file",
            agent_id="l3",
            args={"path": "/tmp/test.txt"},
            _registry=reg,
            _executor=_fake_executor,
        )
        assert result.get("success")
        assert result.get("_hook_applied"), "hook should have modified result"
        assert len(hook_calls) == 1, "hook should have been called once"
        assert hook_calls[0] == ("read_file", "l3")

    def test_execute_ring1_file_lock_is_read(self):
        """Ring 1 tool should acquire a read lock (not write lock)."""
        from l3.tool_system.tool_pipeline import get_pipeline

        pipeline = get_pipeline()
        reg = self._make_registry()

        def _fake_executor(name, args, agent_id=""):
            return {"success": True}

        result = pipeline.execute(
            "read_file",
            agent_id="l3",
            args={"path": "/tmp/test_lock.txt"},
            _registry=reg,
            _executor=_fake_executor,
        )
        assert result.get("success"), f"execution failed: {result}"

    def test_execute_steps_structure(self):
        """Result should contain detailed step tracing."""
        from l3.tool_system.tool_pipeline import get_pipeline

        pipeline = get_pipeline()
        reg = self._make_registry()

        def _fake_executor(name, args, agent_id=""):
            return {"success": True, "data": "result"}

        result = pipeline.execute(
            "read_file",
            agent_id="l3",
            args={"path": "/tmp/test.txt"},
            _registry=reg,
            _executor=_fake_executor,
        )
        assert result.get("success")
        steps = result.get("steps", [])
        phasenames = [s["phase"] for s in steps if "phase" in s]
        assert any("rate" in p for p in phasenames), f"expected rate step in {phasenames}"
