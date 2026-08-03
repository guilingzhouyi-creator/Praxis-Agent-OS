"""Config section handlers — extracted from config_loader.py for modularity.

Each _cfg_* handler processes one section of praxis.yaml and applies
its values to the corresponding kernel/service configuration.
"""

from __future__ import annotations

from typing import Any

from l1.kernel.params.agent import (
    TERRITORY_MAP,
    TERRITORY_PATHS,
    SHARED_PATHS,
    DEFAULT_AGENT_CONFIGS,
    AGENT_CLEARANCE,
    TERMINAL_MAX_WORKERS,
    TERMINAL_POLL_INTERVAL,
    CARD_WAIT_TIMEOUT,
)
from l1.kernel.params.kernel import ALLOCATOR_DEFAULTS
from l1.kernel.params.system import SCOUT_POOL_MAX_TOTAL, SCOUT_POOL_MAX_PER_AGENT, SCOUT_CACHE_TTL
from l1.kernel.device import get_device_manager, DeviceType


def cfg_kernel(cfg: dict, s: Any, results: dict) -> None:
    # Consumers (allocator, process table, syscall audit) read params
    # constants directly — setattr on the authoritative modules AND the
    # params.kernel re-export layer, then mirror into SettingsCenter L2.
    import l1.kernel.params.allocator as _alloc_mod
    import l1.kernel.params.kernel as _kernel_mod
    from l1.kernel.params.allocator import ALLOCATOR_DEFAULTS
    alloc = cfg.get("allocator", {})
    if "tokens" in alloc:
        ALLOCATOR_DEFAULTS.tokens = int(alloc["tokens"])
        s.set_l2("l1.kernel.allocator.tokens", alloc["tokens"])
    for yaml_key, field in (("ring1", "ring1"), ("ring2", "ring2"), ("ring3", "ring3")):
        if yaml_key in alloc:
            setattr(ALLOCATOR_DEFAULTS, field, int(alloc[yaml_key]))
            s.set_l2(f"l1.kernel.allocator.{yaml_key}", alloc[yaml_key])
    swp = cfg.get("swapper", {})
    if "interval" in swp:
        _kernel_mod.SWAPPER_DEFAULT_INTERVAL = float(swp["interval"])
        s.set_l2("l1.kernel.swapper.interval", swp["interval"])
    proc = cfg.get("process", {})
    if "max_pid" in proc:
        _alloc_mod.PROCESS_TABLE_MAX = int(proc["max_pid"])
        _kernel_mod.PROCESS_TABLE_MAX = int(proc["max_pid"])
        s.set_l2("l1.kernel.process.max_pid", proc["max_pid"])
    if "audit_max" in proc:
        _alloc_mod.PROCESS_AUDIT_MAX = int(proc["audit_max"])
        _kernel_mod.PROCESS_AUDIT_MAX = int(proc["audit_max"])
        s.set_l2("l1.kernel.process.audit_max", proc["audit_max"])
    sc = cfg.get("syscall", {})
    if "audit_max" in sc:
        _kernel_mod.SYSCALL_AUDIT_MAX = int(sc["audit_max"])
        s.set_l2("l1.kernel.syscall.audit_max", sc["audit_max"])
    results["kernel"] = True


def cfg_cell(cfg: dict, s: Any, results: dict) -> None:
    # Consumers (agent_terminal, scout pool) read the params constants
    # directly, so setattr them in addition to mirroring into SettingsCenter L2.
    import l1.kernel.params.agent as _agent_mod
    import l1.kernel.params.system as _sys_mod
    term = cfg.get("terminal", {})
    if "workers" in term:
        _agent_mod.TERMINAL_MAX_WORKERS = int(term["workers"])
        s.set_l2("terminal.max_workers", term["workers"])
    if "poll" in term:
        _agent_mod.TERMINAL_POLL_INTERVAL = float(term["poll"])
        s.set_l2("cell.terminal.poll", term["poll"])
    scout = cfg.get("scout", {})
    if "max_total" in scout:
        _sys_mod.SCOUT_POOL_MAX = int(scout["max_total"])
        s.set_l2("scout.max_total", scout["max_total"])
    if "max_per_agent" in scout:
        _sys_mod.SCOUT_POOL_MAX_PER_AGENT = int(scout["max_per_agent"])
        _sys_mod.MAX_SCOUTS_PER_AGENT = int(scout["max_per_agent"])
        s.set_l2("scout.max_per_agent", scout["max_per_agent"])
    if "cache_ttl" in scout:
        _sys_mod.SCOUT_CACHE_TTL = float(scout["cache_ttl"])
        s.set_l2("scout.cache_ttl", scout["cache_ttl"])
    if "session_timeout" in scout:
        _sys_mod.SCOUT_TIMEOUT = float(scout["session_timeout"])
        s.set_l2("scout.session_timeout", scout["session_timeout"])
    card = cfg.get("card", {})
    if "timeout" in card:
        _agent_mod.CARD_WAIT_TIMEOUT = float(card["timeout"])
        s.set_l2("cell.card.timeout", card["timeout"])
    results["cell"] = True


