"""Config section handlers — extracted from config_loader.py for modularity.

Each _cfg_* handler processes one section of praxis.yaml and applies
its values to the corresponding kernel/service configuration.
"""

from __future__ import annotations

from typing import Any

from kernel.params import (
    TERRITORY_MAP, TERRITORY_PATHS, SHARED_PATHS,
    DEFAULT_AGENT_CONFIGS, AGENT_CLEARANCE,
    ALLOCATOR_DEFAULTS, SCOUT_POOL_MAX_TOTAL, SCOUT_POOL_MAX_PER_AGENT,
    SCOUT_CACHE_TTL, TERMINAL_MAX_WORKERS, TERMINAL_POLL_INTERVAL,
    CARD_WAIT_TIMEOUT,
)
from kernel.device import get_device_manager, DeviceType


def cfg_kernel(cfg: dict, s: Any, results: dict) -> None:
    alloc = cfg.get("allocator", {})
    if "tokens" in alloc:
        ALLOCATOR_DEFAULTS.tokens = alloc["tokens"]
        s.set("kernel.allocator.tokens", alloc["tokens"])
    swp = cfg.get("swapper", {})
    if "interval" in swp:
        s.set("kernel.swapper.interval", swp["interval"])
    results["kernel"] = True


def cfg_cell(cfg: dict, s: Any, results: dict) -> None:
    term = cfg.get("terminal", {})
    if "workers" in term:
        TERMINAL_MAX_WORKERS = term["workers"]
        s.set("cell.terminal.workers", term["workers"])
    if "poll" in term:
        TERMINAL_POLL_INTERVAL = term["poll"]
    scout = cfg.get("scout", {})
    if "max_total" in scout:
        SCOUT_POOL_MAX_TOTAL = scout["max_total"]
    if "max_per_agent" in scout:
        SCOUT_POOL_MAX_PER_AGENT = scout["max_per_agent"]
    if "cache_ttl" in scout:
        SCOUT_CACHE_TTL = scout["cache_ttl"]
    card = cfg.get("card", {})
    if "timeout" in card:
        CARD_WAIT_TIMEOUT = card["timeout"]
    results["cell"] = True


def cfg_llm(cfg: dict, s: Any, results: dict) -> None:
    for k in ("provider", "model", "api_url", "api_key", "max_tokens", "temperature", "rate_limit"):
        if k in cfg:
            s.set(f"llm.{k}", cfg[k])
    cache_cfg = cfg.get("cache", {})
    if cache_cfg:
        from .cache_strategy import load_cache_config
        load_cache_config(cache_cfg)
        results["llm_cache"] = len(cache_cfg)
    results["llm"] = True


def cfg_constitution(cfg: dict, s: Any, results: dict) -> None:
    from kernel.params import (CONSTITUTION_FILE_ACTIONS, CONSTITUTION_MODIFY_ACTIONS,
                                CONSTITUTION_GATE_ACTIONS, CONSTITUTION_SCOUT_BLOCKED)
    if "file_actions" in cfg:
        CONSTITUTION_FILE_ACTIONS = frozenset(cfg["file_actions"])
    if "modify_actions" in cfg:
        CONSTITUTION_MODIFY_ACTIONS = frozenset(cfg["modify_actions"])
    if "gate_actions" in cfg:
        CONSTITUTION_GATE_ACTIONS = frozenset(cfg["gate_actions"])
    if "scout_blocked" in cfg:
        CONSTITUTION_SCOUT_BLOCKED = frozenset(cfg["scout_blocked"])
    results["constitution"] = True


