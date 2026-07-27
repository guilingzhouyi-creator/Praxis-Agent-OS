"""Tool registry — extracted from tool_spec.py for modularity.

Contains tool registry, mute system, plugin registration, and middleware.

Uses the unified Registry protocol from l1.kernel.registry_base.
"""

from __future__ import annotations

import json as _j
import logging
import os
from typing import TYPE_CHECKING, Callable

from l1.kernel.paths import get_paths as _gp
from l1.kernel.registry_base import MapRegistry

if TYPE_CHECKING:
    from typing import TYPE_CHECKING
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
        return self._registry.register(spec, source=source)

    def unregister(self, name: str) -> bool:
        return self._registry.unregister(name)

    def get(self, name: str) -> ToolSpec | None:
        return self._registry.get(name)

    def list(self, category: str = "", include_muted: bool = False) -> list[ToolSpec]:
        tools = self._registry.list(category=category)
        if not include_muted:
            tools = [t for t in tools if not self._is_muted(t.name)]
        return tools

    def all_names(self) -> list[str]:
        return self._registry.all_names()

    def stats(self) -> dict:
        return self._registry.stats()

    def to_json(self) -> str:
        return _j.dumps(
            {name: spec.to_dict() for name, spec in self._registry._items.items()},
            indent=2, default=str,
        )

    # ── Backward-compatible helpers ──

    def register_with_plugin(self, spec: ToolSpec, plugin: str = "") -> None:
        """Register a tool, optionally associating with a plugin name."""
        self._registry.register(spec)
        if plugin:
            self._plugins.setdefault(plugin, {"tools": [], "hooks": []})["tools"].append(spec.name)

    def register_plugin(self, name: str, tools: list[ToolSpec],
                        pre_hook: Callable | None = None,
                        post_hook: Callable | None = None) -> None:
        entry = {"tools": [], "hooks": []}
        for spec in tools:
            self.register_with_plugin(spec, plugin=name)
            entry["tools"].append(spec.name)
        if pre_hook:
            entry["hooks"].append({"type": "pre", "name": name, "fn": pre_hook})
        if post_hook:
            entry["hooks"].append({"type": "post", "name": name, "fn": post_hook})
        self._plugins[name] = entry

    def unregister_plugin(self, name: str) -> None:
        entry = self._plugins.pop(name, None)
        if entry:
            for tname in entry.get("tools", []):
                self._registry.unregister(tname)

    def register_middleware(self, hook_type: str, name: str,
                            fn: Callable[[str, dict, str], dict | None]) -> None:
        self._middleware.append({"type": hook_type, "name": name, "fn": fn})

    def list_plugins(self) -> list[str]:
        return list(self._plugins.keys())

    def list_categories(self) -> list[str]:
        return sorted(set(t.category for t in self._registry.list()))

    # ── Mute system ──

    def _mute_path(self) -> str:
        if not self._mute_path_val:
            self._mute_path_val = os.environ.get("PRAXIS_MUTE_PATH", _gp().mute_state)
        return self._mute_path_val

    def _save_mutes(self) -> None:
        try:
            data = {
                "tools": sorted(self._muted), "categories": sorted(self._muted_categories),
                "plugins": sorted(self._muted_plugins), "rings": sorted(self._muted_rings),
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
            self._muted.clear(); self._muted.update(data.get("tools", []))
            self._muted_categories.clear(); self._muted_categories.update(data.get("categories", []))
            self._muted_plugins.clear(); self._muted_plugins.update(data.get("plugins", []))
            self._muted_rings.clear(); self._muted_rings.update(data.get("rings", []))
        except Exception as e:
            logger.warning("load_mutes failed: %s", e)

    def mute_tool(self, name: str) -> None:
        self._muted.add(name); self._save_mutes()

    def unmute_tool(self, name: str) -> None:
        self._muted.discard(name); self._save_mutes()

    def mute_category(self, cat: str) -> None:
        self._muted_categories.add(cat); self._save_mutes()

    def unmute_category(self, cat: str) -> None:
        self._muted_categories.discard(cat); self._save_mutes()

    def mute_plugin(self, name: str) -> None:
        self._muted_plugins.add(name); self._save_mutes()

    def unmute_plugin(self, name: str) -> None:
        self._muted_plugins.discard(name); self._save_mutes()

    def mute_ring(self, ring: str) -> None:
        self._muted_rings.add(ring); self._save_mutes()

    def unmute_ring(self, ring: str) -> None:
        self._muted_rings.discard(ring); self._save_mutes()

    def is_muted(self, tool_name: str, category: str = "", plugin: str = "", ring: str = "") -> bool:
        if tool_name in self._muted:
            return True
        if category and category in self._muted_categories:
            return True
        if plugin and plugin in self._muted_plugins:
            return True
        if ring and ring in self._muted_rings:
            return True
        return False

    def list_muted(self) -> dict:
        return {
            "tools": sorted(self._muted), "categories": sorted(self._muted_categories),
            "plugins": sorted(self._muted_plugins), "rings": sorted(self._muted_rings),
        }

    def clear_mutes(self) -> None:
        self._muted.clear()
        self._muted_categories.clear()
        self._muted_plugins.clear()
        self._muted_rings.clear()

    def get_middleware(self) -> list[dict]:
        return list(self._middleware)


# ── Module-level singleton ──

_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None


# ── Backward-compatible module-level functions ──

TOOL_REGISTRY = get_registry()

def register(spec: ToolSpec, plugin: str = "") -> None:
    get_registry().register_with_plugin(spec, plugin=plugin)

def register_plugin(name: str, tools: list[ToolSpec],
                    pre_hook: Callable | None = None,
                    post_hook: Callable | None = None) -> None:
    get_registry().register_plugin(name, tools, pre_hook=pre_hook, post_hook=post_hook)

def unregister_plugin(name: str) -> None:
    get_registry().unregister_plugin(name)

def register_middleware(hook_type: str, name: str,
                        fn: Callable[[str, dict, str], dict | None]) -> None:
    get_registry().register_middleware(hook_type, name, fn)

def get_tool(tool_name: str) -> ToolSpec | None:
    return get_registry().get(tool_name)

def list_tools(category: str = "", include_muted: bool = False) -> list[ToolSpec]:
    return get_registry().list(category=category, include_muted=include_muted)

def list_categories() -> list[str]:
    return get_registry().list_categories()

def list_plugins() -> list[str]:
    return get_registry().list_plugins()

def tool_registry_to_json() -> str:
    return get_registry().to_json()

def mute_tool(name: str) -> None:
    get_registry().mute_tool(name)

def unmute_tool(name: str) -> None:
    get_registry().unmute_tool(name)

def mute_category(cat: str) -> None:
    get_registry().mute_category(cat)

def unmute_category(cat: str) -> None:
    get_registry().unmute_category(cat)

def mute_plugin(name: str) -> None:
    get_registry().mute_plugin(name)

def unmute_plugin(name: str) -> None:
    get_registry().unmute_plugin(name)

def mute_ring(ring: str) -> None:
    get_registry().mute_ring(ring)

def unmute_ring(ring: str) -> None:
    get_registry().unmute_ring(ring)

def is_muted(tool_name: str, category: str = "", plugin: str = "", ring: str = "") -> bool:
    return get_registry().is_muted(tool_name, category=category, plugin=plugin, ring=ring)

def list_muted() -> dict:
    return get_registry().list_muted()

def clear_mutes() -> None:
    get_registry().clear_mutes()
