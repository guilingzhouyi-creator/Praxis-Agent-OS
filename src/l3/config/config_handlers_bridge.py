"""Config section handlers — bridge / L4-facing domains (api, mcp, vault, diff, commands).

Each ``cfg_*`` handler processes one section of praxis.yaml and applies its
values through L4 adapters. Re-exported by ``config_handlers.py``.

Cross-layer (L3 → L4) imports here are allowlisted in
``tests/infra/test_layer_imports.py``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def cfg_api(cfg: dict, s: Any, results: dict) -> None:
    """Apply api section: start the API gateway and load external routes."""
    from l1.kernel.params.api import API_GATEWAY_HOST, API_GATEWAY_PORT
    from l4.api.api_gateway import start_api

    host = cfg.get("host", API_GATEWAY_HOST)
    port = int(cfg.get("port", API_GATEWAY_PORT))
    token = cfg.get("auth_token", "")
    start_api(host, port, token)
    mcp_mode = cfg.get("mcp_mode", "")
    if mcp_mode:
        from l4.api_handlers.api_handlers_mcp import set_export_mode

        set_export_mode(mcp_mode)
    # api.routes — external route registrations (see api_gateway.load_routes_from_yaml)
    routes = cfg.get("routes") or []
    if isinstance(routes, list):
        try:
            from l4.api.api_gateway import load_routes_from_yaml

            r = load_routes_from_yaml(routes)
            results["api_routes"] = r.get("loaded", 0)
        except Exception as e:
            results["api_routes"] = f"error: {e}"
    results["api"] = True


def cfg_api_routes(cfg: dict, s: Any, results: dict) -> None:
    """Load external API routes from praxis.yaml api.routes section."""
    try:
        from l4.api.api_gateway import load_routes_from_yaml

        r = load_routes_from_yaml(cfg if isinstance(cfg, list) else [])
        results["api_routes"] = r.get("loaded", 0)
    except Exception as e:
        results["api_routes"] = f"error: {e}"


def cfg_mcp(cfg: dict, s: Any, results: dict) -> None:
    """Import MCP servers from praxis.yaml mcp.servers section."""
    from l4.mcp_bridge import McpClient, get_bridge

    if not cfg:
        results["mcp_servers"] = 0
        return
    servers = cfg if isinstance(cfg, list) else cfg.get("servers", []) or []
    imported = 0
    for sv in servers:
        name = sv.get("name", "")
        endpoint = sv.get("endpoint", "")
        api_key = sv.get("api_key", "")
        if name and endpoint:
            try:
                client = McpClient(endpoint, api_key)
                r = get_bridge().import_server(name, client)
                if r.get("success"):
                    imported += 1
            except Exception as e:
                logger.warning("mcp auto-import %s failed: %s", name, e)
    results["mcp_servers"] = imported


def cfg_credentials(cfg: dict, s: Any, results: dict) -> None:
    """Load LLM API credentials from praxis.yaml credentials section.

    YAML format:
      credentials:
        openai:
          api_key: sk-...
          api_url: https://...
        anthropic:
          api_key: sk-ant-...
    """
    try:
        from l4.vault.credential_vault import set_credential

        count = 0
        for provider, keys in (cfg or {}).items():
            for key_name, value in keys.items():
                r = set_credential(provider, key_name, str(value))
                if r.get("success"):
                    count += 1
        results["credentials"] = count
    except Exception as e:
        results["credentials"] = f"error: {e}"


def cfg_commands(cfg: dict, s: Any, results: dict) -> None:
    """Load command overrides + custom commands from praxis.yaml commands: section.

    Format:
      commands:
        # Override metadata for existing commands
        mode:
          help: "switch mode"
          aliases: ["m"]
        # Register new custom commands with handler spec
        my-command:
          help: "My custom command"
          category: "custom"
          handler:
            type: callback       # "callback" | "echo" | "l3_intent"
            response: "hello world"
    """
    from l1.kernel.commands import get_registry

    reg = get_registry()

    # Separate overrides from new command registrations
    overrides = {}
    custom_count = 0
    for name, meta in (cfg or {}).items():
        handler_spec = meta.pop("handler", None) if isinstance(meta, dict) else None
        if handler_spec and isinstance(handler_spec, dict):
            # Register as user command
            htype = handler_spec.get("type", "echo")
            response = handler_spec.get("response", f"{name}: ok")
            if htype == "echo":

                def _make_echo(resp):
                    return lambda args: {"success": True, "output": resp}

                reg.register_user(name, _make_echo(response), meta)
            elif htype == "l3_intent":

                def _make_l3():
                    from l2.l2_shell import dispatch as _d

                    return lambda args: _d("/" + " ".join(args))

                reg.register_user(name, _make_l3(), meta)
            custom_count += 1
        else:
            overrides[name] = meta

    if overrides:
        reg.load_overrides(overrides)
    results["commands"] = {
        "overrides": len(overrides),
        "custom": custom_count,
    }


def cfg_diff(cfg: dict, s: Any, results: dict) -> None:
    """Load diff view settings: mode, heavy API flag, and color scheme."""
    from l3.config.settings_center import get_center

    center = get_center()
    if "mode" in cfg:
        center.set_l2("diff.mode", str(cfg["mode"]))
    if "heavy_api_enabled" in cfg:
        center.set_l2("diff.heavy_api_enabled", bool(cfg["heavy_api_enabled"]))
    if "colors" in cfg and isinstance(cfg["colors"], dict):
        center.set_l2("diff.colors", cfg["colors"])
        try:
            from l4.sandbox.cell_sandbox import set_color_scheme

            set_color_scheme(cfg["colors"])
        except Exception:
            logger.warning("config: diff color scheme apply failed", exc_info=True)
    results["diff"] = True