def cfg_gatechain(cfg: dict, s: Any, results: dict) -> None:
    from kernel.params import (GATECHAIN_DANGER_LEVELS, GATECHAIN_ESCALATION_DANGER,
                                GATECHAIN_RISK_WARN_THRESHOLD, GATECHAIN_REPEAT_THRESHOLD,
                                GATECHAIN_HIGH_FREQ_THRESHOLD, GATECHAIN_G5_HISTORY_LIMIT)
    if "danger_levels" in cfg:
        GATECHAIN_DANGER_LEVELS.clear(); GATECHAIN_DANGER_LEVELS.update(cfg["danger_levels"])
    if "escalation_danger" in cfg: GATECHAIN_ESCALATION_DANGER = int(cfg["escalation_danger"])
    if "risk_warn_threshold" in cfg: GATECHAIN_RISK_WARN_THRESHOLD = float(cfg["risk_warn_threshold"])
    if "repeat_threshold" in cfg: GATECHAIN_REPEAT_THRESHOLD = int(cfg["repeat_threshold"])
    if "high_freq_threshold" in cfg: GATECHAIN_HIGH_FREQ_THRESHOLD = int(cfg["high_freq_threshold"])
    if "history_limit" in cfg: GATECHAIN_G5_HISTORY_LIMIT = int(cfg["history_limit"])
    results["gatechain"] = True


def cfg_tool_rates(cfg: dict, s: Any, results: dict) -> None:
    from kernel.params import TOOL_RATE_RING_1, TOOL_RATE_RING_2_5, TOOL_RATE_RING_3
    if "ring_1" in cfg: TOOL_RATE_RING_1 = int(cfg["ring_1"])
    if "ring_2_5" in cfg: TOOL_RATE_RING_2_5 = int(cfg["ring_2_5"])
    if "ring_3" in cfg: TOOL_RATE_RING_3 = int(cfg["ring_3"])
    results["tool_rates"] = True


def cfg_htn(cfg: dict, s: Any, results: dict) -> None:
    from kernel.params import HTN_DEFAULT_TOOLS, HTN_DOMAIN_PREFIX
    if "domain_prefix" in cfg: HTN_DOMAIN_PREFIX = cfg["domain_prefix"]
    if "tools" in cfg: HTN_DEFAULT_TOOLS.clear(); HTN_DEFAULT_TOOLS.update(cfg["tools"])
    results["htn"] = True


def cfg_cache(cfg: dict, s: Any, results: dict) -> None:
    from kernel.params import FILE_CACHE_MAX_ENTRIES, FILE_CACHE_MAX_SIZE, FILE_CACHE_TTL, CONTEXT_REGISTER_MAX_ENTRIES
    if "max_entries" in cfg: FILE_CACHE_MAX_ENTRIES = int(cfg["max_entries"])
    if "max_size_mb" in cfg: FILE_CACHE_MAX_SIZE = int(cfg["max_size_mb"]) * 1024 * 1024
    if "ttl" in cfg: FILE_CACHE_TTL = float(cfg["ttl"])
    if "context_max" in cfg: CONTEXT_REGISTER_MAX_ENTRIES = int(cfg["context_max"])
    results["cache"] = True


def cfg_persist(cfg: dict, s: Any, results: dict) -> None:
    from kernel.params import PERSIST_AUTO, PERSIST_INTERVAL
    if "enabled" in cfg: PERSIST_AUTO = bool(cfg["enabled"])
    if "interval" in cfg: PERSIST_INTERVAL = float(cfg["interval"])
    results["persist"] = True


def cfg_network(cfg: dict, s: Any, results: dict) -> None:
    import os as _os
    if "discovery_port" in cfg: _os.environ["PRAXIS_DISCOVERY_PORT"] = str(cfg["discovery_port"])
    if "mesh_port" in cfg: _os.environ["PRAXIS_PORT"] = str(cfg["mesh_port"])
    results["network"] = True


def cfg_api(cfg: dict, s: Any, results: dict) -> None:
    from services.api_gateway import start_api
    from kernel.params import API_GATEWAY_HOST, API_GATEWAY_PORT
    host = cfg.get("host", API_GATEWAY_HOST)
    port = int(cfg.get("port", API_GATEWAY_PORT))
    token = cfg.get("auth_token", "")
    start_api(host, port, token)
    results["api"] = True


def cfg_card_gate(cfg: dict, s: Any, results: dict) -> None:
    """Load card gate config from praxis.yaml → card_gate: section."""
    try:
        from .card_gate import load_config
        load_config(cfg if isinstance(cfg, dict) else {})
        results["card_gate"] = True
    except Exception as e:
        results["card_gate"] = f"error: {e}"


