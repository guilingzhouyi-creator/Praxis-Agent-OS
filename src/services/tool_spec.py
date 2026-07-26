"""ToolSpec — generic and extensible tool specification system.

Features:
  - Plugin registration: third-party tools can register via `register_plugin()`
  - Auto-discovery: tools_*.py files are auto-discovered and registered
  - Middleware: pre/post hooks for all tool executions
  - Category-based discovery: tools grouped by category
  - JSON serialization: full registry export for UI
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from kernel.params.system import PRAXIS_MUTE_STATE

logger = logging.getLogger(__name__)


# ── Tool handler Protocol ──

@runtime_checkable
class ToolHandler(Protocol):
    """Protocol for tool handler functions.

    Every tool handler must accept (args: dict, agent_id: str) -> dict.
    Use this as the type annotation for ToolSpec.handler.
    """
    def __call__(self, args: dict, agent_id: str) -> dict: ...


class ToolRing:
    """Canonical tool ring constants — single source in kernel.params."""
    # Re-export from kernel.params so callers importing from tool_spec still
    # work, but there is ONE source of truth (kernel.params.RING_*).
    from kernel.params.kernel import RING_1, RING_2_5, RING_3

RING_GATE_MAP: dict[str, list[str]] = {
    ToolRing.RING_1: ["G1", "G2"],
    ToolRing.RING_2_5: ["G1", "G2", "G3", "G4"],
    ToolRing.RING_3: ["G1", "G2", "G3", "G4", "G5"],
}


@dataclass
class ParamSpec:
    """Tool parameter specification."""
    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""

    def validate(self, value: Any) -> str | None:
        if value is None and not self.required:
            return None
        type_map = {"string": str, "int": int, "bool": bool, "list": list, "dict": dict}
        expected = type_map.get(self.type)
        if expected and value is not None and not isinstance(value, expected):
            return f"{self.name}: expected {self.type}, got {type(value).__name__}"
        return None


@dataclass
class ReturnSpec:
    """Tool return value specification."""
    type: str = "object"
    description: str = ""
    properties: dict[str, str] = field(default_factory=lambda: {
        "success": "bool", "data": "any", "error": "string?",
    })


@dataclass
class ToolSpec:
    """Generic tool specification — framework-agnostic, project-agnostic.

    A ToolSpec defines a tool's complete interface:
    - name, description, category for discovery
    - ring, danger, gates for security
    - parameters, returns for validation
    - handler for execution
    - metadata for extensibility (any key-value pairs)
    """
    name: str
    description: str
    category: str
    ring: str
    danger: int
    gates: list[str] = field(default_factory=list)
    parameters: list[ParamSpec] = field(default_factory=list)
    returns: ReturnSpec = field(default_factory=ReturnSpec)
    handler: Callable | None = None
    parallel_safe: bool = False
    sandbox_profile: str | None = None  # "DANGER_0".."DANGER_4", None = no sandbox
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.gates:
            self.gates = RING_GATE_MAP.get(self.ring, ["G1", "G2"])

    def validate(self, args: dict) -> list[str]:
        """Validate parameters against spec. Returns list of errors."""
        errors = []
        for p in self.parameters:
            val = args.get(p.name)
            if p.required and val is None:
                errors.append(f"missing required parameter: {p.name}")
            else:
                err = p.validate(val)
                if err:
                    errors.append(err)
        return errors

    def to_api_format(self) -> dict:
        """Convert to OpenAI-style function-calling API format."""
        properties = {}
        required = []
        for p in self.parameters:
            properties[p.name] = {"type": p.type, "description": p.description}
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "name": self.name, "description": self.description,
            "category": self.category, "ring": self.ring,
            "danger": self.danger, "gates": self.gates,
            "parameters": [
                {"name": p.name, "type": p.type, "required": p.required,
                 "default": p.default, "description": p.description}
                for p in self.parameters
            ],
            "returns": self.returns.__dict__,
            "parallel_safe": self.parallel_safe,
            "sandbox_profile": self.sandbox_profile,
            "metadata": self.metadata,
        }


# ═════════════════════════════════════════════════════════════════════════════
# @tool decorator — register a tool at module load time
# ═════════════════════════════════════════════════════════════════════════════

def tool(name: str = "", description: str = "", category: str = "",
         ring: str = "RING_1", danger: int = 0,
         params: list | None = None,
         parallel_safe: bool = False,
         metadata: dict | None = None) -> Callable:
    """Decorator: register a ToolSpec when the decorated function is defined.

    Usage::

        @tool(name="file_stat", description="Query file metadata",
              category="files", ring="RING_1", danger=0,
              params=[ParamSpec("path", "string", required=True)])
        def _cmd_file_stat(args: dict, agent_id: str) -> dict:
            ...

    The tool is registered immediately upon module import.
    The original handler function is returned (not wrapped).
    """
    def decorator(handler: Callable) -> Callable:
        spec = ToolSpec(
            name=name or handler.__name__,
            description=description,
            category=category,
            ring=ring,
            danger=danger,
            parameters=params or [],
            handler=handler,
            parallel_safe=parallel_safe,
            metadata=metadata or {},
        )
        register(spec)
        return handler
    return decorator


# ═════════════════════════════════════════════════════════════════════════════
# Global Registry
# ═════════════════════════════════════════════════════════════════════════════

TOOL_REGISTRY: dict[str, ToolSpec] = {}
_PLUGIN_REGISTRY: dict[str, dict] = {}  # plugin_name → {tools: [...], hooks: [...]}
_MIDDLEWARE: list[dict] = []  # pre/post hooks

# ── Mute/disable system ──
#
# Four independent mute levels — applies if ANY level matches:
#   1. Tool name  (granular, one tool)
#   2. Category   (group, e.g. "network", "os")
#   3. Plugin     (vendor, e.g. "docker")
#   4. Ring       (clearance, e.g. "ring_3")
#
# Use cases:
#   mute_tool("run_in_terminal")        → block a single dangerous tool
#   mute_category("network")            → disable all network tools
#   mute_plugin("docker")               → disable a plugin entirely
#   mute_ring(ToolRing.RING_3)          → block all destructive tools
#   mute_category("network", plugin="docker") → disable docker's network tools only
#
# Mute state is NOT persisted here — callers should save/restore via settings.

_MUTED: set[str] = set()                  # muted tool names
_MUTED_CATEGORIES: set[str] = set()       # muted category names
_MUTED_PLUGINS: set[str] = set()          # muted plugin names
_MUTED_RINGS: set[str] = set()            # muted ring levels
_MUTE_PATH: str = ""

# ── Mute state persistence ──

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

def mute_plugin(plugin: str) -> None:
    _MUTED_PLUGINS.add(plugin); _save_mutes()

def unmute_plugin(plugin: str) -> None:
    _MUTED_PLUGINS.discard(plugin); _save_mutes()

def mute_ring(ring: str) -> None:
    _MUTED_RINGS.add(ring); _save_mutes()

def unmute_ring(ring: str) -> None:
    _MUTED_RINGS.discard(ring); _save_mutes()


def is_muted(tool_name: str) -> bool:
    """Check if a tool is muted at any level."""
    if tool_name in _MUTED:
        return True
    spec = TOOL_REGISTRY.get(tool_name)
    if not spec:
        return False
    if spec.category in _MUTED_CATEGORIES:
        return True
    if spec.ring in _MUTED_RINGS:
        return True
    for pname, pinfo in _PLUGIN_REGISTRY.items():
        if pname in _MUTED_PLUGINS and tool_name in pinfo.get("tools", []):
            return True
    return False


def list_muted() -> dict:
    """Return all active mute rules."""
    return {
        "tools": sorted(_MUTED),
        "categories": sorted(_MUTED_CATEGORIES),
        "plugins": sorted(_MUTED_PLUGINS),
        "rings": sorted(_MUTED_RINGS),
        "effective": sorted(t for t in TOOL_REGISTRY if is_muted(t)),
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
    """Register middleware: 'pre' (before execution) or 'post' (after execution).
    
    Pre-hook: receives (tool_name, args, agent_id) → returns modified args or None to block
    Post-hook: receives (tool_name, result, agent_id) → returns modified result
    """
    _MIDDLEWARE.append({"type": hook_type, "name": name, "fn": fn})


def get_tool(tool_name: str) -> ToolSpec | None:
    return TOOL_REGISTRY.get(tool_name)


def list_tools(category: str | None = None, plugin: str | None = None,
               include_muted: bool = False,
               locale: str = "") -> list[ToolSpec]:
    """List tools, optionally filtered by category or plugin.

    Args:
        category: filter by category name
        plugin: filter by plugin name
        include_muted: if True, muted tools are also returned
        locale: if set, tool descriptions are localized via services.i18n
    """
    tools = list(TOOL_REGISTRY.values())
    if category:
        tools = [t for t in tools if t.category == category]
    if plugin:
        plugin_tools = _PLUGIN_REGISTRY.get(plugin, {}).get("tools", [])
        tools = [t for t in tools if t.name in plugin_tools]
    if not include_muted:
        tools = [t for t in tools if not is_muted(t.name)]
    if locale:
        _localize_descriptions(tools, locale)
    return tools


def _localize_descriptions(tools: list[ToolSpec], locale: str) -> None:
    """Localize tool descriptions in-place using services.i18n.

    Translates both ToolSpec.description (via tool.{name}) and
    each ParamSpec.description (via param.{name}).
    Falls back to the original text when no translation is found.
    """
    try:
        from services.i18n import t as _t
        for tool in tools:
            key = f"tool.{tool.name}"
            localized = _t(key)
            if localized != key:
                tool.description = localized
            # Also localize each parameter description
            for p in tool.parameters:
                if p.description:
                    pkey = f"param.{p.name}"
                    plocalized = _t(pkey)
                    if plocalized != pkey:
                        p.description = plocalized
    except Exception:
        pass


def list_categories() -> list[str]:
    """List all tool categories."""
    return sorted(set(t.category for t in TOOL_REGISTRY.values()))


def list_plugins() -> dict[str, list[str]]:
    """List all registered plugins and their tools."""
    return {name: info["tools"] for name, info in _PLUGIN_REGISTRY.items()}


def tool_registry_to_json() -> str:
    """Export entire registry as JSON."""
    return json.dumps(
        {n: s.to_dict() for n, s in TOOL_REGISTRY.items()},
        indent=2, ensure_ascii=False,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Auto-discovery (deprecated — use ToolConfig.load() instead)
# ═════════════════════════════════════════════════════════════════════════════

def auto_discover(package_path: str = "") -> int:
    """Deprecated: use ToolConfig.load(). Kept for backward compat."""
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# Execution with middleware
# ═════════════════════════════════════════════════════════════════════════════

def execute_tool_spec(tool_name: str, args: dict, agent_id: str = "") -> dict:
    """Execute a tool through the registry, with mute and middleware support."""
    spec = get_tool(tool_name)
    if not spec:
        return {"success": False, "error": f"unknown tool: {tool_name}"}

    # Mute check (fast path before validation)
    if is_muted(tool_name):
        return {"success": False, "error": f"tool muted: {tool_name}", "muted": True}

    # Validate parameters
    errors = spec.validate(args)
    if errors:
        return {"success": False, "error": "; ".join(errors)}

    # ── ResultStore: try cache hit for read-only tools ──
    from .result_store import get_result_store as _get_rs
    from .tool_config import ToolConfig as _TC
    _rs = _get_rs()
    is_write = tool_name in _TC.write_tool_names()
    if not is_write and spec.ring == "RING_1":
        _fp = _rs.fingerprint(tool_name, args)
        _cached = _rs.get(_fp)
        if _cached is not None:
            logger.debug("result_store HIT: %s %s", tool_name, str(args)[:60])
            return dict(_cached)  # return a copy
    else:
        _fp = ""
        # Invalidate matching cache entries for write tools
        if is_write:
            _rs.invalidate_for_tool(tool_name, args)

    # Pre-hooks
    current_args = dict(args)
    for hook in _MIDDLEWARE:
        if hook["type"] == "pre":
            try:
                result = hook["fn"](tool_name, current_args, agent_id)
                if result is None:
                    return {"success": False, "error": f"blocked by middleware: {hook['name']}"}
                if isinstance(result, dict):
                    current_args.update(result)
            except Exception as e:
                logger.warning("middleware pre-hook failed: %s", e)

    # Execute
    if spec.handler is None:
        return {"success": False, "error": f"{tool_name}: no handler registered"}
    try:
        result = spec.handler(current_args, agent_id)
        if not isinstance(result, dict):
            return {"success": False, "error": f"{tool_name}: handler returned non-dict"}
    except Exception as e:
        return {"success": False, "error": f"{tool_name}: {e}"}

    # ── ResultStore: store result for cache hit on future calls ──
    if not is_write and _fp and result.get("success", False):
        _rs.set(_fp, result, tool_name=tool_name, path=current_args.get("path", ""))

    # Record tool call
    try:
        from .counter import get_counter
        get_counter().record_tool(agent_id=agent_id or "unknown",
                                  tool=tool_name,
                                  success=result.get("success", False))
    except Exception as e:
        logger.warning("tool counter failed: %s", e)

    # Post-hooks
    for hook in _MIDDLEWARE:
        if hook["type"] == "post":
            try:
                modified = hook["fn"](tool_name, result, agent_id)
                if isinstance(modified, dict):
                    result = modified
            except Exception as e:
                logger.warning("middleware post-hook failed: %s", e)

    # ── Reference Channel: {prediction, actual, deviation} triplet ──
    try:
        from .reference_channel import get_rc as _rc
        actual_ok = result.get("success", False)
        pred_summary = result.get("data", result.get("output", ""))[:200]
        _rc().tool_call(tool_name, agent_id, allowed=actual_ok,
                        gate="", reason="", args=args,
                        predicted_success=True,
                        predicted_summary=pred_summary)
    except Exception:
        pass

    return result
