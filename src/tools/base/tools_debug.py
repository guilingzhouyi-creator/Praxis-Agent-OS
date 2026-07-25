"""Debug tools - 6 kinds.

debug_start, debug_step, debug_continue, debug_breakpoint, debug_var_watch, stack_trace
"""

import sys
import traceback
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R


# Simulated debugger state
_debug_sessions: dict[str, dict] = {}


def _cmd_debug_start(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    session_id = f"debug-{agent_id}-{len(_debug_sessions)}"
    _debug_sessions[session_id] = {
        "agent_id": agent_id,
        "path": path,
        "state": "running",
        "breakpoints": [],
        "variables": {},
        "started": True,
    }
    return {"success": True, "data": {"session_id": session_id, "state": "running", "file": path}}


def _cmd_debug_step(args: dict, agent_id: str) -> dict:
    session_id = args.get("session_id", "")
    if not session_id or session_id not in _debug_sessions:
        return {"success": False, "error": "invalid session_id"}
    session = _debug_sessions[session_id]
    return {"success": True, "data": {"session_id": session_id, "action": "step", "line": 1, "state": "paused"}}


def _cmd_debug_continue(args: dict, agent_id: str) -> dict:
    session_id = args.get("session_id", "")
    if not session_id or session_id not in _debug_sessions:
        return {"success": False, "error": "invalid session_id"}
    _debug_sessions[session_id]["state"] = "running"
    return {"success": True, "data": {"session_id": session_id, "state": "running"}}


def _cmd_debug_breakpoint(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    line = args.get("line", 1)
    action = args.get("action", "set")
    if not path:
        return {"success": False, "error": "path is required"}
    return {"success": True, "data": {"path": path, "line": line, "action": action, "set": True}}


def _cmd_debug_var_watch(args: dict, agent_id: str) -> dict:
    expression = args.get("expression", "")
    if not expression:
        return {"success": False, "error": "expression is required"}
    return {"success": True, "data": {"expression": expression, "value": "<evaluated at runtime>", "type": "unknown"}}


def _cmd_stack_trace(args: dict, agent_id: str) -> dict:
    session_id = args.get("session_id", "")
    frames = []
    try:
        raise RuntimeError("simulated stack trace")
    except RuntimeError:
        for frame in traceback.extract_stack()[-10:-1]:
            frames.append({"file": frame.filename, "line": frame.lineno, "function": frame.name, "code": frame.line})
    return {"success": True, "data": {"session_id": session_id, "frames": frames, "count": len(frames)}}


def register_tools() -> None:
    register(ToolSpec(name="debug_start", description="Start debug session", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True, description="File to debug")],
                      handler=_cmd_debug_start))
    register(ToolSpec(name="debug_step", description="Step over", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("session_id", "string", required=True)],
                      handler=_cmd_debug_step))
    register(ToolSpec(name="debug_continue", description="Continue to next breakpoint", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("session_id", "string", required=True)],
                      handler=_cmd_debug_continue))
    register(ToolSpec(name="debug_breakpoint", description="Set/remove breakpoint", category="generic",
                      ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("line", "int", default=1),
                                  ParamSpec("action", "string", default="set")],
                      handler=_cmd_debug_breakpoint))
    register(ToolSpec(name="debug_var_watch", description="Watch variable value", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("expression", "string", required=True)],
                      handler=_cmd_debug_var_watch))
    register(ToolSpec(name="stack_trace", description="Get current call stack", category="generic",
                      ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("session_id", "string", default="")],
                      handler=_cmd_stack_trace))