def cfg_llm(cfg: dict, s: Any, results: dict) -> None:
    for k in ("provider", "model", "api_url", "api_key", "max_tokens", "temperature", "rate_limit"):
        if k in cfg:
            s.set_l2(f"llm.{k}", cfg[k])
    cache_cfg = cfg.get("cache", {})
    if cache_cfg:
        from .cache_strategy import load_cache_config
        load_cache_config(cache_cfg)
        results["llm_cache"] = len(cache_cfg)
    results["llm"] = True


def cfg_constitution(cfg: dict, s: Any, results: dict) -> None:
    """Load constitution config from praxis.yaml.

    Stores action sets in both module-level constants (for hot-path perf)
    and SettingsCenter (for API query/runtime override).
    """
    import l1.kernel.params.agent as _agent_mod
    from l1.kernel.discovery import set_config as _set_cfg
    if "file_actions" in cfg:
        val = frozenset(cfg["file_actions"])
        _agent_mod.CONSTITUTION_FILE_ACTIONS = val
        _set_cfg("constitution", "file_actions", sorted(val))
        s.set_l2("constitution.file_actions", list(val))
    if "modify_actions" in cfg:
        val = frozenset(cfg["modify_actions"])
        _agent_mod.CONSTITUTION_MODIFY_ACTIONS = val
        _set_cfg("constitution", "modify_actions", sorted(val))
        s.set_l2("constitution.modify_actions", list(val))
    if "gate_actions" in cfg:
        val = frozenset(cfg["gate_actions"])
        _agent_mod.CONSTITUTION_GATE_ACTIONS = val
        _set_cfg("constitution", "gate_actions", sorted(val))
        s.set_l2("constitution.gate_actions", list(val))
    if "scout_blocked" in cfg:
        val = frozenset(cfg["scout_blocked"])
        _agent_mod.CONSTITUTION_SCOUT_BLOCKED = val
        _set_cfg("constitution", "scout_blocked", sorted(val))
        s.set_l2("constitution.scout_blocked", list(val))

    # Load custom rules from YAML (optional)
    rules = cfg.get("rules", [])
    if rules:
        try:
            from l1.kernel.constitution import get_constitution
            c = get_constitution()
            s.set_l2("constitution.custom_rules", rules)
            c.update_rules(rules)
        except Exception as e:
            logger.warning("constitution rules load: %s", e)

    results["constitution"] = True


def cfg_gatechain(cfg: dict, s: Any, results: dict) -> None:
    import l1.kernel.params.gatechain as _gatechain_mod
    import l1.kernel.params.kernel as _kernel_mod
    from l1.kernel.discovery import set_config as _set_cfg
    if "danger_levels" in cfg:
        _gatechain_mod.GATECHAIN_DANGER_LEVELS.clear()
        _gatechain_mod.GATECHAIN_DANGER_LEVELS.update(cfg["danger_levels"])
        for _action, _danger in cfg["danger_levels"].items():
            _set_cfg("gatechain_danger_levels", _action, _danger)
    # Scalar thresholds: setattr on the authoritative params modules AND the
    # discovery registry (gatechain.py reads get_config("gatechain")).
    _scalars = {
        "escalation_danger": ("GATECHAIN_ESCALATION_DANGER", int),
        "risk_warn_threshold": ("GATECHAIN_RISK_WARN_THRESHOLD", float),
        "repeat_threshold": ("GATECHAIN_REPEAT_THRESHOLD", int),
        "high_freq_threshold": ("GATECHAIN_HIGH_FREQ_THRESHOLD", int),
        "history_limit": ("GATECHAIN_G5_HISTORY_LIMIT", int),
    }
    for yaml_key, (attr, cast) in _scalars.items():
        if yaml_key in cfg:
            val = cast(cfg[yaml_key])
            setattr(_gatechain_mod, attr, val)
            setattr(_kernel_mod, attr, val)
            _set_cfg("gatechain", yaml_key, val)
    results["gatechain"] = True


