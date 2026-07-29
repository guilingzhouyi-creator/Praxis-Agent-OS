"""Model/LLM command handlers — extracted from commands.py for modularity."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _cmd_model(args: list[str]) -> dict:
    """Manage LLM model providers and model specs.

    Usage:
      /model list                          — list registered providers
      /model status                        — show current model specs for all roles
      /model switch <role> <provider> [model] — switch model for a role
      /model health [provider]             — test provider connectivity
      /model set <role> <key> <value>      — set a model spec parameter

    Roles: peer_agent, subagent, scout, r4_agent, convention, card_planner, l3a
    """
    if not args:
        return {"success": False, "error": "usage: /model [list|status|switch|health|set]"}

    sub = args[0]
    try:
        if sub == "list":
            return _model_list()
        elif sub == "status":
            return _model_status()
        elif sub == "switch" and len(args) >= 3:
            return _model_switch(args[1], args[2], args[3] if len(args) > 3 else "")
        elif sub == "health":
            return _model_health(args[1] if len(args) > 1 else "")
        elif sub == "set" and len(args) >= 4:
            return _model_set(args[1], args[2], args[3])
        else:
            return {"success": False, "error": f"unknown /model subcommand: {sub}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _model_list() -> dict:
    try:
        from l1.kernel.model_registry import get_registry
        reg = get_registry()
        providers = reg.list_providers() if hasattr(reg, "list_providers") else []
    except Exception as e:
        return {"success": False, "error": str(e)}

    from l4.vault.credential_vault import export_vault_status
    vault = export_vault_status()

    lines = [f"Providers ({len(providers)} registered):"]
    for p in providers:
        if isinstance(p, str):
            lines.append(f"  {p}")
        else:
            lines.append(f"  {str(p)}")
    lines.append("")
    lines.append(f"Vault: {vault.get('providers', 0)} providers, {vault.get('total_keys', 0)} keys")
    return {"success": True, "output": "\n".join(lines)}


def _model_status() -> dict:
    from l3.services.model_service import get_service
    from l3.config.settings_center import get_center

    sc = get_center()
    all_ = sc.all() if hasattr(sc, "all") else {}
    model_specs = {k: v for k, v in all_.items() if k.startswith("model_spec.")}
    ms = get_service()

    lines = ["Active Model Specs:"]
    for key, value in sorted(model_specs.items()):
        spec_name = key.removeprefix("model_spec.")
        lines.append(f"  {spec_name:45s} = {value}")

    lines.append("")
    lines.append("Resolved Configs:")
    for role in ["peer_agent", "subagent.default", "scout", "r4_agent", "convention", "card_planner", "l3a"]:
        try:
            cfg = ms.resolve(role)
            lines.append(f"  {role:25s} → provider={cfg.provider:15s} model={cfg.model}")
        except Exception:
            lines.append(f"  {role:25s} → (error)")

    return {"success": True, "output": "\n".join(lines)}


def _model_switch(role: str, provider: str, model: str = "") -> dict:
    from l3.services.model_service import get_service
    ms = get_service()
    role_key = role.replace("-", "_")
    if role_key in ("peer_agent", "scout", "r4_agent", "convention", "card_planner", "l3a"):
        key_prefix = f"model_spec.{role_key}"
    elif role_key.startswith("subagent."):
        key_prefix = f"model_spec.subagent.specs.{role_key.removeprefix('subagent.')}"
    else:
        return {"success": False, "error": f"unknown role: {role}"}

    from l3.config.settings_center import get_center
    sc = get_center()
    sc.set(f"{key_prefix}.provider", provider)
    if model:
        sc.set(f"{key_prefix}.model", model)

    try:
        from l1.kernel import get_event_bus
        get_event_bus().emit_event("settings.updated", data={"key": key_prefix, "provider": provider, "model": model})
    except Exception:
        logger.warning("cmd_model: failed to emit settings.updated event")

    return {"success": True, "output": f"Switched {role} to provider={provider} model={model or '(unchanged)'}"}


def _model_health(provider: str = "") -> dict:
    from l3.services.model_service import get_service
    ms = get_service()
    if provider:
        result = ms.health_check(provider)
        return {"success": result.get("status") == "ok", "output": f"Provider {provider}: {result}"}

    from l1.kernel.model_registry import get_registry
    reg = get_registry()
    providers = reg.list_providers() if hasattr(reg, "list_providers") else []
    lines = []
    for name in providers:
        try:
            h = ms.health_check(name)
            status = "✅" if h.get("status") == "ok" else "❌"
            lines.append(f"  {status} {name:20s} {h.get('message', '')}")
        except Exception as e:
            lines.append(f"  ❌ {name:20s} {e}")
    return {"success": True, "output": "\n".join(lines)}


def _model_set(role: str, key: str, value: str) -> dict:
    """Set a model spec parameter for a role."""
    role_key = role.replace("-", "_")
    if role_key in ("peer_agent", "scout", "r4_agent", "convention", "card_planner", "l3a"):
        prefix = f"model_spec.{role_key}"
    elif role_key.startswith("subagent."):
        prefix = f"model_spec.subagent.specs.{role_key.removeprefix('subagent.')}"
    else:
        return {"success": False, "error": f"unknown role: {role}"}

    from l3.config.settings_center import get_center
    sc = get_center()
    sc.set(f"{prefix}.{key}", value)

    try:
        from l1.kernel import get_event_bus
        get_event_bus().emit_event("settings.updated", data={"key": f"{prefix}.{key}", "value": value})
    except Exception:
        logger.warning("cmd_model: failed to emit settings.updated event")

    return {"success": True, "output": f"Set {role}.{key} = {value}"}
