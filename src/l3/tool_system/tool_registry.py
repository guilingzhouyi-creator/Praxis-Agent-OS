"""Tool registry — extracted from tool_spec.py for modularity.

Contains tool registry, mute system, plugin registration, and middleware.

Uses the unified Registry protocol from l1.kernel.registry_base.
"""

from __future__ import annotations

import json as _j
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from l1.kernel.paths import get_paths as _gp
from l1.kernel.registry_base import MapRegistry

if TYPE_CHECKING:
    from l3.tool_system.tool_spec import ToolSpec

logger = logging.getLogger(__name__)

# ── Registry instance (unified architecture) ──
# Note: ToolRegistry must be defined before TOOL_REGISTRY is created


class ToolRegistry:
    """Tool registry backed by MapRegistry — unified architecture.

    Provides the standard register/unregister/get/list/stats API
    plus tool-specific mute, plugin, and middleware systems.
    """

    def __init__(self, allow_overwrite: bool = False):
        self._registry = MapRegistry(allow_overwrite=allow_overwrite)
        self._plugins: dict[str, dict] = {}
        self._middleware: list[dict] = []
        self._muted: set[str] = set()
        self._muted_categories: set[str] = set()
        self._muted_plugins: set[str] = set()
        self._muted_rings: set[str] = set()
        self._mute_path_val: str = ""
        self._load_mutes()

    # ── Registry protocol ──

    def register(self, spec: ToolSpec, *, source: str = "code") -> bool:
        """Register a tool spec; returns True on success."""
        return self._registry.register(spec, source=source)

    def unregister(self, name: str) -> bool:
        """Remove a tool by name; returns True if it was registered."""
        return self._registry.unregister(name)

    def get(self, name: str) -> ToolSpec | None:
        """Fetch a tool spec by name, or None if unregistered."""
        return self._registry.get(name)

    def list_tools(self, category: str = "", include_muted: bool = False) -> list[ToolSpec]:
        """List tool specs, optionally filtered by category and excluding muted tools."""
        tools = self._registry.list_items(category=category)
        if not include_muted:
            tools = [t for t in tools if not self.is_muted(t.name)]
        return tools

    def all_names(self) -> list[str]:
        """Return the sorted names of all registered tools."""
        return self._registry.all_names()

    def stats(self) -> dict:
        """Return registry statistics (counts by source/category)."""
        return self._registry.stats()

    def to_json(self) -> str:
        """Serialize the full registry to a JSON string."""
        return _j.dumps(
            {name: spec.to_dict() for name, spec in self._registry._items.items()},
            indent=2,
            default=str,
        )

    # ── Backward-compatible helpers ──

    def register_with_plugin(self, spec: ToolSpec, plugin: str = "") -> None:
        """Register a tool, optionally associating with a plugin name."""
        self._registry.register(spec)
        if plugin:
            self._plugins.setdefault(plugin, {"tools": [], "hooks": []})["tools"].append(spec.name)

    def register_plugin(
        self, name: str, tools: list[ToolSpec], pre_hook: Callable | None = None, post_hook: Callable | None = None
    ) -> None:
        """Register a plugin with its tools and optional pre/post hooks."""
        entry: dict[str, list] = {"tools": [], "hooks": []}
        for spec in tools:
            self.register_with_plugin(spec, plugin=name)
            entry["tools"].append(spec.name)
        if pre_hook:
            entry["hooks"].append({"type": "pre", "name": name, "fn": pre_hook})
        if post_hook:
            entry["hooks"].append({"type": "post", "name": name, "fn": post_hook})
        self._plugins[name] = entry

    def unregister_plugin(self, name: str) -> None:
        """Unregister a plugin and remove all its registered tools."""
        entry = self._plugins.pop(name, None)
        if entry:
            for tname in entry.get("tools", []):
                self._registry.unregister(tname)

    def register_middleware(self, hook_type: str, name: str, fn: Callable[[str, dict, str], dict | None]) -> None:
        """Register a middleware hook of the given type."""
        self._middleware.append({"type": hook_type, "name": name, "fn": fn})

    def list_plugins(self) -> list[str]:
        """Return the names of all registered plugins."""
        return list(self._plugins.keys())

    def list_categories(self) -> list[str]:
        """Return sorted unique tool categories across all registered tools."""
        return sorted(set(t.category for t in self._registry.list_items()))

    # ── Mute system ──

    def _mute_path(self) -> str:
        if not self._mute_path_val:
            self._mute_path_val = os.environ.get("PRAXIS_MUTE_PATH", _gp().mute_state)
        return self._mute_path_val

    def _save_mutes(self) -> None:
        try:
            data = {
                "tools": sorted(self._muted),
                "categories": sorted(self._muted_categories),
                "plugins": sorted(self._muted_plugins),
                "rings": sorted(self._muted_rings),
            }
            tmp = self._mute_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _j.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._mute_path())
        except Exception as e:
            logger.warning("save_mutes failed: %s", e)

    def _load_mutes(self) -> None:
        path = self._mute_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = _j.load(f)
            self._muted.clear()
            self._muted.update(data.get("tools", []))
            self._muted_categories.clear()
            self._muted_categories.update(data.get("categories", []))
            self._muted_plugins.clear()
            self._muted_plugins.update(data.get("plugins", []))
            self._muted_rings.clear()
            self._muted_rings.update(data.get("rings", []))
        except Exception as e:
            logger.warning("load_mutes failed: %s", e)

    def mute_tool(self, name: str) -> None:
        """Mute a tool by name and persist the mute state."""
        self._muted.add(name)
        self._save_mutes()

    def unmute_tool(self, name: str) -> None:
        """Unmute a tool by name and persist the mute state."""
        self._muted.discard(name)
        self._save_mutes()

    def mute_category(self, cat: str) -> None:
        """Mute all tools in a category and persist the mute state."""
        self._muted_categories.add(cat)
        self._save_mutes()

    def unmute_category(self, cat: str) -> None:
        """Unmute a category and persist the mute state."""
        self._muted_categories.discard(cat)
        self._save_mutes()

    def mute_plugin(self, name: str) -> None:
        """Mute all tools of a plugin and persist the mute state."""
        self._muted_plugins.add(name)
        self._save_mutes()

    def unmute_plugin(self, name: str) -> None:
        """Unmute a plugin and persist the mute state."""
        self._muted_plugins.discard(name)
        self._save_mutes()

    def mute_ring(self, ring: str) -> None:
        """Mute all tools in a ring and persist the mute state."""
        self._muted_rings.add(ring)
        self._save_mutes()

    def unmute_ring(self, ring: str) -> None:
        """Unmute a ring and persist the mute state."""
        self._muted_rings.discard(ring)
        self._save_mutes()

    def is_muted(self, tool_name: str, category: str = "", plugin: str = "", ring: str = "") -> bool:
        """Return True if the tool is muted by name, category, plugin, or ring."""
        if tool_name in self._muted:
            return True
        # Resolve category/ring from the registered spec when not passed —
        # mute_category / mute_ring must affect tools registered under them.
        if not (category and plugin and ring):
            spec = self._registry.get(tool_name)
            if spec:
                category = category or getattr(spec, "category", "")
                ring = ring or getattr(spec, "ring", "")
                plugin = plugin or getattr(spec, "plugin", "")
        if category and category in self._muted_categories:
            return True
        if plugin and plugin in self._muted_plugins:
            return True
        return bool(ring and ring in self._muted_rings)

    def list_muted(self) -> dict:
        """Return a dict of all muted tools, categories, plugins, and rings."""
        return {
            "tools": sorted(self._muted),
            "categories": sorted(self._muted_categories),
            "plugins": sorted(self._muted_plugins),
            "rings": sorted(self._muted_rings),
        }

    def clear_mutes(self) -> None:
        """Clear all mute state across tools, categories, plugins, and rings."""
        self._muted.clear()
        self._muted_categories.clear()
        self._muted_plugins.clear()
        self._muted_rings.clear()

    def get_middleware(self) -> list[dict]:
        """Return a copy of the registered middleware list."""
        return list(self._middleware)


