"""Tests for mcp_bridge, ops_console, and convergence."""
from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestOpsConsole:
    def test_get_ops_singleton(self):
        from l4.ops_console import get_ops, reset_ops
        reset_ops()
        o1 = get_ops()
        o2 = get_ops()
        assert o1 is o2

    def test_summary_structure(self):
        from l4.ops_console import get_ops, reset_ops
        reset_ops()
        ops = get_ops()
        s = ops.summary()
        assert "cell_count" in s
        assert "cells" in s

    def test_recent_alerts(self):
        from l4.ops_console import get_ops, reset_ops
        reset_ops()
        ops = get_ops()
        alerts = ops.recent_alerts(limit=10)
        assert isinstance(alerts, list)
        assert len(alerts) >= 0

    def test_register_and_deregister_cell(self):
        from l4.ops_console import get_ops, reset_ops
        reset_ops()
        ops = get_ops()
        ops.register_cell("test-cell", {"agent-a": "reader"})
        status = ops.summary()
        assert status["cell_count"] >= 1


class TestMCPBridge:
    def test_get_bridge(self):
        from l4.mcp_bridge import get_bridge
        bridge = get_bridge()
        assert bridge is not None

    def test_bridge_import_export(self):
        from l4.mcp_bridge import MCPBridge
        bridge = MCPBridge()
        r = bridge.export_tools(categories=["generic"])
        assert isinstance(r, (dict, list))

    def test_mcp_tool_dataclass(self):
        from l4.mcp_bridge import McpTool
        tool = McpTool(name="test_tool", description="test", input_schema={})
        assert tool.name == "test_tool"
        assert tool.description == "test"


class TestConvergence:
    def test_rule_converge(self):
        from l3.agent.convergence import _rule_converge_from_text
        r = _rule_converge_from_text("* completed task A\n* fixed bug B")
        assert "Rule-based convergence" in r or "unavailable" in r
