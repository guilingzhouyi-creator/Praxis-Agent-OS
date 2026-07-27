"""Tool registry — extracted from tool_spec.py for modularity.

Contains TOOL_REGISTRY, mute system, plugin registration, and middleware.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Callable

from l1.kernel.params.system import PRAXIS_MUTE_STATE

if TYPE_CHECKING:
    from l3.tool_spec import ToolSpec

logger = logging.getLogger(__name__)

# ── Global Registry ──

TOOL_REGISTRY: dict[str, ToolSpec] = {}
_PLUGIN_REGISTRY: dict[str, dict] = {}
_MIDDLEWARE: list[dict] = []

# ── Mute/disable system ──

_MUTED: set[str] = set()
_MUTED_CATEGORIES: set[str] = set()
_MUTED_PLUGINS: set[str] = set()
_MUTED_RINGS: set[str] = set()
_MUTE_PATH: str = ""


def _mute_path() -> str:
    global _MUTE_PATH
    if not _MUTE_PATH:
        _MUTE_PATH = os.environ.get("PRAXIS_MUTE_PATH", PRAXIS_MUTE_STATE)
    return _MUTE_PATH


def _save_mutes() -> None:
    try:
        import json as _j
        data = {
            "tools": sorted(_MUTED), "categories": sorted(_MUTED_CATEGORIES),
            "plugins": sorted(_MUTED_PLUGINS), "rings": sorted(_MUTED_RINGS),
        }
        tmp = _mute_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _j.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _mute_path())
    except Exception as e:
        logger.warning("save_mutes failed: %s", e)


def _load_mutes() -> None:
    path = _mute_path()
    if not os.path.exists(path):
        return
    try:
        import json as _j
        with open(path, encoding="utf-8") as f:
            data = _j.load(f)
        _MUTED.clear(); _MUTED.update(data.get("tools", []))
        _MUTED_CATEGORIES.clear(); _MUTED_CATEGORIES.update(data.get("categories", []))
        _MUTED_PLUGINS.clear(); _MUTED_PLUGINS.update(data.get("plugins", []))
        _MUTED_RINGS.clear(); _MUTED_RINGS.update(data.get("rings", []))
    except Exception as e:
        logger.warning("load_mutes failed: %s", e)


_load_mutes()


def mute_tool(name: str) -> None:
    _MUTED.add(name); _save_mutes()

def unmute_tool(name: str) -> None:
    _MUTED.discard(name); _save_mutes()

def mute_category(cat: str) -> None:
    _MUTED_CATEGORIES.add(cat); _save_mutes()

def unmute_category(cat: str) -> None:
    _MUTED_CATEGORIES.discard(cat); _save_mutes()

def mute_plugin(name: str) -> None:
    _MUTED_PLUGINS.add(name); _save_mutes()

def unmute_plugin(name: str) -> None:
    _MUTED_PLUGINS.discard(name); _save_mutes()

def mute_ring(ring: str) -> None:
    _MUTED_RINGS.add(ring); _save_mutes()

def unmute_ring(ring: str) -> None:
    _MUTED_RINGS.discard(ring); _save_mutes()


def is_muted(tool_name: str, category: str = "", plugin: str = "", ring: str = "") -> bool:
    """Check if a tool is muted at any of the 4 levels."""
    if tool_name in _MUTED:
        return True
    if category and category in _MUTED_CATEGORIES:
        return True
    if plugin and plugin in _MUTED_PLUGINS:
        return True
    if ring and ring in _MUTED_RINGS:
        return True
    return False


def list_muted() -> dict:
    return {
        "tools": sorted(_MUTED), "categories": sorted(_MUTED_CATEGORIES),
        "plugins": sorted(_MUTED_PLUGINS), "rings": sorted(_MUTED_RINGS),
    }


def clear_mutes() -> None:
    _MUTED.clear()
    _MUTED_CATEGORIES.clear()
    _MUTED_PLUGINS.clear()
    _MUTED_RINGS.clear()


def register(spec: ToolSpec, plugin: str = "") -> None:
    """Register a tool. Optionally associate with a plugin name."""
    TOOL_REGISTRY[spec.name] = spec
    if plugin:
        _PLUGIN_REGISTRY.setdefault(plugin, {"tools": [], "hooks": []})["tools"].append(spec.name)


def register_plugin(name: str, tools: list[ToolSpec],
                    pre_hook: Callable | None = None,
                    post_hook: Callable | None = None) -> None:
    """Register a plugin with multiple tools and optional hooks."""
    entry = {"tools": [], "hooks": []}
    for spec in tools:
        register(spec, plugin=name)
        entry["tools"].append(spec.name)
    if pre_hook:
        entry["hooks"].append({"type": "pre", "name": name, "fn": pre_hook})
    if post_hook:
        entry["hooks"].append({"type": "post", "name": name, "fn": post_hook})
    _PLUGIN_REGISTRY[name] = entry


def unregister_plugin(name: str) -> None:
    """Remove a plugin and all its tools from the registry."""
    entry = _PLUGIN_REGISTRY.pop(name, None)
    if entry:
        for tname in entry.get("tools", []):
            TOOL_REGISTRY.pop(tname, None)


def register_middleware(hook_type: str, name: str,
                        fn: Callable[[str, dict, str], dict | None]) -> None:
    _MIDDLEWARE.append({"type": hook_type, "name": name, "fn": fn})


def get_tool(tool_name: str) -> ToolSpec | None:
    return TOOL_REGISTRY.get(tool_name)


def list_tools(category: str = "", include_muted: bool = False) -> list[ToolSpec]:
    """List registered tools, optionally filtered by category."""
    tools = list(TOOL_REGISTRY.values())
    if category:
        tools = [t for t in tools if t.category == category]
    if not include_muted:
        tools = [t for t in tools if not is_muted(t.name, t.category, t.plugin, t.ring)]
    return tools


def list_categories() -> list[str]:
    return sorted(set(t.category for t in TOOL_REGISTRY.values()))


def list_plugins() -> list[str]:
    return list(_PLUGIN_REGISTRY.keys())


def tool_registry_to_json() -> str:
    import json as _j
    return _j.dumps(
        {name: spec.to_dict() for name, spec in TOOL_REGISTRY.items()},
        indent=2, default=str,
    )
