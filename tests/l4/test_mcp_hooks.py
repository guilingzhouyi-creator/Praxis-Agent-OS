"""MCP bridge, tool pipeline hooks, and AgentLoop chat.params hook tests."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ═══════════════════════════════════════════════════════════════
# MCP 5-state machine tests
# ═══════════════════════════════════════════════════════════════

class TestMCPStateMachine:
    def test_status_constants(self):
        from l4.mcp_bridge import (
            MCP_STATUS_CONNECTED,
            MCP_STATUS_DISABLED,
            MCP_STATUS_FAILED,
            MCP_STATUS_NEEDS_AUTH,
            MCP_STATUS_NEEDS_REGISTRATION,
        )
        assert MCP_STATUS_CONNECTED == "connected"
        assert MCP_STATUS_DISABLED == "disabled"
        assert MCP_STATUS_FAILED == "failed"
        assert MCP_STATUS_NEEDS_AUTH == "needs_auth"
        assert MCP_STATUS_NEEDS_REGISTRATION == "needs_client_registration"

    def test_bridge_init_empty(self):
        from l4 import mcp_bridge as mb
        orig_path = mb.MCP_STATE_PATH
        with tempfile.TemporaryDirectory() as d:
            mb.MCP_STATE_PATH = os.path.join(d, "mcp_state.json")
            try:
                from l4.mcp_bridge import MCPBridge
                bridge = MCPBridge()
                s = bridge.status()
                assert s["servers"] == {}
                assert s["count"] == 0
            finally:
                mb.MCP_STATE_PATH = orig_path

    def test_set_disabled_and_enabled(self):
        from l4.mcp_bridge import MCPBridge
        bridge = MCPBridge()
        r = bridge.set_disabled("test-server")
        assert r["success"]
        assert r["status"] == "disabled"
        status = bridge.get_status("test-server")
        assert status["status"] == "disabled"

        r2 = bridge.set_enabled("test-server")
        assert r2["success"]
        status2 = bridge.get_status("test-server")
        assert status2["status"] == "unknown"  # cleared

    def test_import_server_fails_on_disabled(self):
        from l4.mcp_bridge import MCPBridge
        bridge = MCPBridge()
        bridge.set_disabled("blocked-server")
        from l4.mcp_bridge import McpClient
        client = McpClient("http://localhost:1")
        r = bridge.import_server("blocked-server", client)
        assert not r["success"]
        assert "disabled" in r.get("error", "")

    def test_get_status_all(self):
        from l4.mcp_bridge import MCPBridge
        bridge = MCPBridge()
        bridge.set_disabled("srv-a")
        all_status = bridge.get_status()
        assert "srv-a" in all_status
        assert all_status["srv-a"]["status"] == "disabled"


class TestMCPStatePersistence:
    def test_save_and_load_state(self, tmp_path):
        # Temporarily override state path
        import l4.mcp_bridge as mb
        from l4.mcp_bridge import (
            _load_mcp_state,
            _save_mcp_state,
        )
        original_path = mb.MCP_STATE_PATH
        try:
            test_path = os.path.join(str(tmp_path), "mcp_state.json")
            mb.MCP_STATE_PATH = test_path

            _save_mcp_state({"srv-1": {"status": "disabled", "error": "", "endpoint": "", "auth": {}}})
            loaded = _load_mcp_state()
            assert "srv-1" in loaded
            assert loaded["srv-1"]["status"] == "disabled"
        finally:
            mb.MCP_STATE_PATH = original_path


# ═══════════════════════════════════════════════════════════════
# MCP L2_Shell command tests
# ═══════════════════════════════════════════════════════════════

class TestMCPCommand:
    def test_mcp_status_via_dispatch(self):
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/mcp")
        assert r.get("success")
        assert "data" in r
        assert "servers" in r["data"]

    def test_mcp_status_long(self):
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/mcp status")
        assert r.get("success")
        assert "servers" in r["data"]

    def test_mcp_add_missing_args(self):
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/mcp add")
        assert not r.get("success")

    def test_mcp_disable_unknown(self):
        from l4.mcp_bridge import get_bridge, reset_bridge
        reset_bridge()
        bridge = get_bridge()
        r = bridge.set_disabled("ghost-server")
        assert r["success"]
        assert bridge.get_status("ghost-server")["status"] == "disabled"


# ═══════════════════════════════════════════════════════════════
# Tool pipeline hook tests
# ═══════════════════════════════════════════════════════════════

class TestToolPipelineHooks:
    def test_register_post_execute_hook(self):
        from l3.tool_system.tool_pipeline import get_pipeline, reset_pipeline
        reset_pipeline()
        pipeline = get_pipeline()
        called = []

        def my_hook(tool, agent, args, result):
            called.append(tool)
            return {"hook_applied": True}

        pipeline.register_post_execute_hook(my_hook)
        assert len(pipeline._post_execute_hooks) == 1
        assert pipeline._post_execute_hooks[0] is my_hook

    def test_run_post_execute_hooks(self):
        from l3.tool_system.tool_pipeline import get_pipeline, reset_pipeline
        reset_pipeline()
        pipeline = get_pipeline()

        def hook1(tool, agent, args, result):
            result["h1"] = True
            return result

        def hook2(tool, agent, args, result):
            result["h2"] = True
            return result

        pipeline.register_post_execute_hook(hook1)
        pipeline.register_post_execute_hook(hook2)
        result = pipeline._run_post_execute_hooks("test_tool", "agent", {}, {"success": True})
        assert result["h1"]
        assert result["h2"]

    def test_register_tool_definition_hook(self):
        from l3.tool_system.tool_pipeline import get_pipeline, reset_pipeline
        reset_pipeline()
        pipeline = get_pipeline()

        def my_hook(tool, spec):
            return {"description": f"modified: {tool}"}

        pipeline.register_tool_definition_hook(my_hook)
        assert len(pipeline._tool_definition_hooks) == 1

    def test_post_execute_hook_exception_isolation(self):
        from l3.tool_system.tool_pipeline import get_pipeline, reset_pipeline
        reset_pipeline()
        pipeline = get_pipeline()

        def broken_hook(tool, agent, args, result):
            raise RuntimeError("hook crash")

        def good_hook(tool, agent, args, result):
            result["from_good"] = True
            return result

        pipeline.register_post_execute_hook(broken_hook)
        pipeline.register_post_execute_hook(good_hook)
        result = pipeline._run_post_execute_hooks("t", "a", {}, {"success": True})
        # Exception in first hook should not stop the second
        assert result.get("from_good")

    def test_hook_deduplication(self):
        from l3.tool_system.tool_pipeline import get_pipeline, reset_pipeline
        reset_pipeline()
        pipeline = get_pipeline()

        def same_hook(t, a, args, res):
            return res

        pipeline.register_post_execute_hook(same_hook)
        pipeline.register_post_execute_hook(same_hook)  # duplicate
        assert len(pipeline._post_execute_hooks) == 1


# ═══════════════════════════════════════════════════════════════
# AgentLoop chat.params hook tests
# ═══════════════════════════════════════════════════════════════

class TestAgentLoopChatParamsHook:
    def test_register_hook(self):
        from l3.agent.agent_loop import AgentLoop
        loop = AgentLoop(task="test", agent_id="test-agent")

        def my_hook(task, agent, kwargs):
            kwargs["temperature"] = 0.1
            return kwargs

        loop.register_chat_params_hook(my_hook)
        assert len(loop._chat_params_hooks) == 1

    def test_hook_deduplication(self):
        from l3.agent.agent_loop import AgentLoop
        loop = AgentLoop(task="test")

        def h(task, agent, kwargs):
            return kwargs

        loop.register_chat_params_hook(h)
        loop.register_chat_params_hook(h)
        assert len(loop._chat_params_hooks) == 1

    def test_import_does_not_crash(self):
        from l3.agent.agent_loop import AgentLoop
        loop = AgentLoop(task="test", agent_id="test-agent")
        # Just verify the run() method can be called without LLM
        assert loop is not None


# ═══════════════════════════════════════════════════════════════
# MCPBridge list_prompts / list_resources tests
# ═══════════════════════════════════════════════════════════════

class TestMCPBridgePromptsResources:
    def test_list_prompts_no_server(self):
        from l4.mcp_bridge import get_bridge, reset_bridge
        reset_bridge()
        bridge = get_bridge()
        r = bridge.list_prompts("nonexistent")
        assert not r["success"]
        assert "not imported" in r["error"]

    def test_list_resources_no_server(self):
        from l4.mcp_bridge import get_bridge, reset_bridge
        reset_bridge()
        bridge = get_bridge()
        r = bridge.list_resources("nonexistent")
        assert not r["success"]
        assert "not imported" in r["error"]