def cfg_tool_rates(cfg: dict, s: Any, results: dict) -> None:
    """Load tool rate limits from praxis.yaml tool_rates: section.

    Writes into discovery "tool_rates" (scheduler_rate.py reads it),
    params/tool.py constants, and SettingsCenter L2.
    """
    import l1.kernel.params.tool as _tool_mod
    from l1.kernel.discovery import set_config as _set_cfg
    _rate_map = {
        "ring_1": "TOOL_RATE_RING_1",
        "ring_2_5": "TOOL_RATE_RING_2_5",
        "ring_3": "TOOL_RATE_RING_3",
    }
    for yaml_key, attr in _rate_map.items():
        if yaml_key in cfg:
            setattr(_tool_mod, attr, int(cfg[yaml_key]))
            _set_cfg("tool_rates", yaml_key, int(cfg[yaml_key]))
            s.set_l2(f"tool_rates.{yaml_key}", cfg[yaml_key])
    results["tool_rates"] = True


def cfg_tool(cfg: dict, s: Any, results: dict) -> None:
    """Load tool timeout config from praxis.yaml tool: section.

    Writes into params/tool.py (via setattr), the discovery "tool" registry
    (get_tool_config reads it), and SettingsCenter L2.
    """
    import l1.kernel.params.tool as _tool_mod
    from l1.kernel.discovery import set_config as _set_cfg
    _timeout_map = {
        "web_timeout": "TOOL_WEB_TIMEOUT",
        "search_timeout": "TOOL_SEARCH_TIMEOUT",
        "terminal_timeout": "TOOL_TERMINAL_TIMEOUT",
        "git_timeout": "TOOL_GIT_TIMEOUT",
        "build_timeout": "TOOL_BUILD_TIMEOUT",
        "pip_install_timeout": "TOOL_PIP_INSTALL_TIMEOUT",
        "npm_timeout": "TOOL_NPM_TIMEOUT",
        "pyright_timeout": "TOOL_PYRIGHT_TIMEOUT",
        "compile_check_timeout": "TOOL_COMPILE_CHECK_TIMEOUT",
        "package_manager_timeout": "TOOL_PACKAGE_MANAGER_TIMEOUT",
        "handler_timeout": "TOOL_HANDLER_TIMEOUT",
    }
    for yaml_key, attr in _timeout_map.items():
        if yaml_key in cfg:
            setattr(_tool_mod, attr, cfg[yaml_key])
            _set_cfg("tool", yaml_key, cfg[yaml_key])
            s.set_l2(f"tool.{yaml_key}", cfg[yaml_key])
    # Build/test detectors: praxis.yaml uses list-of-lists; discovery uses
    # {name: {cmd: [...]}}. Convert for get_config("build_detectors").
    for yaml_key, params_attr in (("build_detectors", "BUILD_DETECTORS"),
                                  ("test_detectors", "TEST_DETECTORS")):
        if yaml_key in cfg and isinstance(cfg[yaml_key], list):
            cmds = [tuple(c) if isinstance(c, (list, tuple)) else (c,) for c in cfg[yaml_key]]
            setattr(_tool_mod, params_attr, cmds)
            for i, c in enumerate(cmds):
                _set_cfg(yaml_key, f"d{i}", {"cmd": list(c)})
            s.set_l2(f"tool.{yaml_key}", cmds)
    results["tool"] = True


def cfg_persistence(cfg: dict, s: Any, results: dict) -> None:
    """Load persistence auto-save intervals from praxis.yaml persistence: section.

    Writes into discovery "persistence" (approval_gate/card_gate read it),
    params/system.py constants, and SettingsCenter L2.
    """
    import l1.kernel.params.system as _sys_mod
    from l1.kernel.discovery import set_config as _set_cfg
    _persist_map = {
        "auto_save": "PERSIST_AUTO",
        "interval": "PERSIST_INTERVAL",
        "card_registry": "CARD_REGISTRY_AUTO_SAVE",
        "card_gate": "CARD_GATE_AUTO_SAVE",
        "pending_queue": "PENDING_QUEUE_AUTO_SAVE",
        "issue_table": "ISSUE_TABLE_AUTO_SAVE",
        "approval_gate": "APPROVAL_GATE_AUTO_SAVE",
        "sandbox_state": "SANDBOX_STATE_AUTO_SAVE",
        "todo_table": "TODO_TABLE_AUTO_SAVE",
        "transaction_area": "TRANSACTION_AREA_AUTO_SAVE",
        "statecharts": "STATECHARTS_AUTO_SAVE",
        "execution_results": "EXECUTION_RESULTS_AUTO_SAVE",
        "dialogue_session": "DIALOGUE_SESSION_AUTO_SAVE",
    }
    for yaml_key, attr in _persist_map.items():
        if yaml_key in cfg:
            setattr(_sys_mod, attr, cfg[yaml_key])
            _set_cfg("persistence", yaml_key, cfg[yaml_key])
            s.set_l2(f"persistence.{yaml_key}", cfg[yaml_key])
    results["persistence"] = True


