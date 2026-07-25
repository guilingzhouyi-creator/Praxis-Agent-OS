"""Context tools - 6 kinds.

context_get, context_set, context_push, context_pop, context_clear, context_summary
"""

import time
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R

# Simulated context stack
_context_stack: dict[str, list[dict]] = {}


def _cmd_context_get(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    namespace = args.get("namespace", "default")
    stack = _context_stack.get(namespace, [])
    if not stack:
        return {"success": True, "data": {"key": key, "found": False, "namespace": namespace}}
    current = stack[-1]
    if key:
        return {"success": True, "data": {"key": key, "value": current.get(key), "found": key in current, "namespace": namespace}}
    return {"success": True, "data": {"context": current, "namespace": namespace, "depth": len(stack)}}


def _cmd_context_set(args: dict, agent_id: str) -> dict:
    key = args.get("key", "")
    value = args.get("value", "")
    namespace = args.get("namespace", "default")
    if not key:
        return {"success": False, "error": "key is required"}
    stack = _context_stack.setdefault(namespace, [])
    if not stack:
        stack.append({})
    stack[-1][key] = value
    return {"success": True, "data": {"key": key, "value": value, "namespace": namespace}}


def _cmd_context_push(args: dict, agent_id: str) -> dict:
    namespace = args.get("namespace", "default")
    initial = args.get("initial", {})
    if isinstance(initial, str):
        import json
        try:
            initial = json.loads(initial)
        except Exception:
            initial = {}
    _context_stack.setdefault(namespace, []).append(dict(initial))
    return {"success": True, "data": {"namespace": namespace, "depth": len(_context_stack[namespace])}}


def _cmd_context_pop(args: dict, agent_id: str) -> dict:
    namespace = args.get("namespace", "default")
    stack = _context_stack.get(namespace, [])
    if not stack:
        return {"success": False, "error": f"context stack '{namespace}' is empty"}
    popped = stack.pop()
    return {"success": True, "data": {"namespace": namespace, "popped": popped, "remaining_depth": len(stack)}}


def _cmd_context_clear(args: dict, agent_id: str) -> dict:
    namespace = args.get("namespace", "")
    if namespace:
        _context_stack.pop(namespace, None)
        return {"success": True, "data": {"namespace": namespace, "cleared": True}}
    _context_stack.clear()
    return {"success": True, "data": {"cleared_all": True, "namespaces_cleared": True}}


def _cmd_context_summary(args: dict, agent_id: str) -> dict:
    summary = {}
    for ns, stack in _context_stack.items():
        summary[ns] = {"depth": len(stack), "keys": list(stack[-1].keys()) if stack else []}
    return {"success": True, "data": {"namespaces": summary, "count": len(summary)}}


def register_tools() -> None:
    register(ToolSpec(name="context_get", description="Read value from current context", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("key", "string", default=""), ParamSpec("namespace", "string", default="default")],
                      handler=_cmd_context_get))
    register(ToolSpec(name="context_set", description="Set value in current context", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("key", "string", required=True), ParamSpec("value", "string", default=""),
                                  ParamSpec("namespace", "string", default="default")],
                      handler=_cmd_context_set))
    register(ToolSpec(name="context_push", description="Push new context layer", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("namespace", "string", default="default"), ParamSpec("initial", "string", default="{}")],
                      handler=_cmd_context_push))
    register(ToolSpec(name="context_pop", description="Pop current context layer", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("namespace", "string", default="default")],
                      handler=_cmd_context_pop))
    register(ToolSpec(name="context_clear", description="Clear context", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("namespace", "string", default="")],
                      handler=_cmd_context_clear))
    register(ToolSpec(name="context_summary", description="Context stack summary", category="generic", ring=R.RING_1, danger=0,
                      handler=_cmd_context_summary))