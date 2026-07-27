from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

def _cmd_process(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        procs = reg.processes()
        if args and args[0].isdigit():
            pid = int(args[0])
            procs = [p for p in procs if p.get("pid") == pid]
        return {"success": True, "processes": procs, "count": len(procs)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_vfs(args: list[str]) -> dict:
    try:
        from l1.kernel.vfs import get_vfs
        vfs = get_vfs()
        if args and args[0] == "--mounts":
            return {"success": True, "mounts": vfs.mounts()}
        path = args[0] if args else "/"
        r = vfs.list(path)
        if r.get("success"):
            return {"success": True, "path": path, "entries": r.get("entries", []),
                    "count": len(r.get("entries", []))}
        r2 = vfs.read(path)
        if r2.get("success"):
            return {"success": True, "path": path, "content": r2.get("content", "")[:2000]}
        return {"success": False, "error": r.get("error", f"cannot list {path}")}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_cache(args: list[str]) -> dict:
    try:
        from l3.cache import get_llm_cache_stats, reset_caches
        sub = args[0].lower() if args else "stats"
        if sub == "clear":
            reset_caches()
            return {"success": True, "message": "all caches cleared"}
        stats = get_llm_cache_stats()
        return {"success": True, "stats": stats}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_sysinfo(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        return {"success": True, "summary": reg.summary()}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_clear(args: list[str]) -> dict:
    return {"success": True, "clear": True}

def _cmd_history(args: list[str]) -> dict:
    limit = 20
    if args and args[0].isdigit():
        limit = min(int(args[0]), 200)
    try:
        from l2.shell_session import get_manager
        mgr = get_manager()
        lines = mgr.list()
        return {"success": True, "history": lines[-limit:], "count": len(lines[-limit:])}
    except Exception:
        return {"success": True, "history": [], "count": 0}

def _cmd_lang(args: list[str]) -> dict:
    from l2.i18n import get_locale, set_locale, get_available_locales, t as _t
    if not args:
        current = get_locale()
        available = get_available_locales()
        return {"success": True, "locale": current, "available": available}
    target = args[0]
    available = get_available_locales()
    if target not in available:
        return {"success": False, "error": _t("shell.error.lang_usage", locales=", ".join(available))}
    set_locale(target)
    try:
        from l1.kernel.errors import set_locale as _ke_set
        _ke_set(target)
    except Exception:
        pass
    return {"success": True, "locale": target, "available": available}

def _cmd_audit(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        limit = int(args[0]) if args and args[0].isdigit() else 20
        return {"success": True, "audit": reg.audit(limit=limit), "count": limit}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_settings(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        return {"success": True, "settings": reg.settings()}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_devices(args: list[str]) -> dict:
    try:
        from l1.kernel.registry import get_registry
        reg = get_registry()
        return {"success": True, "devices": reg.devices()}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_tools(args: list[str]) -> dict:
    try:
        from l3.tool_spec import list_tools
        from l2.i18n import get_locale
        category = args[0] if args else None
        locale = get_locale()
        tools = list_tools(category=category, locale=locale)
        return {"success": True, "tools": [{"name": t.name, "description": t.description[:60],
                                              "ring": t.ring, "category": t.category} for t in tools],
                "count": len(tools)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_config(args: list[str]) -> dict:
    sub = args[0].lower() if args else "show"
    if sub == "reload":
        try:
            from l3.config_loader import load as load_config
            cfg = load_config()
            from l1.kernel.commands import load_command_overrides
            load_command_overrides(cfg.get("commands", {}))
            from l1.kernel.prompts import load_prompt_overrides
            load_prompt_overrides(cfg.get("prompts", {}))
            return {"success": True, "message": "configuration reloaded"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    try:
        from l3.config_loader import load as load_config
        cfg = load_config()
        return {"success": True, "config": {k: v for k, v in cfg.items() if k in ("kernel", "cell", "llm", "language")}}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _cmd_tokens(args: list[str]) -> dict:
    from l3.context_pool import all_cell_totals, cell_total, token_usage
    scope, scope_id, rest = _resolve_scope(args)
    sub = rest[0] if rest else "global"
    try:
        if scope == "global" and sub == "global":
            return {"success": True, "tokens": all_cell_totals()}
        if scope == "cell" and scope_id:
            return {"success": True, "cell": cell_total(scope_id)}
        if scope == "agent" and scope_id:
            return {"success": True, "agent": token_usage(scope_id)}
        if sub == "cells":
            return {"success": True, "cells": all_cell_totals().get("cells", [])}
        agents = _resolve_agents(scope, scope_id)
        results = {a: token_usage(a).get(a, 0) for a in agents}
        return {"success": True, "scope": scope, "scope_id": scope_id,
                "results": results, "agents": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _pipeline(segments: list[str]) -> dict:
    from l1.kernel.commands import get_handler as _gh
    import shlex
    parts = [shlex.split(s.strip()) for s in segments]

    def _subst(args: list[str], ctx: dict) -> list[str]:
        out = []
        for a in args:
            if not isinstance(a, str) or "{" not in a:
                out.append(a)
                continue
            import re
            a = re.sub(r"\{\.(\w+)\}", lambda m: str(ctx.get(m.group(1), m.group(0))), a)
            a = a.format(**ctx)
            out.append(a)
        return out

    def _build_ctx(result: dict) -> dict:
        ctx = {"scope": result.get("scope", ""), "scope_id": result.get("scope_id", ""),
               "count": str(result.get("agents", result.get("count", 0)))}
        ctx.update({k: str(v) for k, v in result.items()
                   if isinstance(v, (str, int, float, bool))})
        return ctx

    ctx = {}
    last_result = None
    for seg_idx, seg_parts in enumerate(parts):
        if not seg_parts:
            continue
        cmd = seg_parts[0][1:] if seg_parts[0].startswith("/") else seg_parts[0]
        cmd_args = seg_parts[1:]
        handler = _gh(cmd)
        if not handler:
            return {"success": False, "error": f"pipeline: unknown '{cmd}'", "segment": seg_idx}
        if last_result and isinstance(last_result, dict):
            results_dict = last_result.get("results")
            if isinstance(results_dict, dict) and seg_idx > 0:
                aggregated = {}
                for item_key, item_val in results_dict.items():
                    ictx = dict(ctx, key=str(item_key), value=str(item_val)
                                if not isinstance(item_val, (dict, list)) else str(item_key))
                    nargs = _subst(cmd_args, ictx)
                    r = handler(nargs)
                    aggregated[item_key] = r
                return {"success": True, "pipeline": True,
                        "segments": len(parts), "results": aggregated}
            results_list = last_result.get("results")
            if isinstance(results_list, (list, tuple)) and seg_idx > 0:
                aggregated = {}
                for i, item in enumerate(results_list):
                    item_str = str(item) if not isinstance(item, (dict, list)) else str(i)
                    ictx = dict(ctx, key=item_str, value=item_str, index=str(i))
                    nargs = _subst(cmd_args, ictx)
                    r = handler(nargs)
                    aggregated[str(i) if not isinstance(item, str) else item] = r
                return {"success": True, "pipeline": True,
                        "segments": len(parts), "results": aggregated}
        cmd_args = _subst(cmd_args, ctx)
        result = handler(cmd_args)
        if not result.get("success", True):
            return result
        last_result = result
        ctx.update(_build_ctx(result))
    return last_result or {"success": True, "result": ""}

