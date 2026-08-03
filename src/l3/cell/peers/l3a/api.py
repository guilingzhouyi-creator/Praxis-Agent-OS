"""L2 Shell API — command routing for `/l3a`."""

from __future__ import annotations

from . import params as _p
from .session import SessionManager
from .model import L3AModelConfig
from .context import ContextRegistry
from . import archive as _archive


def dispatch(args: list[str], mgr: SessionManager,
             registry: ContextRegistry,
             model_cfg: L3AModelConfig) -> dict:
    if not args:
        return {"success": True, "data": {
            "active_sessions": [s.info() for s in mgr.list_active()],
            "model": model_cfg.show(),
        }}

    sub = args[0].lower()

    if sub == "create":
        title = " ".join(args[1:]) if len(args) > 1 else ""
        s = mgr.create(title=title, model_config=model_cfg, registry=registry)
        return {"success": True, "data": s.info()}

    if sub == "list":
        active = mgr.list_active()
        arch = _archive.search_sessions(limit=_p.DEFAULT_SEARCH_LIMIT)
        return {"success": True, "data": {
            "active": active,
            "archived": arch.get("data", []),
        }, "count": len(active) + len(arch.get("data", []))}

    if sub == "info":
        sid = args[1] if len(args) > 1 else ""
        if sid:
            s = mgr.get(sid)
            if s:
                return {"success": True, "data": s.info()}
            r = _archive.search_sessions(session_id=sid)
            if r["count"]:
                return {"success": True, "data": r["data"][0]}
            return {"success": False, "error": f"session not found: {sid}"}
        return {"success": False, "error": "session_id required"}

    if sub == "close":
        sid = args[1] if len(args) > 1 else ""
        if sid:
            return mgr.close(sid)
        return {"success": False, "error": "session_id required"}

    if sub == "messages":
        if len(args) < 2:
            return {"success": False, "error": "session_id required"}
        sid = args[1]
        s = mgr.get(sid)
        if not s:
            return {"success": False, "error": f"session not active: {sid}"}
        limit = int(args[2]) if len(args) > 2 and args[2].isdigit() else 20
        page = s.messages(limit=limit)
        return {"success": True, "data": page.items,
                "cursor": page.cursor, "total": page.total, "count": len(page.items)}

    if sub == "model":
        return _model_dispatch(args[1:], model_cfg)

    if sub == "context":
        return _context_dispatch(args[1:], registry)

    if sub == "tasks":
        if len(args) < 2:
            return {"success": False, "error": "session_id required"}
        sid = args[1]
        s = mgr.get(sid)
        if not s:
            return {"success": False, "error": f"session not active: {sid}"}
        status = args[2] if len(args) > 2 else ""
        return {"success": True, "session_id": sid,
                "data": s.tasks.list(status=status),
                "pending": s.tasks.pending_count(),
                "count": len(s.tasks.all())}

    if sub == "todos":
        if len(args) < 2:
            return {"success": False, "error": "session_id required"}
        sid = args[1]
        s = mgr.get(sid)
        if not s:
            return {"success": False, "error": f"session not active: {sid}"}
        if len(args) >= 4 and args[2].lower() == "update":
            r = s.todos_update(args[3], args[4] if len(args) > 4 else "in_progress")
            return r
        return {"success": True, "session_id": sid, "data": s.todos()}

    return {"success": False, "error": f"unknown subcommand: {sub}"}


def _model_dispatch(args: list[str], cfg: L3AModelConfig) -> dict:
    if not args:
        return {"success": True, "data": cfg.show()}
    op = args[0].lower()
    if op == "show":
        return {"success": True, "data": cfg.show()}
    if op == "set" and len(args) >= 3:
        cfg.set(args[1], args[2])
        return {"success": True, "data": cfg.show()}
    return {"success": False, "error": "usage: model show|set <key> <value>"}


def _context_dispatch(args: list[str], registry: ContextRegistry) -> dict:
    if not args:
        return {"success": True, "data": {
            "sources": registry.list_sources(),
        }}
    op = args[0].lower()
    if op == "sources":
        return {"success": True, "data": registry.list_sources()}
    return {"success": False, "error": f"unknown context subcommand: {op}"}
