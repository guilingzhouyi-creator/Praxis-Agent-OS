"""MCP server mode — expose Praxis capabilities to external agents via MCP protocol.

Three export modes (config: `api.mcp_mode` in praxis.yaml):
  normal   — base tools only (TOOL_REGISTRY exported via MCPBridge.export_tools)
  selected — L3A session tools only (sessions, subagents, cards)
  full     — base + selected (all)

Endpoints (served by ApiGateway under /api/mcp/):
  GET  /api/mcp/tools/list   → {"tools": [{name, description, inputSchema}]}
  POST /api/mcp/tools/call   → {"name", "arguments"} → result dict
  GET  /api/mcp/ping         → 200

Auth: inherits ApiGateway Bearer token check (PRAXIS_API_TOKEN / api.auth_token).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from l1.kernel.params.api import MCP_EXPORT_MODE

logger = logging.getLogger(__name__)

# ── Export modes ──

MCP_MODE_NORMAL = "normal"
MCP_MODE_SELECTED = "selected"
MCP_MODE_FULL = "full"

_valid_modes = {MCP_MODE_NORMAL, MCP_MODE_SELECTED, MCP_MODE_FULL}

_export_mode: str = MCP_EXPORT_MODE


def set_export_mode(mode: str) -> None:
    global _export_mode
    if mode not in _valid_modes:
        logger.warning("mcp: invalid export mode %r, keeping %s", mode, _export_mode)
        return
    _export_mode = mode
    logger.info("mcp: export mode = %s", mode)


def get_export_mode() -> str:
    return _export_mode


# ── L3A session tools ──

def _l3a_create(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    s = get_daemon().create_session(title=args.get("title", ""))
    return {"success": True, "data": s.info()}


def _l3a_prompt(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    sid = args.get("session_id", "")
    text = args.get("text", "")
    if not sid or not text:
        return {"success": False, "error": "session_id and text required"}
    s = get_daemon().get_session(sid)
    if not s:
        return {"success": False, "error": f"session not found: {sid}"}
    return s.prompt(text, mode=args.get("mode", "steer"))


def _l3a_messages(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    sid = args.get("session_id", "")
    s = get_daemon().get_session(sid)
    if not s:
        return {"success": False, "error": f"session not found: {sid}"}
    page = s.messages(cursor=args.get("cursor") or None,
                      limit=int(args.get("limit", 20)))
    return {"success": True, "data": page.items,
            "cursor": page.cursor, "total": page.total}


def _l3a_info(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    sid = args.get("session_id", "")
    s = get_daemon().get_session(sid)
    if not s:
        return {"success": False, "error": f"session not found: {sid}"}
    return {"success": True, "data": s.info()}


def _l3a_list(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    return {"success": True, "data": get_daemon().manager.list_active()}


def _l3a_close(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    sid = args.get("session_id", "")
    if not sid:
        return {"success": False, "error": "session_id required"}
    return get_daemon().manager.close(sid)


def _l3a_spawn(args: dict) -> dict:
    from l3.cell.peers.l3a import get_l3a_pool
    return get_l3a_pool().commission(
        spec=args.get("spec", "investigator"),
        task=args.get("task", ""),
        group=args.get("group", ""),
        expect=args.get("expect"),
    )


def _l3a_collect(args: dict) -> dict:
    from l3.cell.peers.l3a import get_l3a_pool
    return get_l3a_pool().collect(
        group=args.get("group", ""),
        timeout=float(args.get("timeout", 30)),
    )


def _l3a_peek(args: dict) -> dict:
    from l3.cell.peers.l3a import get_l3a_pool
    return get_l3a_pool().peek(task_id=args.get("task_id", ""))


def _l3a_tasks(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    sid = args.get("session_id", "")
    s = get_daemon().get_session(sid)
    if not s:
        return {"success": False, "error": f"session not found: {sid}"}
    return {"success": True, "session_id": sid,
            "data": s.tasks.list(status=args.get("status", "")),
            "pending": s.tasks.pending_count(),
            "count": len(s.tasks.all())}


def _l3a_todos(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    sid = args.get("session_id", "")
    s = get_daemon().get_session(sid)
    if not s:
        return {"success": False, "error": f"session not found: {sid}"}
    content = args.get("content", "")
    status = args.get("status", "")
    if content:
        return s.todos_update(content, status or "in_progress")
    return {"success": True, "session_id": sid, "data": s.todos()}


def _l3a_resume(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    from l3.cell.peers.l3a.session import Session
    archived_id = args.get("archived_session_id", "")
    if not archived_id:
        return {"success": False, "error": "archived_session_id required"}
    d = get_daemon()
    s = Session.resume_from_archive(archived_id, model_config=d.model_config,
                                    registry=d.registry)
    if not s:
        return {"success": False,
                "error": f"archived session not found: {archived_id}"}
    with d.manager._lock:
        d.manager._sessions[s.id] = s
    return {"success": True, "data": s.info(), "resumed_from": archived_id}


def _l3a_compress(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    sid = args.get("session_id", "")
    s = get_daemon().get_session(sid)
    if not s:
        return {"success": False, "error": f"session not found: {sid}"}
    keep = int(args.get("keep_last", 10))
    return s.compress(keep_last=keep)


def _l3a_memory(args: dict) -> dict:
    from l3.cell.peers.l3a import get_daemon
    sid = args.get("session_id", "")
    if sid:
        s = get_daemon().get_session(sid)
        if not s:
            return {"success": False, "error": f"session not found: {sid}"}
        return s.memory_usage(window=float(args.get("window", 3600)))
    from l3.memory.central_memory import get_center
    return {"success": True, "data": get_center().monitor()}


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties,
            "required": required, "additionalProperties": False}


def _str_prop(desc: str) -> dict:
    return {"type": "string", "description": desc}


_L3A_TOOLS: dict[str, dict[str, Any]] = {
    "l3a_create": {
        "description": "Create a new L3A session. Returns session metadata.",
        "inputSchema": _schema(
            {"title": _str_prop("Optional session title")}, []),
        "handler": _l3a_create,
    },
    "l3a_prompt": {
        "description": "Send a prompt to an L3A session. Runs the AgentLoop — blocking.",
        "inputSchema": _schema(
            {"session_id": _str_prop("Session ID from l3a_create"),
             "text": _str_prop("User prompt text"),
             "mode": _str_prop("steer (default) or queue")},
            ["session_id", "text"]),
        "handler": _l3a_prompt,
    },
    "l3a_messages": {
        "description": "Paginate through session message history.",
        "inputSchema": _schema(
            {"session_id": _str_prop("Session ID"),
             "limit": {"type": "integer", "description": "Page size (default 20)"},
             "cursor": _str_prop("Opaque cursor from previous page")},
            ["session_id"]),
        "handler": _l3a_messages,
    },
    "l3a_info": {
        "description": "Get session details (turns, cards, context, model).",
        "inputSchema": _schema(
            {"session_id": _str_prop("Session ID")}, ["session_id"]),
        "handler": _l3a_info,
    },
    "l3a_list": {
        "description": "List active L3A sessions.",
        "inputSchema": _schema({}, []),
        "handler": _l3a_list,
    },
    "l3a_close": {
        "description": "Close an L3A session (archives to R4).",
        "inputSchema": _schema(
            {"session_id": _str_prop("Session ID")}, ["session_id"]),
        "handler": _l3a_close,
    },
    "l3a_spawn": {
        "description": "Spawn an async L3A subagent. "
                       "spec: card-planner (can create cards) or investigator (read-only).",
        "inputSchema": _schema(
            {"spec": _str_prop("card-planner | investigator (default investigator)"),
             "task": _str_prop("Task description"),
             "group": _str_prop("Group tag for parallel collection"),
             "expect": {"type": "object", "description": "Optional output schema"}},
            ["task"]),
        "handler": _l3a_spawn,
    },
    "l3a_collect": {
        "description": "Blocking collect of all subagent results in a group.",
        "inputSchema": _schema(
            {"group": _str_prop("Group tag from l3a_spawn"),
             "timeout": {"type": "number", "description": "Wait seconds (default 30)"}},
            ["group"]),
        "handler": _l3a_collect,
    },
    "l3a_peek": {
        "description": "Non-blocking peek at a single subagent result.",
        "inputSchema": _schema(
            {"task_id": _str_prop("Task ID from l3a_spawn")}, ["task_id"]),
        "handler": _l3a_peek,
    },
    "l3a_tasks": {
        "description": "Query the session card task table (status tracking buffer).",
        "inputSchema": _schema(
            {"session_id": _str_prop("Session ID"),
             "status": _str_prop("Optional filter: queued|dispatched|running|completed|failed|cancelled")},
            ["session_id"]),
        "handler": _l3a_tasks,
    },
    "l3a_todos": {
        "description": "Query or update the session TODO table (LLM task list). "
                       "With content+status: update an item. Without: list all.",
        "inputSchema": _schema(
            {"session_id": _str_prop("Session ID"),
             "content": _str_prop("TODO item content (omit to list)"),
             "status": _str_prop("pending|in_progress|verifying|verified|escalated|waived")},
            ["session_id"]),
        "handler": _l3a_todos,
    },
    "l3a_resume": {
        "description": "Resume an archived session from R4 into a new live session.",
        "inputSchema": _schema(
            {"archived_session_id": _str_prop("Archived session ID from l3a_list")},
            ["archived_session_id"]),
        "handler": _l3a_resume,
    },
    "l3a_compress": {
        "description": "Manually compress a session's history into a summary, "
                       "keeping the last N messages. Returns before/after tokens.",
        "inputSchema": _schema(
            {"session_id": _str_prop("Session ID"),
             "keep_last": {"type": "integer",
                           "description": "Messages to keep (default 10)"}},
            ["session_id"]),
        "handler": _l3a_compress,
    },
    "l3a_memory": {
        "description": "Report R1-R3 ring usage + ingress rate for a session "
                       "(or all scopes if session_id omitted).",
        "inputSchema": _schema(
            {"session_id": _str_prop("Session ID (omit for all scopes)"),
             "window": {"type": "number",
                        "description": "Ingress window seconds (default 3600)"}},
            []),
        "handler": _l3a_memory,
    },
}


# ── Tool resolution by mode ──

def _base_tools() -> dict[str, dict]:
    try:
        from l4.mcp_bridge import get_bridge
        specs = get_bridge().list_exported_tools()
        if not specs:
            get_bridge().export_tools()
            specs = get_bridge().list_exported_tools()
    except Exception as e:
        logger.warning("mcp: base tools unavailable: %s", e)
        return {}
    tools = {}
    for name, spec in specs.items():
        tools[name] = {
            "description": getattr(spec, "description", "") or name,
            "inputSchema": _schema_from_params(spec),
        }
    return tools


def _schema_from_params(spec: Any) -> dict:
    try:
        params = getattr(spec, "parameters", None)
        if params:
            props = {}
            required = []
            for p in params:
                props[p.name] = {"type": _js_type(p.type),
                                 "description": getattr(p, "description", "")}
                if getattr(p, "required", False):
                    required.append(p.name)
            return _schema(props, required)
    except Exception:
        pass
    return {"type": "object", "properties": {}}


def _js_type(py_type: str) -> str:
    return {"string": "string", "int": "integer", "float": "number",
            "bool": "boolean", "list": "array", "dict": "object"}.get(py_type, "string")


def _selected_tools() -> dict[str, dict]:
    return {
        name: {"description": t["description"], "inputSchema": t["inputSchema"]}
        for name, t in _L3A_TOOLS.items()
    }


def _visible_tools() -> dict[str, dict]:
    mode = _export_mode
    if mode == MCP_MODE_NORMAL:
        return _base_tools()
    if mode == MCP_MODE_SELECTED:
        return _selected_tools()
    merged = dict(_base_tools())
    merged.update(_selected_tools())
    return merged


def _dispatch_tool(name: str, arguments: dict) -> dict:
    if name in _L3A_TOOLS:
        if _export_mode == MCP_MODE_NORMAL:
            return {"success": False, "error": f"tool {name} not exposed in mode {_export_mode}"}
        try:
            return _L3A_TOOLS[name]["handler"](arguments or {})
        except Exception as e:
            return {"success": False, "error": str(e)}
    if _export_mode in (MCP_MODE_NORMAL, MCP_MODE_FULL):
        try:
            from l3.tool_system.tool_spec import execute_tool_spec
            return execute_tool_spec(name, arguments or {}, "")
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": False, "error": f"unknown tool: {name}"}


# ── HTTP handlers (called by ApiGateway route dispatcher) ──

def handle_mcp_tools_list(body: dict | None = None) -> dict:
    tools = _visible_tools()
    return {
        "tools": [
            {"name": name, "description": t["description"],
             "inputSchema": t["inputSchema"]}
            for name, t in sorted(tools.items())
        ],
        "mode": _export_mode,
        "count": len(tools),
    }


def handle_mcp_tools_call(body: dict) -> dict:
    name = (body or {}).get("name", "")
    arguments = (body or {}).get("arguments", {})
    if not name:
        return {"success": False, "error": "name required"}
    result = _dispatch_tool(name, arguments)
    result["_tool"] = name
    return result


def handle_mcp_ping(body: dict | None = None) -> dict:
    return {"status": "ok", "mode": _export_mode}