def cfg_services(cfg: dict, s: Any, results: dict) -> None:
    """Load service timeouts from praxis.yaml services: section.

    Writes into discovery "services" (convention.py reads it),
    params/api.py constants, and SettingsCenter L2.
    """
    import l1.kernel.params.api as _api_mod
    from l1.kernel.discovery import set_config as _set_cfg
    _svc_map = {
        "lsp_manager_timeout": "LSP_MANAGER_TIMEOUT",
        "lsp_long_timeout": "LSP_MANAGER_LONG_TIMEOUT",
        "lsp_diag_timeout": "LSP_DIAG_TIMEOUT",
        "mcp_bridge_timeout": "MCP_BRIDGE_TIMEOUT",
        "mcp_bridge_long_timeout": "MCP_BRIDGE_LONG_TIMEOUT",
        "shell_session_timeout": "SHELL_SESSION_TIMEOUT",
        "pool_queue_timeout": "POOL_QUEUE_TIMEOUT",
        "term_handler_timeout": "TERM_HANDLER_TIMEOUT",
        "term_handler_long_timeout": "TERM_HANDLER_LONG_TIMEOUT",
        "gateway_queue_timeout": "API_GATEWAY_QUEUE_TIMEOUT",
        "r4_agent_join_timeout": "R4_AGENT_JOIN_TIMEOUT",
        "subagent_run_timeout": "SUBAGENT_RUN_TIMEOUT",
        "subagent_join_timeout": "SUBAGENT_JOIN_TIMEOUT",
    }
    for yaml_key, attr in _svc_map.items():
        if yaml_key in cfg:
            setattr(_api_mod, attr, cfg[yaml_key])
            _set_cfg("services", yaml_key, cfg[yaml_key])
            s.set_l2(f"services.{yaml_key}", cfg[yaml_key])
    results["services"] = True


def cfg_card_pool(cfg: dict, s: Any, results: dict) -> None:
    """Load card pool registry config from praxis.yaml card_pool: section.

    No runtime consumer yet — expose to SettingsCenter L2 for API querying.
    """
    from l3.config.settings_center import get_center
    center = get_center()
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            center.set_l2(f"card_pool.{k}", v)
    results["card_pool"] = True


def cfg_htn(cfg: dict, s: Any, results: dict) -> None:
    import l1.kernel.params.tool as _tool_mod
    if "domain_prefix" in cfg:
        _tool_mod.HTN_DOMAIN_PREFIX = cfg["domain_prefix"]
    if "tools" in cfg:
        _tool_mod.HTN_DEFAULT_TOOLS.clear(); _tool_mod.HTN_DEFAULT_TOOLS.update(cfg["tools"])
    results["htn"] = True


def cfg_cache(cfg: dict, s: Any, results: dict) -> None:
    import l1.kernel.params.system as _sys_mod
    if "max_entries" in cfg:
        _sys_mod.FILE_CACHE_MAX_ENTRIES = int(cfg["max_entries"])
    if "max_size_mb" in cfg:
        _sys_mod.FILE_CACHE_MAX_SIZE = int(cfg["max_size_mb"]) * 1024 * 1024
    if "ttl" in cfg:
        _sys_mod.FILE_CACHE_TTL = float(cfg["ttl"])
    if "context_max" in cfg:
        _sys_mod.CONTEXT_REGISTER_MAX_ENTRIES = int(cfg["context_max"])
    results["cache"] = True


def cfg_persist(cfg: dict, s: Any, results: dict) -> None:
    import l1.kernel.params.system as _sys_mod
    if "enabled" in cfg:
        _sys_mod.PERSIST_AUTO = bool(cfg["enabled"])
    if "interval" in cfg:
        _sys_mod.PERSIST_INTERVAL = float(cfg["interval"])
    results["persist"] = True