# ── Module-level singleton ──

_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get the module-level ToolRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the module-level ToolRegistry singleton to None."""
    global _registry
    _registry = None


# ── Backward-compatible module-level functions ──

TOOL_REGISTRY = get_registry()


def register(spec: ToolSpec, plugin: str = "") -> None:
    """Register a tool spec via the registry singleton, optionally with a plugin."""
    get_registry().register_with_plugin(spec, plugin=plugin)


def register_plugin(
    name: str, tools: list[ToolSpec], pre_hook: Callable | None = None, post_hook: Callable | None = None
) -> None:
    """Register a plugin via the registry singleton."""
    get_registry().register_plugin(name, tools, pre_hook=pre_hook, post_hook=post_hook)


def unregister_plugin(name: str) -> None:
    """Unregister a plugin via the registry singleton."""
    get_registry().unregister_plugin(name)


def register_middleware(hook_type: str, name: str, fn: Callable[[str, dict, str], dict | None]) -> None:
    """Register a middleware hook via the registry singleton."""
    get_registry().register_middleware(hook_type, name, fn)
    # Keep the tool_spec module-level hook list in sync — execute_tool_spec
    # iterates that list at runtime.
    try:
        from l3.tool_system import tool_spec as _ts

        _ts._MIDDLEWARE.append({"type": hook_type, "name": name, "fn": fn})
    except (ImportError, AttributeError):
        logger.debug("tool_registry: middleware registration failed", exc_info=True)


def get_tool(tool_name: str) -> ToolSpec | None:
    """Fetch a tool spec by name from the registry singleton."""
    return get_registry().get(tool_name)


def list_tools(category: str = "", include_muted: bool = False) -> list[ToolSpec]:
    """List tools from the registry singleton, optionally filtered by category."""
    return get_registry().list_tools(category=category, include_muted=include_muted)


def list_categories() -> list[str]:
    """List sorted categories from the registry singleton."""
    return get_registry().list_categories()


def list_plugins() -> list[str]:
    """List registered plugin names from the registry singleton."""
    return get_registry().list_plugins()


def tool_registry_to_json() -> str:
    """Serialize the registry singleton to a JSON string."""
    return get_registry().to_json()


def mute_tool(name: str) -> None:
    """Mute a tool via the registry singleton."""
    get_registry().mute_tool(name)


def unmute_tool(name: str) -> None:
    """Unmute a tool via the registry singleton."""
    get_registry().unmute_tool(name)


def mute_category(cat: str) -> None:
    """Mute a category via the registry singleton."""
    get_registry().mute_category(cat)


def unmute_category(cat: str) -> None:
    """Unmute a category via the registry singleton."""
    get_registry().unmute_category(cat)


def mute_plugin(name: str) -> None:
    """Mute a plugin via the registry singleton."""
    get_registry().mute_plugin(name)


def unmute_plugin(name: str) -> None:
    """Unmute a plugin via the registry singleton."""
    get_registry().unmute_plugin(name)


def mute_ring(ring: str) -> None:
    """Mute a ring via the registry singleton."""
    get_registry().mute_ring(ring)


def unmute_ring(ring: str) -> None:
    """Unmute a ring via the registry singleton."""
    get_registry().unmute_ring(ring)


def is_muted(tool_name: str, category: str = "", plugin: str = "", ring: str = "") -> bool:
    """Return whether a tool is muted via the registry singleton."""
    return get_registry().is_muted(tool_name, category=category, plugin=plugin, ring=ring)


def list_muted() -> dict:
    """Return the muted state dict from the registry singleton."""
    return get_registry().list_muted()


def clear_mutes() -> None:
    """Clear all mute state via the registry singleton."""
    get_registry().clear_mutes()
