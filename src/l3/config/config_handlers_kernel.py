"""Config section handlers — kernel / L1 param domains.

Each ``cfg_*`` handler processes one section of praxis.yaml and applies its
values to the corresponding kernel/params configuration. Re-exported by
``config_handlers.py``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from l1.kernel.device import DeviceType, get_device_manager  # noqa: E402  (mid-file import avoids circularity)


def cfg_kernel(cfg: dict, s: Any, results: dict) -> None:
    """Apply kernel: section (allocator/swapper/process/syscall) to params and L2 settings."""
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
    """Apply cell: section (terminal/scout/card) to params and L2 settings."""
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


def cfg_gatechain(cfg: dict, s: Any, results: dict) -> None:
    """Apply gatechain: section (danger levels/scalar thresholds) to params and discovery registry."""
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


def cfg_network(cfg: dict, s: Any, results: dict) -> None:
    """Apply network section: ports, timeouts into env, params, and settings."""
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


def cfg_cache(cfg: dict, s: Any, results: dict) -> None:
    """Apply cache: section (file/context cache limits) to params/system.py constants."""
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


def cfg_devices(cfg: dict, s: Any, results: dict) -> None:
    """Load device definitions into the device manager and record the count."""
    dm = get_device_manager()
    devices: list[dict] = cfg if isinstance(cfg, list) else []
    for d in devices:
        name = d.get("name", "")
        dtype_name = d.get("type", "CUSTOM").upper()
        try:
            dtype = DeviceType[dtype_name]
        except Exception:
            dtype = DeviceType.CUSTOM
        dm.register(name, dtype, rate_limit=d.get("rate_limit", 10), description=d.get("description", ""))
    results["devices"] = len(devices)


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
        logger.warning("config: language apply failed", exc_info=True)
    results["language"] = True
