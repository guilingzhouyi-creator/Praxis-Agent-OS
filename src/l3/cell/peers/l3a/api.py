"""L2 Shell API — command routing for `/l3a`."""

from __future__ import annotations

from . import archive as _archive
from . import params as _p
from .context import ContextRegistry
from .model import L3AModelConfig
from .session import SessionManager


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

    if sub == "resume":
        if len(args) < 2:
            return {"success": False, "error": "archived session_id required"}
        from .session import Session
        s = Session.resume_from_archive(
            args[1], model_config=model_cfg, registry=registry)
        if not s:
            return {"success": False,
                    "error": f"archived session not found: {args[1]}"}
        with mgr._lock:
            mgr._sessions[s.id] = s
        return {"success": True, "data": s.info(),
                "resumed_from": args[1]}

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

    if sub == "convergence":
        if len(args) >= 2:
            from .helpers import get_convergence_queue
            items = get_convergence_queue(args[1])
            return {"success": True, "cell_id": args[1], "data": items,
                    "count": len(items)}
        from . import _convergence_loader
        items = _convergence_loader()
        return {"success": True, "scope": "all", "data": items,
                "count": len(items)}

    if sub == "convention":
        if len(args) < 2:
            return {"success": False, "error": "issue_id required"}
        from .helpers import l3a_convention_handler
        return l3a_convention_handler({
            "issue_id": args[1],
            "max_chars": int(args[2]) if len(args) > 2 and args[2].isdigit() else 0,
        })

    if sub == "summaries":
        from .helpers import l3a_summary_handler
        if len(args) >= 3 and args[1].lower() == "get":
            return l3a_summary_handler({"action": "get",
                                        "issue_id": args[2]})
        if len(args) >= 3 and args[1].lower() == "search":
            return l3a_summary_handler({"action": "search",
                                        "query": " ".join(args[2:])})
        domain = args[1] if len(args) >= 2 else ""
        return l3a_summary_handler({"action": "latest", "domain": domain,
                                    "limit": 10})

    if sub == "compress":
        if len(args) < 2:
            return {"success": False, "error": "session_id required"}
        sid = args[1]
        s = mgr.get(sid)
        if not s:
            return {"success": False, "error": f"session not active: {sid}"}
        keep = int(args[2]) if len(args) > 2 and args[2].isdigit() else 10
        return s.compress(keep_last=keep)

    if sub == "memory":
        if len(args) >= 2:
            sid = args[1]
            s = mgr.get(sid)
            if not s:
                return {"success": False, "error": f"session not active: {sid}"}
            window = float(args[2]) if len(args) > 2 else 3600.0
            return s.memory_usage(window=window)
        from l3.memory.central_memory import get_center
        m = get_center().monitor()
        return {"success": True, "data": m}

    if sub == "compress-status":
        from l3.config.settings_center import get_center
        sc = get_center()
        policy = {
            "enabled": bool(sc.get("l3a.auto_compress", True)),
            "threshold": float(sc.get("l3a.auto_compress_threshold", 0.6)),
            "keep_last": int(sc.get("l3a.auto_compress_keep", 10)),
        }
        # live pressure for all active sessions
        live = []
        for s in mgr.list_active():
            sess = mgr.get(s.get("session_id", ""))
            if sess:
                try:
                    cs = sess.context_stats()
                    live.append({"session_id": s["session_id"],
                                 "pressure": cs.get("pressure_ratio", 0),
                                 "level": cs.get("pressure_level", "ok"),
                                 "history": sess.history.count()})
                except Exception:
                    continue
        return {"success": True, "policy": policy, "live": live}

    if sub == "compress-force":
        if len(args) < 2:
            return {"success": False, "error": "session_id required"}
        sid = args[1]
        s = mgr.get(sid)
        if not s:
            return {"success": False, "error": f"session not active: {sid}"}
        return s.auto_compress_check(force=True)

    if sub == "ask":
        if len(args) < 2:
            return {"success": False, "error": "session_id required"}
        sid = args[1]
        s = mgr.get(sid)
        if not s:
            return {"success": False, "error": f"session not active: {sid}"}
        return s.ask_status()

    if sub == "ask-pending":
        from l3.tools._comm import pending_questions
        agent = args[1] if len(args) > 1 else ""
        items = pending_questions(agent)
        return {"success": True, "data": items, "count": len(items)}

    if sub == "answer":
        if len(args) < 2:
            return {"success": False, "error": "session_id required"}
        sid = args[1]
        s = mgr.get(sid)
        if not s:
            return {"success": False, "error": f"session not active: {sid}"}
        answers: dict = {}
        free_form = ""
        for part in args[2:]:
            if "=" in part:
                k, _, v = part.partition("=")
                answers[k.strip()] = v.strip()
            else:
                free_form = (free_form + " " + part).strip()
        r = s.submit_answers(answers, free_form)
        if r.get("success"):
            return s.resume_after_ask()
        return r

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