def cfg_prompts(cfg: dict, s: Any, results: dict) -> None:
    """Load prompt template overrides from praxis.yaml prompts: section."""
    try:
        from kernel.prompts import load_prompt_overrides
        load_prompt_overrides(cfg if isinstance(cfg, dict) else {})
        results["prompts"] = len(cfg) if isinstance(cfg, dict) else 0
    except Exception as e:
        results["prompts"] = f"error: {e}"


def cfg_content_trust(cfg: dict, s: Any, results: dict) -> None:
    """Load content trust policies from praxis.yaml -> content_trust: section."""
    from .content_trust import load_policies
    load_policies(cfg if isinstance(cfg, dict) else {})
    results["content_trust"] = len(cfg) if isinstance(cfg, dict) else 0


def cfg_card_types(cfg: dict, s: Any, results: dict) -> None:
    """Load card type definitions from praxis.yaml → card_types: section."""
    from .card_unified import load_card_types
    load_card_types(cfg if isinstance(cfg, dict) else {})
    results["card_types"] = len(cfg) if isinstance(cfg, dict) else 0


def cfg_mcp(cfg: dict, s: Any, results: dict) -> None:
    """Import MCP servers from praxis.yaml mcp.servers section."""
    from .mcp_bridge import McpClient, get_bridge
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


def cfg_commands(cfg: dict, s: Any, results: dict) -> None:
    """Load command overrides from praxis.yaml commands: section."""
    from kernel.commands import load_command_overrides
    load_command_overrides(cfg if isinstance(cfg, dict) else {})
    results["commands"] = len(cfg) if isinstance(cfg, dict) else 0


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
        from .credential_vault import set_credential
        count = 0
        for provider, keys in (cfg or {}).items():
            for key_name, value in keys.items():
                r = set_credential(provider, key_name, str(value))
                if r.get("success"):
                    count += 1
        results["credentials"] = count
    except Exception as e:
        results["credentials"] = f"error: {e}"


def cfg_api_routes(cfg: dict, s: Any, results: dict) -> None:
    """Load external API routes from praxis.yaml api.routes section."""
    try:
        from services.api_gateway import load_routes_from_yaml
        r = load_routes_from_yaml(cfg if isinstance(cfg, list) else [])
        results["api_routes"] = r.get("loaded", 0)
    except Exception as e:
        results["api_routes"] = f"error: {e}"


def cfg_devices(cfg: dict, s: Any, results: dict) -> None:
    dm = get_device_manager()
    for d in (cfg if isinstance(cfg, list) else []):
        name = d.get("name", "")
        dtype_name = d.get("type", "CUSTOM").upper()
        try: dtype = DeviceType[dtype_name]
        except Exception: dtype = DeviceType.CUSTOM
        dm.register(name, dtype, rate_limit=d.get("rate_limit", 10), description=d.get("description", ""))
    results["devices"] = len(cfg) if isinstance(cfg, list) else 0


def cfg_territories(cfg: dict, s: Any, results: dict) -> None:
    TERRITORY_MAP.clear(); TERRITORY_PATHS.clear()
    for role, paths in cfg.items():
        TERRITORY_PATHS[role] = paths
        for p in paths: TERRITORY_MAP[p] = role
    results["territories"] = len(cfg)


def cfg_clearance(cfg: dict, s: Any, results: dict) -> None:
    AGENT_CLEARANCE.clear(); AGENT_CLEARANCE.update(cfg)
    results["clearance"] = len(cfg)


def cfg_agents(cfg: dict, s: Any, results: dict) -> None:
    from kernel.params import AgentDefaults
    for role, cdict in cfg.items():
        mc = cdict.get("model_config", None)
        spk = cdict.get("system_prompt_key", "")
        DEFAULT_AGENT_CONFIGS[role] = AgentDefaults(
            max_scouts=cdict.get("max_scouts", 3),
            ring=cdict.get("ring", 1),
            model_config=mc if isinstance(mc, dict) else None,
            system_prompt_key=str(spk) if spk else "",
        )
    results["agents"] = len(cfg)
