"""API handler mixin — MCP bridge server import / list / remove.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations


def mcp_import(body: dict) -> dict:
    """Import an MCP server into the bridge."""
    try:
        from ..mcp_bridge import McpClient, get_bridge

        server_name = body.get("server_name", "")
        endpoint = body.get("endpoint", "")
        if not server_name or not endpoint:
            return {"error": "server_name and endpoint are required"}
        api_key = body.get("api_key", "")
        client = McpClient(endpoint, api_key)
        return get_bridge().import_server(server_name, client)
    except Exception as e:
        return {"error": str(e)}


def mcp_list(body: dict | None = None) -> dict:
    """List imported MCP servers."""
    try:
        from ..mcp_bridge import get_bridge

        return get_bridge().status()
    except Exception as e:
        return {"status": "error", "error": str(e)}


def mcp_remove(body: dict) -> dict:
    """Remove an imported MCP server."""
    try:
        from ..mcp_bridge import get_bridge

        server_name = body.get("server_name", "")
        if not server_name:
            return {"error": "server_name is required"}
        return get_bridge().remove_server(server_name)
    except Exception as e:
        return {"error": str(e)}