def cfg_network(cfg: dict, s: Any, results: dict) -> None:
    import os as _os
    import l1.kernel.params.api as _api_mod
    import l1.kernel.params.system as _sys_mod
    if "discovery_port" in cfg:
        _os.environ["PRAXIS_DISCOVERY_PORT"] = str(cfg["discovery_port"])
        _api_mod.DISCOVERY_PORT_DEFAULT = int(cfg["discovery_port"])
        s.set_l2("network.discovery_port", cfg["discovery_port"])
    if "mesh_port" in cfg:
        _os.environ["PRAXIS_PORT"] = str(cfg["mesh_port"])
        _api_mod.PRAXIS_PORT_DEFAULT = int(cfg["mesh_port"])
        s.set_l2("network.mesh_port", cfg["mesh_port"])
    if "broadcast_interval" in cfg:
        _api_mod.BROADCAST_INTERVAL = float(cfg["broadcast_interval"])
        s.set_l2("network.broadcast_interval", cfg["broadcast_interval"])
    if "peer_timeout" in cfg:
        _sys_mod.NET_PEER_TIMEOUT = float(cfg["peer_timeout"])
        s.set_l2("network.peer_timeout", cfg["peer_timeout"])
    results["network"] = True


def cfg_api(cfg: dict, s: Any, results: dict) -> None:
    from l4.api.api_gateway import start_api
    from l1.kernel.params.api import API_GATEWAY_HOST, API_GATEWAY_PORT
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


def cfg_card_gate(cfg: dict, s: Any, results: dict) -> None:
    """Load card gate config from praxis.yaml → card_gate: section."""
    try:
        from l3.card.card_gate import load_config
        load_config(cfg if isinstance(cfg, dict) else {})
        results["card_gate"] = True
    except Exception as e:
        results["card_gate"] = f"error: {e}"


def cfg_prompts(cfg: dict, s: Any, results: dict) -> None:
    """Load prompt template overrides from praxis.yaml prompts: section."""
    try:
        from l1.kernel.prompts import load_prompt_overrides
        load_prompt_overrides(cfg if isinstance(cfg, dict) else {})
        results["prompts"] = len(cfg) if isinstance(cfg, dict) else 0
    except Exception as e:
        results["prompts"] = f"error: {e}"


def cfg_content_trust(cfg: dict, s: Any, results: dict) -> None:
    """Load content trust policies from praxis.yaml -> content_trust: section."""
    from l3.services.content_trust import load_policies
    load_policies(cfg if isinstance(cfg, dict) else {})
    results["content_trust"] = len(cfg) if isinstance(cfg, dict) else 0


def cfg_card_types(cfg: dict, s: Any, results: dict) -> None:
    """Load card type definitions from praxis.yaml → card_types: section."""
    from l3.card.card_unified import load_card_types
    load_card_types(cfg if isinstance(cfg, dict) else {})
    results["card_types"] = len(cfg) if isinstance(cfg, dict) else 0


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


def cfg_model_spec(cfg: dict, s: Any, results: dict) -> None:
    """Load model_spec tree from praxis.yaml model_spec: section.

    Stores flat keys in SettingsCenter for ModelService retrieval:
      model_spec.subagent.defaults.{key}
      model_spec.subagent.specs.{name}.{key}
      model_spec.scout.{key}
      model_spec.r4_agent.{key}
      model_spec.convention.{key}
      model_spec.cell.{key}
    """
    _store_tree(s, "model_spec", cfg)
    results["model_spec"] = "loaded"


def _store_tree(s: Any, prefix: str, data: dict) -> None:
    """Recursively store a nested dict as flat keys in SettingsCenter."""
    for key, value in data.items():
        full_key = f"{prefix}.{key}"
        if isinstance(value, dict):
            _store_tree(s, full_key, value)
        else:
            s.set(full_key, value)


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


def cfg_api_routes(cfg: dict, s: Any, results: dict) -> None:
    """Load external API routes from praxis.yaml api.routes section."""
    try:
        from l4.api.api_gateway import load_routes_from_yaml
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


