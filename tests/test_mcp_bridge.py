"""MCP bridge tests — tool import/export, tool listing."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestMcpBridge:
    def test_bridge_create(self):
        from services.mcp_bridge import MCPBridge
        bridge = MCPBridge()
        assert bridge is not None

    def test_bridge_status(self):
        from services.mcp_bridge import get_bridge
        bridge = get_bridge()
        status = bridge.status()
        assert isinstance(status, dict)
        assert "servers" in status or "imported_servers" in status

    def test_client_create(self):
        from services.mcp_bridge import McpClient
        client = McpClient(endpoint="http://localhost:9999/mcp")
        assert client is not None
        assert client.endpoint == "http://localhost:9999/mcp"

    def test_export_tools_empty(self):
        from services.mcp_bridge import get_bridge
        bridge = get_bridge()
        r = bridge.export_tools(categories=[])
        assert isinstance(r, dict)
