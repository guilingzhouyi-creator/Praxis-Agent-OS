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

from l1.kernel.params.kernel import RING_1, RING_2_5, RING_3
from l1.kernel.paths import get_paths as _gp
from l1.kernel.registry_base import RegisterableSpec

from .tool_params import ParamSpec, ReturnSpec
from .tool_registry import (
    TOOL_REGISTRY, _PLUGIN_REGISTRY, _MIDDLEWARE,
    register, register_plugin, unregister_plugin, register_middleware,
    get_tool, list_tools, list_categories, list_plugins, tool_registry_to_json,
    is_muted, mute_tool, unmute_tool, mute_category, unmute_category,
    mute_plugin, unmute_plugin, mute_ring, unmute_ring,
    list_muted, clear_mutes,
)

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
    from l1.kernel.params.kernel import RING_1, RING_2_5, RING_3

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

    Also available as ToolSpecBase(RegisterableSpec) for users of the
    unified registry architecture (see registry_base.py).
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
            "parallel_safe": self.parallel_safe,
            "sandbox_profile": self.sandbox_profile,
        }


# ── ToolSpecBase — unified registry architecture compat layer ──


@dataclass
class ToolSpecBase(RegisterableSpec):
    """ToolSpec that also satisfies the RegisterableSpec protocol.

    Use this when registering tools via a MapRegistry[ToolSpecBase]
    from the unified registry architecture.
    """
    ring: str = RING_1
    danger: int = 0
    gates: list[str] = field(default_factory=list)
    parameters: list[ParamSpec] = field(default_factory=list)
    returns: ReturnSpec = field(default_factory=ReturnSpec)
    parallel_safe: bool = False
    sandbox_profile: str | None = None
    handler: Callable | None = None

    def __post_init__(self):
        if not self.gates:
            self.gates = RING_GATE_MAP.get(self.ring, ["G1", "G2"])

    def validate(self, args: dict) -> list[str]:
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

# ═════════════════════════════════════════════════════════════════════════════
# @tool decorator — register a tool at module load time
# ═════════════════════════════════════════════════════════════════════════════

def tool(name: str = "", description: str = "", category: str = "",
         ring: str = RING_1, danger: int = 0,
         params: list | None = None,
         parallel_safe: bool = False,
         metadata: dict | None = None) -> Callable:
    """Decorator: register a ToolSpec when the decorated function is defined.

    Usage::

        @tool(name="file_stat", description="Query file metadata",
              category="files", ring=RING_1, danger=0,
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
    from l3.memory.result_store import get_result_store as _get_rs
    from .tool_config import ToolConfig as _TC
    _rs = _get_rs()
    is_write = tool_name in _TC.write_tool_names()
    if not is_write and spec.ring == RING_1:
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
        from l3.services.counter import get_counter
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
        from l3.bus.reference_channel import get_rc as _rc
        actual_ok = result.get("success", False)
        pred_summary = result.get("data", result.get("output", ""))[:200]
        _rc().tool_call(tool_name, agent_id, allowed=actual_ok,
                        gate="", reason="", args=args,
                        predicted_success=True,
                        predicted_summary=pred_summary)
    except Exception:
        pass

    return result