def cfg_agent_role_map(cfg: dict, s: Any, results: dict) -> None:
    """Load AGENT_ROLE_MAP from praxis.yaml agent_role_map: section.

    Format:
      agent_role_map:
        1: "reader"
        2: "writer"
        3: "reviewer"

    Maps tool ring level → agent role name for HTN-C inference.
    """
    from l1.kernel.params.agent import AGENT_ROLE_MAP
    role_map = dict(AGENT_ROLE_MAP)
    for ring_str, role in cfg.items():
        try:
            role_map[int(ring_str)] = str(role)
        except (ValueError, TypeError):
            continue
    results["agent_role_map"] = len(role_map)


def cfg_agent_priority(cfg: dict, s: Any, results: dict) -> None:
    """Load AGENT_PRIORITY from praxis.yaml agent_priority: section.

    Format:
      agent_priority:
        reader:   5
        writer:   5
        reviewer: 5
    """
    from l1.kernel.params.agent import AGENT_PRIORITY
    priority = dict(AGENT_PRIORITY)
    priority.update(cfg)
    results["agent_priority"] = len(cfg)


def cfg_agents(cfg: dict, s: Any, results: dict) -> None:
    from l1.kernel.params.agent import AgentDefaults
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


def cfg_think(cfg: dict, s: Any, results: dict) -> None:
    """Load think quota max budget / max reasoning from praxis.yaml think: section."""
    from l3.config.settings_center import get_center
    center = get_center()
    if "max_budget" in cfg:
        center.set_l2("think.max_budget", int(cfg["max_budget"]))
    if "max_reasoning" in cfg:
        center.set_l2("think.max_reasoning", str(cfg["max_reasoning"]))
    if "profiles" in cfg and isinstance(cfg["profiles"], dict):
        center.set_l2("think.profiles", cfg["profiles"])
    results["think"] = True


def cfg_loop_control(cfg: dict, s: Any, results: dict) -> None:
    """Load loop control parameters from praxis.yaml loop_control: section."""
    from l3.config.settings_center import get_center
    center = get_center()
    mapping = {
        "max_steps": "loop.max_steps",
        "timeout": "loop.timeout",
        "max_iterations": "loop.max_iterations",
        "max_attempts": "loop.max_attempts",
        "continuation_nudge": "loop.continuation_nudge",
        "tool_repeat_warn": "loop.tool_repeat_warn",
        "tool_repeat_stop": "loop.tool_repeat_stop",
        "coarse_repeat_nudge": "loop.coarse_repeat_nudge",
        "coarse_repeat_stop": "loop.coarse_repeat_stop",
        "verify_cadence": "loop.verify_cadence",
    }
    for cfg_key, center_key in mapping.items():
        if cfg_key in cfg:
            center.set_l2(center_key, cfg[cfg_key])

    if "scope" in cfg:
        center.set_l2("loop.scope", cfg["scope"])
    if "enabled" in cfg:
        center.set_l2("loop.enabled", bool(cfg["enabled"]))
    results["loop_control"] = True


def cfg_l3a(cfg: dict, s: Any, results: dict) -> None:
    """Load L3A session limits from praxis.yaml l3a: section."""
    from l3.config.settings_center import get_center
    center = get_center()
    mapping = {
        "max_steps": "l3a.max_steps",
        "max_turns": "l3a.max_turns",
        "timeout": "l3a.timeout",
        "idle_timeout": "l3a.idle_timeout",
        "archive_importance": "l3a.archive_importance",
    }
    for yaml_key, sc_key in mapping.items():
        if yaml_key in cfg:
            center.set_l2(sc_key, cfg[yaml_key])
    results["l3a"] = True


def cfg_diff(cfg: dict, s: Any, results: dict) -> None:
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
            pass
    results["diff"] = True


def cfg_language(cfg: Any, s: Any, results: dict) -> None:
    """Load display language from praxis.yaml top-level `language:` key.

    The i18n adapter is wired with params/api.py I18N_DEFAULT_LOCALE; setattr
    that constant and mirror into SettingsCenter L2. If the i18n port is
    already registered (e.g. after wiring), switch its locale immediately.
    """
    if not cfg:
        results["language"] = False
        return
    lang = str(cfg).strip()
    if not lang:
        results["language"] = False
        return
    import l1.kernel.params.api as _api_mod
    _api_mod.I18N_DEFAULT_LOCALE = lang
    s.set_l2("language", lang)
    try:
        from l1.kernel.ports import get_port
        i18n = get_port("i18n")
        if i18n is not None and hasattr(i18n, "set_locale"):
            i18n.set_locale(lang)
    except Exception:
        pass
    results["language"] = True
