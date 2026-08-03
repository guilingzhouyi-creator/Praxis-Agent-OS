"""MCP bridge — McpClient, MCPBridge tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestMcpClient:
    def test_create_client(self):
        from l4.mcp_bridge import McpClient
        client = McpClient(endpoint="http://localhost:8080")
        assert client.endpoint == "http://localhost:8080"

    def test_create_client_with_api_key(self):
        from l4.mcp_bridge import McpClient
        client = McpClient(endpoint="http://example.com", api_key="secret")
        assert client.api_key == "secret"


class TestMCPBridge:
    def test_get_bridge_returns_instance(self):
        from l4.mcp_bridge import get_bridge, reset_bridge
        reset_bridge()
        bridge = get_bridge()
        assert bridge is not None

    def test_get_status(self):
        from l4.mcp_bridge import get_bridge, reset_bridge
        reset_bridge()
        bridge = get_bridge()
        st = bridge.get_status()
        assert isinstance(st, dict)

    def test_status(self):
        from l4.mcp_bridge import get_bridge, reset_bridge
        reset_bridge()
        bridge = get_bridge()
        st = bridge.status()
        assert isinstance(st, dict)
