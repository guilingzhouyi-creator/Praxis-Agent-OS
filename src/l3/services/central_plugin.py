"""CentralPlugin — unified plugin lifecycle management.

Coordinates three extension paths under a single API:
  1. Tool plugins  — TOOL_REGISTRY via register_plugin()/unregister_plugin()
  2. Service plugins — BaseService auto-registration in _registry
  3. MCP imports  — MCPBridge.import_server()/remove_server()

Provides: install, enable, disable, remove, list, status.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class PluginInfo:
    """Metadata for a registered plugin."""

    def __init__(self, name: str, kind: str, enabled: bool = True, description: str = "", version: str = "0.1.0"):
        self.name = name
        self.kind = kind  # "tool" | "service" | "mcp"
        self.enabled = enabled
        self.description = description
        self.version = version
        self.installed_at = time.time()
        self.tool_count: int = 0
        self.error: str = ""


class CentralPlugin:
    """Unified plugin lifecycle manager."""

    def __init__(self):
        self._plugins: dict[str, PluginInfo] = {}
        self._lock = threading.RLock()

    # ── Tool plugins ──

    def install_tool_plugin(self, name: str, tools: list[Any], description: str = "", version: str = "0.1.0") -> dict:
        """Register a tool plugin via tool_spec.register_plugin()."""
        from .tool_system.tool_spec import get_tool, register_plugin

        try:
            register_plugin(name, tools)
            count = sum(1 for t in tools if get_tool(t.name) is not None)
            with self._lock:
                pi = PluginInfo(name, "tool", description=description, version=version)
                pi.tool_count = count
                self._plugins[name] = pi
            logger.info("central_plugin: installed tool plugin '%s' (%d tools)", name, count)
            return {"success": True, "name": name, "tools": count}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def remove_tool_plugin(self, name: str) -> dict:
        """Unregister a tool plugin via tool_spec.unregister_plugin()."""
        from .tool_system.tool_spec import list_tools, unregister_plugin

        try:
            before = len(list_tools())
            unregister_plugin(name)
            with self._lock:
                self._plugins.pop(name, None)
            logger.info("central_plugin: removed tool plugin '%s'", name)
            return {"success": True, "name": name, "removed": before - len(list_tools())}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── MCP server plugins ──

    def install_mcp(self, server_name: str, endpoint: str, api_key: str = "", description: str = "") -> dict:
        """Import an MCP server as a plugin."""
        from .mcp_bridge import McpClient, get_bridge

        try:
            client = McpClient(endpoint, api_key)
            r = get_bridge().import_server(server_name, client)
            if r.get("success"):
                with self._lock:
                    pi = PluginInfo(server_name, "mcp", description=description or f"MCP {server_name}")
                    pi.tool_count = r.get("count", 0)
                    self._plugins[server_name] = pi
            return r
        except Exception as e:
            return {"success": False, "error": str(e)}

    def remove_mcp(self, server_name: str) -> dict:
        """Remove an MCP server plugin."""
        from .mcp_bridge import get_bridge

        try:
            r = get_bridge().remove_server(server_name)
            with self._lock:
                self._plugins.pop(server_name, None)
            return r
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Query ──

    def list_plugins(self, kind: str = "") -> list[dict]:
        """List all installed plugins, optionally filtered by kind."""
        with self._lock:
            items = list(self._plugins.values())
        if kind:
            items = [p for p in items if p.kind == kind]
        return [
            {
                "name": p.name,
                "kind": p.kind,
                "enabled": p.enabled,
                "description": p.description,
                "version": p.version,
                "tool_count": p.tool_count,
                "installed_at": getattr(p, "installed_at", 0),
            }
            for p in sorted(items, key=lambda x: x.name)
        ]

    def get_plugin(self, name: str) -> dict | None:
        """Return metadata for a plugin, or None if not installed."""
        with self._lock:
            pi = self._plugins.get(name)
        if not pi:
            return None
        return {
            "name": pi.name,
            "kind": pi.kind,
            "enabled": pi.enabled,
            "description": pi.description,
            "version": pi.version,
            "tool_count": pi.tool_count,
        }

    def stats(self) -> dict:
        """Return plugin counts by kind and the full plugin name list."""
        with self._lock:
            by_kind: dict[str, int] = {}
            for p in self._plugins.values():
                by_kind[p.kind] = by_kind.get(p.kind, 0) + 1
            return {
                "total": len(self._plugins),
                "by_kind": by_kind,
                "plugins": [p.name for p in sorted(self._plugins.values(), key=lambda x: x.name)],
            }


_center: CentralPlugin | None = None


def get_center() -> CentralPlugin:
    """Return the CentralPlugin singleton, creating it if needed."""
    global _center
    if _center is None:
        _center = CentralPlugin()
    return _center


def reset_center() -> None:
    """Reset the CentralPlugin singleton."""
    global _center
    _center = None
