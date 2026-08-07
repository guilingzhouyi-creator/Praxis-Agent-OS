"""Provider + ModelSpec management API handlers.

Endpoints:
  GET    /api/v2/providers                    — list all registered providers
  POST   /api/v2/providers                    — register a new provider
  DELETE /api/v2/providers/{name}             — unregister a provider
  GET    /api/v2/providers/{name}/health      — test provider connectivity
  PUT    /api/v2/providers/{name}/config      — update provider configuration

  GET    /api/v2/model-spec                   — list all model specs
  PUT    /api/v2/model-spec/{name}            — update a model spec at runtime

  GET    /api/v2/subagent/defaults            — subagent platform defaults
  PUT    /api/v2/subagent/defaults            — update subagent defaults
  GET    /api/v2/subagent/specs/{name}        — per-subagent model config
  PUT    /api/v2/subagent/specs/{name}        — update per-subagent config

  GET    /api/v2/scout/config                 — scout model config
  PUT    /api/v2/scout/config                 — update scout config

  GET    /api/v2/r4/config                    — R4Agent model config
  PUT    /api/v2/r4/config                    — update R4Agent config

  GET    /api/v2/convention/config            — Convention model config
  PUT    /api/v2/convention/config            — update Convention config
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Provider management ─────────────────────────────────────


def handle_providers_list(body: dict | None = None) -> dict:
    """GET /api/v2/providers — list all registered LLM providers."""
    from l1.kernel.model_registry import get_registry

    reg = get_registry()
    try:
        models = reg.list_models() if hasattr(reg, "list_models") else []
    except Exception:
        models = []
    from l4.vault.credential_vault import export_vault_status

    vault = export_vault_status()
    return {
        "success": True,
        "providers": models,
        "vault": vault,
    }


def handle_providers_register(body: dict | None = None) -> dict:
    """POST /api/v2/providers — register a new LLM provider.

    Body:
      name: str              — provider name (e.g. "my-provider")
      api_url: str           — API endpoint
      api_key: str           — API key (optional, stored in vault)
      model: str             — default model name
      extra: dict            — any additional kwargs for the provider class
    """
    b = body or {}
    name = b.get("name", "")
    if not name:
        return {"success": False, "error": "name required"}

    from l4.vault.credential_vault import set_credential

    if b.get("api_key"):
        set_credential(name, "api_key", b["api_key"])
    if b.get("api_url"):
        set_credential(name, "api_url", b["api_url"])
    if b.get("model"):
        set_credential(name, "model", b["model"])

    return {"success": True, "provider": name}


def handle_providers_remove(name: str = "") -> dict:
    """DELETE /api/v2/providers/{name} — unregister a provider."""
    if not name:
        return {"success": False, "error": "name required"}
    from l4.vault.credential_vault import delete_credential

    delete_credential(name)
    return {"success": True, "provider": name}


def handle_providers_health(name: str = "") -> dict:
    """GET /api/v2/providers/{name}/health — test provider connectivity."""
    if not name:
        return {"success": False, "error": "name required"}
    from l3.services.model_service import get_service

    return get_service().health_check(name)


def handle_providers_config(name: str = "", body: dict | None = None) -> dict:
    """PUT /api/v2/providers/{name}/config — update provider configuration."""
    if not name:
        return {"success": False, "error": "name required"}
    b = body or {}
    from l4.vault.credential_vault import set_credential

    for key in ("api_key", "api_url", "model"):
        if key in b:
            set_credential(name, key, str(b[key]))
    return {"success": True, "provider": name, "updated": list(b.keys())}


# ── Model spec viewer / updater ─────────────────────────────


def handle_model_spec_list(body: dict | None = None) -> dict:
    """GET /api/v2/model-spec — list all model specs."""
    from l3.config.settings_center import get_center

    sc = get_center()
    all_ = sc.all() if hasattr(sc, "all") else {}
    specs = {k: v for k, v in all_.items() if k.startswith("model_spec.")}
    return {"success": True, "model_spec": specs}


def handle_model_spec_update(name: str = "", body: dict | None = None) -> dict:
    """PUT /api/v2/model-spec/{name} — update a model spec at runtime.

    Path: dot-separated key, e.g. "scout", "subagent.defaults"
    Body: dict of {key: value} pairs to set
    """
    if not name:
        return {"success": False, "error": "name required"}
    b = body or {}
    from l3.config.settings_center import get_center

    sc = get_center()
    prefix = f"model_spec.{name}"
    for key, value in b.items():
        sc.set(f"{prefix}.{key}", value)
    return {"success": True, "model_spec": name, "updated": list(b.keys())}


def handle_model_strategy_apply(name: str = "", body: dict | None = None) -> dict:
    """PUT /api/v2/model-spec/{name}/strategy — apply a named strategy pack."""
    if not name:
        return {"success": False, "error": "name required"}
    strategy = (body or {}).get("strategy", "")
    if not strategy:
        return {"success": False, "error": "strategy required"}
    from l3.services.model_service import get_service

    return get_service().apply_strategy(name, strategy)


def handle_model_strategy_clear(name: str = "", body: dict | None = None) -> dict:
    """DELETE /api/v2/model-spec/{name}/strategy — restore executor defaults."""
    if not name:
        return {"success": False, "error": "name required"}
    from l3.services.model_service import get_service

    return get_service().clear_strategy(name)


def handle_model_strategy_get(name: str = "", body: dict | None = None) -> dict:
    """GET /api/v2/model-spec/{name}/strategy — current active strategy."""
    if not name:
        return {"success": False, "error": "name required"}
    from l3.services.model_service import get_service

    return get_service().current_strategy(name)


def handle_model_strategy_apply_many(body: dict | None = None) -> dict:
    """PUT /api/v2/model-spec/strategy/apply — apply a strategy to many executors.

    Body: {"strategy": "deep", "specs": ["l3a", "scout"]} or specs: ["all"].
    """
    b = body or {}
    strategy = b.get("strategy", "")
    specs = b.get("specs") or []
    if not strategy:
        return {"success": False, "error": "strategy required"}
    if not specs:
        return {"success": False, "error": "specs required"}
    from l3.services.model_service import get_service

    ms = get_service()
    if "all" in specs:
        specs = ["scout", "l3a", "l3a_subagent", "subagent", "r4_agent"]
    results: list[dict] = []
    for name in specs:
        r = ms.apply_strategy(name, strategy)
        if not r.get("success"):
            return {"success": False, "error": f"{name}: {r.get('error')}", "applied": results}
        results.append({"spec": name, "applied": r["applied"]})
    return {"success": True, "strategy": strategy, "specs": results}


_SPEC_NAMES = ("scout", "l3a", "l3a_subagent", "subagent", "r4_agent")


def handle_model_spec_overview(body: dict | None = None) -> dict:
    """GET /api/v2/model-spec/overview — full panel state for frontend rendering.

    Returns per-executor resolved values + active strategy, global caps,
    available strategy packs and the reasoning tier set.
    """
    from l3.config.settings_center import get_center
    from l3.services.model_service import get_service

    sc = get_center()
    ms = get_service()
    specs = {}
    for name in _SPEC_NAMES:
        cur = ms.current_strategy(name)
        specs[name] = {
            "current": ms.resolve_dict(name),
            "strategy": cur["strategy"],
            "overrides": cur["overrides"],
        }
    strategies: dict[str, dict[str, Any]] = {}
    for key, value in sc.all().items():
        if key.startswith("model_spec.strategies."):
            parts = key.split(".")
            # model_spec.strategies.{name}.{attr}
            if len(parts) >= 4:
                strategies.setdefault(parts[2], {})[parts[3]] = value
    try:
        from l1.kernel.params.api import EFFORT_RANK

        tiers = list(EFFORT_RANK.keys())
    except Exception:
        tiers = ["none", "low", "medium", "high", "xhigh", "max"]
    try:
        from l3.scheduler.think_registry import get_think_registry

        peers = get_think_registry().stats()
    except Exception:
        peers = {}
    return {
        "success": True,
        "specs": specs,
        "caps": {
            "max_reasoning": sc.get("think.max_reasoning", "max"),
            "max_budget": sc.get("think.max_budget", 32768),
        },
        "strategies": strategies,
        "tiers": tiers,
        "peers": peers,
    }


def handle_think_caps_get(body: dict | None = None) -> dict:
    """GET /api/v2/model-spec/caps — current reasoning caps."""
    from l3.config.settings_center import get_center

    sc = get_center()
    return {
        "success": True,
        "caps": {
            "max_reasoning": sc.get("think.max_reasoning", "max"),
            "max_budget": sc.get("think.max_budget", 32768),
        },
    }


def handle_think_caps_set(body: dict | None = None) -> dict:
    """PUT /api/v2/model-spec/caps — set reasoning caps.

    Body: {"max_reasoning": "high"} and/or {"max_budget": 8192}.
    """
    b = body or {}
    from l3.config.settings_center import get_center

    sc = get_center()
    updated = []
    if "max_reasoning" in b:
        tier = str(b["max_reasoning"])
        try:
            from l1.kernel.params.api import EFFORT_RANK

            if tier not in EFFORT_RANK:
                return {"success": False, "error": f"invalid tier: {tier} (none|low|medium|high|xhigh|max)"}
        except Exception:
            pass
        sc.set("think.max_reasoning", tier)
        updated.append("max_reasoning")
    if "max_budget" in b:
        try:
            budget = int(b["max_budget"])
        except (TypeError, ValueError):
            return {"success": False, "error": "max_budget must be an int"}
        if budget < 0:
            return {"success": False, "error": "max_budget must be >= 0"}
        sc.set("think.max_budget", budget)
        updated.append("max_budget")
    return {
        "success": True,
        "updated": updated,
        "caps": {
            "max_reasoning": sc.get("think.max_reasoning", "max"),
            "max_budget": sc.get("think.max_budget", 32768),
        },
    }


def handle_peer_strategy_apply(body: dict | None = None) -> dict:
    """PUT /api/v2/model-spec/peer — apply a strategy pack to a think scope.

    Body: {"scope": "agent", "name": "cell-1.agent-a", "strategy": "deep"}
    Scopes: global | cell (name=cell_id) | agent (name=cell.agent).
    """
    b = body or {}
    scope = b.get("scope", "")
    name = b.get("name", "")
    strategy = b.get("strategy", "")
    if not scope or not strategy:
        return {"success": False, "error": "scope and strategy required"}
    from l3.scheduler.think_registry import get_think_registry

    return get_think_registry().apply_strategy(scope, name, strategy)


def handle_peer_strategy_clear(body: dict | None = None) -> dict:
    """DELETE /api/v2/model-spec/peer — clear a strategy from a think scope."""
    b = body or {}
    scope = b.get("scope", "")
    name = b.get("name", "")
    if not scope:
        return {"success": False, "error": "scope required"}
    from l3.scheduler.think_registry import get_think_registry

    return get_think_registry().clear_strategy(scope, name)


def handle_peer_strategy_get(body: dict | None = None) -> dict:
    """GET /api/v2/model-spec/peer — current think scopes (global/cell/agent)."""
    from l3.scheduler.think_registry import get_think_registry

    reg = get_think_registry()
    return {"success": True, "state": reg.stats()}


# ── SubAgent platform config ────────────────────────────────


def handle_subagent_defaults(body: dict | None = None) -> dict:
    """GET /api/v2/subagent/defaults — get subagent platform defaults."""
    from l3.config.settings_center import get_center

    sc = get_center()
    all_ = sc.all() if hasattr(sc, "all") else {}
    result = {}
    for k, v in all_.items():
        if k.startswith("model_spec.subagent.defaults"):
            result[k[len("model_spec.subagent.defaults.") :]] = v
    return {"success": True, "defaults": result}


def handle_subagent_defaults_update(body: dict | None = None) -> dict:
    """PUT /api/v2/subagent/defaults — update subagent platform defaults."""
    b = body or {}
    from l3.config.settings_center import get_center

    sc = get_center()
    for key, value in b.items():
        sc.set(f"model_spec.subagent.defaults.{key}", value)
    return {"success": True, "updated": list(b.keys())}


def handle_subagent_spec_config(name: str = "") -> dict:
    """GET /api/v2/subagent/specs/{name} — get per-subagent model config."""
    if not name:
        return {"success": False, "error": "name required"}
    from l3.config.settings_center import get_center

    sc = get_center()
    all_ = sc.all() if hasattr(sc, "all") else {}
    result = {}
    for k, v in all_.items():
        if k.startswith(f"model_spec.subagent.specs.{name}"):
            result[k[len(f"model_spec.subagent.specs.{name}.") :]] = v
    return {"success": True, "spec": name, "config": result}


def handle_subagent_spec_config_update(name: str = "", body: dict | None = None) -> dict:
    """PUT /api/v2/subagent/specs/{name} — update per-subagent model config."""
    if not name:
        return {"success": False, "error": "name required"}
    b = body or {}
    from l3.config.settings_center import get_center

    sc = get_center()
    for key, value in b.items():
        sc.set(f"model_spec.subagent.specs.{name}.{key}", value)
    return {"success": True, "spec": name, "updated": list(b.keys())}


# ── Scout config ────────────────────────────────────────────


def handle_scout_config(body: dict | None = None) -> dict:
    """GET /api/v2/scout/config — get scout model config."""
    from l3.config.settings_center import get_center

    sc = get_center()
    all_ = sc.all() if hasattr(sc, "all") else {}
    result = {}
    for k, v in all_.items():
        if k.startswith("model_spec.scout"):
            result[k[len("model_spec.scout.") :]] = v
    return {"success": True, "config": result}


def handle_scout_config_update(body: dict | None = None) -> dict:
    """PUT /api/v2/scout/config — update scout model config."""
    b = body or {}
    from l3.config.settings_center import get_center

    sc = get_center()
    for key, value in b.items():
        sc.set(f"model_spec.scout.{key}", value)
    return {"success": True, "updated": list(b.keys())}


# ── R4Agent config ──────────────────────────────────────────


def handle_r4_config(body: dict | None = None) -> dict:
    """GET /api/v2/r4/config — get R4Agent model config."""
    from l3.config.settings_center import get_center

    sc = get_center()
    all_ = sc.all() if hasattr(sc, "all") else {}
    result = {}
    for k, v in all_.items():
        if k.startswith("model_spec.r4_agent"):
            result[k[len("model_spec.r4_agent.") :]] = v
    return {"success": True, "config": result}


def handle_r4_config_update(body: dict | None = None) -> dict:
    """PUT /api/v2/r4/config — update R4Agent model config."""
    b = body or {}
    from l3.config.settings_center import get_center

    sc = get_center()
    for key, value in b.items():
        sc.set(f"model_spec.r4_agent.{key}", value)
    return {"success": True, "updated": list(b.keys())}


# ── Convention config ───────────────────────────────────────


def handle_convention_config(body: dict | None = None) -> dict:
    """GET /api/v2/convention/config — get convention model config."""
    from l3.config.settings_center import get_center

    sc = get_center()
    all_ = sc.all() if hasattr(sc, "all") else {}
    result = {}
    for k, v in all_.items():
        if k.startswith("model_spec.convention"):
            result[k[len("model_spec.convention.") :]] = v
    return {"success": True, "config": result}


def handle_convention_config_update(body: dict | None = None) -> dict:
    """PUT /api/v2/convention/config — update convention model config."""
    b = body or {}
    from l3.config.settings_center import get_center

    sc = get_center()
    for key, value in b.items():
        sc.set(f"model_spec.convention.{key}", value)
    return {"success": True, "updated": list(b.keys())}
