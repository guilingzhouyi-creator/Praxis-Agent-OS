"""L2 Shell: model and settings commands (config, cron, model, settings)."""

from __future__ import annotations

import logging
from typing import Any

from l3.error_bus import capture

logger = logging.getLogger(__name__)

def _cmd_config(args: list[str]) -> dict:
    from l1.kernel.settings import get_settings
    s = get_settings()
    if not args: return {"success": True, "settings": s.all()}
    if args[0] == "set" and len(args) >= 3:
        key, value = args[1], _coerce_str(args[2])
        s.set(key, value); return {"success": True, "key": key, "value": value}
    v = s.get(args[0]); return {"success": True, args[0]: v}

def _cmd_cron(args: list[str]) -> dict:
    from l4.cron_scheduler import get_scheduler
    s = get_scheduler(); sub = args[0].lower() if args else "list"
    if sub == "list": return {"success": True, "cron": s.list()}
    if sub == "add" and len(args) >= 4:
        return {"success": True, "id": args[1], "schedule": args[2], "task": args[3]}
    return {"success": False, "error": "usage: /cron [list|add <id> <schedule> <task>]"}

def _cmd_model(args: list[str]) -> dict:
    if not args: return _model_list()
    sub = args[0].lower()
    if sub == "list": return _model_list()
    if sub == "status": return _model_status()
    if sub == "switch" and len(args) >= 3: return _model_switch(args[1], args[2], args[3] if len(args) > 3 else "")
    if sub == "health": return _model_health(args[1] if len(args) > 1 else "")
    if sub == "set" and len(args) >= 4: return _model_set(args[1], args[2], args[3])
    if sub == "spec":
        return _cmd_model_spec(args[1:])
    return {"success": False, "error": "usage: /model [list|status|switch|health|set|spec]"}


def _cmd_model_spec(args: list[str]) -> dict:
    """Model-spec / strategy panel: view, switch packs, set caps."""
    from l3.services.model_service import get_service as _ms
    from l4.api_handlers.api_handlers_providers import (
        handle_model_spec_overview,
        handle_think_caps_get,
        handle_think_caps_set,
    )
    if not args:
        return handle_model_spec_overview({})
    sub = args[0].lower()
    if sub == "strategy" and len(args) >= 3:
        return _ms().apply_strategy(args[1], args[2])
    if sub == "clear" and len(args) >= 2:
        return _ms().clear_strategy(args[1])
    if sub == "caps":
        if len(args) >= 2:
            caps = {"max_reasoning": args[1]}
            if len(args) >= 3:
                try:
                    caps["max_budget"] = int(args[2])
                except ValueError:
                    return {"success": False, "error": "max_budget must be an int"}
            return handle_think_caps_set(caps)
        return handle_think_caps_get({})
    if sub == "peer":
        return _cmd_model_spec_peer(args[1:])
    return {"success": False,
            "error": "usage: /model spec [strategy <name> <pack>|clear <name>|caps [max_reasoning [max_budget]]|peer <scope> <name> <pack>|peer clear <scope> <name>]"}


def _cmd_model_spec_peer(args: list[str]) -> dict:
    """Peer-agent think strategy: apply/clear strategy packs on think scopes."""
    from l3.scheduler.think_registry import get_think_registry
    from l4.api_handlers.api_handlers_providers import handle_peer_strategy_get
    reg = get_think_registry()
    if not args:
        return handle_peer_strategy_get({})
    sub = args[0].lower()
    if sub == "clear" and len(args) >= 3:
        return reg.clear_strategy(args[1], args[2])
    if sub in ("global", "cell", "agent") and len(args) >= 2:
        if sub == "global":
            return reg.apply_strategy("global", "", args[1])
        if len(args) >= 3:
            return reg.apply_strategy(sub, args[1], args[2])
        return {"success": False,
                "error": f"usage: /model spec peer {sub} <name> <pack>"}
    return {"success": False,
            "error": "usage: /model spec peer [global <pack>|cell <id> <pack>|agent <cell>.<agent> <pack>|clear <scope> <name>]"}

def _cmd_settings(args: list[str]) -> dict:
    from .commands_settings import _cmd_settings as _cs; return _cs(args)

def _coerce_str(v: str) -> Any:
    try:
        return int(v)
    except ValueError:
        logger.debug("model: %r not an int, trying float", v)
    try:
        return float(v)
    except ValueError:
        logger.debug("model: %r not numeric, returning string", v)
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    return v

def _model_list() -> dict:
    from l1.kernel.params.agent import AGENT_ROLE_TYPES
    from l3.services.model_service import get_service as _ms
    ms = _ms(); lines = [f"Providers ({len(AGENT_ROLE_TYPES)} registered):"]
    for role in AGENT_ROLE_TYPES:
        try:
            cfg = ms.resolve(role); lines.append(f"  {role:25s} → provider={cfg.provider:15s} model={cfg.model}")
        except Exception:
            capture("model: resolve failed", error_code="E_CMD", component="l2", context={"role": role})
            lines.append(f"  {role:25s} → (error)")
    return {"success": True, "output": "\n".join(lines)}

def _model_switch(role: str, provider: str, model: str = "") -> dict:
    from l1.kernel.params.agent import AGENT_CLEARANCE
    from l3.config.settings_center import get_center
    if role not in AGENT_CLEARANCE: return {"success": False, "error": f"unknown role: {role}"}
    center = get_center(); prefix = f"model.{role}"; center.set(f"{prefix}.provider", provider)
    if model: center.set(f"{prefix}.model", model)
    try:
        from l1.kernel import get_event_bus; get_event_bus().emit_event("settings.updated", data={"key": prefix, "provider": provider, "model": model})
    except Exception:
        capture("model: event emit failed", error_code="E_CMD", component="l2", context={"role": role})
        logger.warning("_cmd_model: failed to emit settings.updated event")
    return {"success": True, "role": role, "provider": provider, "model": model}

def _model_status() -> dict: return {"success": True, "note": "use /model list"}

def _model_health(provider: str = "") -> dict:
    from l3.services.model_service import get_service as _ms
    ms = _ms()
    try:
        from l4.llm.llm import get_engine; engine = get_engine()
        if hasattr(engine._provider, "health"): return engine._provider.health()
    except Exception:
        capture("model: health check failed", error_code="E_CMD", component="l2")
    return {"success": True, "providers": ms.list_providers()}

def _model_set(role: str, key: str, value: str) -> dict:
    from l3.config.settings_center import get_center
    prefix = f"model.{role}"; center = get_center(); center.set(f"{prefix}.{key}", _coerce_str(value))
    return {"success": True, f"{prefix}.{key}": value}
