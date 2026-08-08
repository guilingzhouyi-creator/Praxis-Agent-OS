"""Boot step implementations — extracted from ``boot.py`` for modularity.

Each ``_*`` function is one boot step (constitution, discovery, config, kernel
services, tools, record center, skills/network, memory/archive, system bus,
services, cell, health check). ``boot.py`` registers and orchestrates them via
the boot-step registry; implementations live here so the orchestration file
stays small.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from l1.kernel.params.agent import DEFAULT_CELL_ID
from l1.kernel.params.kernel import SWAPPER_BOOT_INTERVAL

logger = logging.getLogger(__name__)


def _load_constitution() -> dict:
    """Load constitution from .praxis-rules.md into both territory and rule engine.

    Also restores custom rules previously persisted to SettingsCenter L3
    (from runtime API updates) so they survive restarts.
    """
    from pathlib import Path

    from l1.kernel.constitution import TerritoryConstitution, get_constitution, load_territory
    from l1.kernel.params.agent import CONSTITUTION_ENV_VAR
    from l1.kernel.paths import get_paths

    constitution_path = get_paths().constitution_file
    path = Path(os.environ.get(CONSTITUTION_ENV_VAR, constitution_path))
    result: dict[str, Any] = {"source": str(path) if path.exists() else "none"}
    try:
        if path.exists():
            c = load_territory(str(path))
            if not c or not isinstance(c, TerritoryConstitution):
                result["assembly_mode"] = True
            else:
                engine_load = get_constitution().load(str(path))
                if not engine_load.get("success"):
                    logger.warning("constitution engine load failed: %s", engine_load.get("error", ""))
                result["assembly_mode"] = False
                result["rules"] = engine_load.get("rules", 0)
                result["custom"] = engine_load.get("custom", 0)
        else:
            result["assembly_mode"] = True

        # Restore custom rules from SettingsCenter L3 (runtime persistence)
        try:
            from l3.config.settings_center import get_center

            sc = get_center()
            custom_rules = sc.get("constitution.custom_rules")
            if custom_rules and isinstance(custom_rules, list) and len(custom_rules) > 0:
                r = get_constitution().update_rules(custom_rules)
                result["restored"] = r.get("updated", 0)
                logger.info("constitution: restored %d custom rules from L3", r.get("updated", 0))
        except Exception:
            logger.debug("boot: constitution restore failed")

        # Inject the security-posture provider (kernel never imports L3; the
        # constitution's §9.2 skill.offensive_posture rule reads it to gate
        # offensive-skill use by system posture).
        try:
            from l1.kernel.constitution import set_posture_provider
            from l3.tool_system.security_mode import get_posture

            set_posture_provider(get_posture)
            result["posture_provider"] = True
        except Exception as e:
            logger.debug("boot: posture provider inject skipped: %s", e)

        # Inject the posture provider into GateChain too — G4 escalation skips
        # the L3 review WARN for high-danger tools when full_power is granted.
        try:
            from l1.kernel.gatechain import get_gatechain
            from l3.tool_system.security_mode import get_posture as _gp2

            get_gatechain().set_posture_provider(_gp2)
        except Exception as e:
            logger.debug("boot: gatechain posture provider inject skipped: %s", e)

        # Inject the metric sink into the L1 layers (constitution §9.2 BLOCK,
        # gatechain G4 full_power) — L1 never imports L3; the sink forwards
        # security.* counters to StatsCenter via security_mode helper.
        try:
            from l1.kernel.constitution import set_metric_sink
            from l1.kernel.gatechain import get_gatechain as _gc3
            from l3.tool_system.security_mode import ingest_security_metric

            def _sink(name: str, value: float, tags: dict | None = None) -> None:
                ingest_security_metric(name, value, tags)

            set_metric_sink(_sink)
            _gc3().set_metric_sink(_sink)
        except Exception as e:
            logger.debug("boot: metric sink inject skipped: %s", e)

        # Register the security notification source into RecordCenter so
        # query()/stats()/export() can cover the security domain (Phase E).
        try:
            from l3.services.record_center import get_record_center
            from l3.tool_system.security_mode import security_notifications

            def _sec_query(limit: int = 0) -> list:
                return security_notifications(limit=limit)

            def _sec_stats() -> dict:
                return {"notifications": len(security_notifications())}

            get_record_center().register_source(
                "security",
                query_fn=_sec_query,
                stats_fn=_sec_stats,
                export_fn=_sec_query,
            )
        except Exception as e:
            logger.debug("boot: record_center security source register skipped: %s", e)

        # Auto-trigger territory discussion if constitution is blank
        if result.get("assembly_mode"):
            try:
                logger.info("constitution: blank — triggering territory discussion")
                from l3.card.issue import IssueCard, get_table

                card = IssueCard(
                    id=f"issue-boot-{int(time.time())}",
                    title="Determine Cell territory division",
                    intent="The constitution has no territory definitions. "
                    "Each Cell must propose its territory assignment.",
                    domain="cluster",
                    cell_id="cell-1",
                )
                get_table().submit(card)
                from l3.discussion.issue_orchestrator import get_orchestrator

                orch = get_orchestrator()
                r = orch.start_discussion(card)
                if r.get("success"):
                    orch.register_cell(r["session_id"], "cell-1")
                    result["discussion_session"] = r["session_id"]
                    logger.info("constitution: started discussion %s", r["session_id"])
            except Exception as e:
                logger.warning("constitution: auto-discuss failed: %s", e)

        return {"success": True, **result}
    except Exception as e:
        logger.error("constitution load error: %s", e)
        return {"success": False, "error": str(e), "assembly_mode": True}


def _init_discovery() -> dict:
    """Auto-discover declarative YAML config snippets from config/discovery/.

    Merges them on top of params-derived defaults so later boot steps
    (load_config, load_tools, etc.) see the merged result.
    """
    from l1.kernel.discovery import (
        discover,
        register,
        register_discovery_dir,
    )
    from l1.kernel.params import agent as _pag
    from l1.kernel.params import api as _pa
    from l1.kernel.params import gatechain as _pgc
    from l1.kernel.params import kernel as _pk
    from l1.kernel.params import system as _ps
    from l1.kernel.params import tool as _pt

    # Register params-derived defaults for each config section
    register(
        "build_detectors",
        {
            "pip": {"cmd": ["python", "-m", "build"]},
            "cargo": {"cmd": ["cargo", "build"]},
            "npm": {"cmd": ["npm", "run", "build"]},
            "msbuild": {"cmd": ["msbuild"]},
            "dotnet": {"cmd": ["dotnet", "build"]},
        },
    )
    register(
        "test_detectors",
        {
            "pytest": {"cmd": ["python", "-m", "pytest"]},
            "cargo": {"cmd": ["cargo", "test"]},
            "npm": {"cmd": ["npm", "test"]},
            "dotnet": {"cmd": ["dotnet", "test"]},
            "vstest": {"cmd": ["vstest.console"]},
        },
    )
    register("provider_urls", dict(_pa.LLM_PROVIDER_URLS))
    # Ring → gate requirements (tool_spec.py reads get_config("ring_gates"))
    register(
        "ring_gates",
        {
            _pk.RING_1: ["G1", "G2"],
            _pk.RING_2_5: ["G1", "G2", "G3", "G4"],
            _pk.RING_3: ["G1", "G2", "G3", "G4", "G5"],
        },
    )
    # GateChain action-level danger ratings (gatechain.py reads this)
    register("gatechain_danger_levels", dict(_pgc.GATECHAIN_DANGER_LEVELS))
    # Constitution action sets (constitution.py reads get_config("constitution"))
    register(
        "constitution",
        {
            "file_actions": sorted(_pag.CONSTITUTION_FILE_ACTIONS),
            "modify_actions": sorted(_pag.CONSTITUTION_MODIFY_ACTIONS),
            "gate_actions": sorted(_pag.CONSTITUTION_GATE_ACTIONS),
            "scout_blocked": sorted(_pag.CONSTITUTION_SCOUT_BLOCKED),
        },
    )
    # Tool rate limiting (scheduler_rate.py reads get_config("tool_rates"))
    register(
        "tool_rates",
        {
            "ring_1": _pt.TOOL_RATE_RING_1,
            "ring_2_5": _pt.TOOL_RATE_RING_2_5,
            "ring_3": _pt.TOOL_RATE_RING_3,
        },
    )
    # Service timeouts (convention.py reads get_config("services"))
    register(
        "services",
        {
            "lsp_manager_timeout": _pa.LSP_MANAGER_TIMEOUT,
            "lsp_long_timeout": _pa.LSP_MANAGER_LONG_TIMEOUT,
            "lsp_diag_timeout": _pa.LSP_DIAG_TIMEOUT,
            "mcp_bridge_timeout": _pa.MCP_BRIDGE_TIMEOUT,
            "mcp_bridge_long_timeout": _pa.MCP_BRIDGE_LONG_TIMEOUT,
            "shell_session_timeout": _pa.SHELL_SESSION_TIMEOUT,
            "pool_queue_timeout": _pa.POOL_QUEUE_TIMEOUT,
            "term_handler_timeout": _pa.TERM_HANDLER_TIMEOUT,
            "term_handler_long_timeout": _pa.TERM_HANDLER_LONG_TIMEOUT,
            "gateway_queue_timeout": _pa.API_GATEWAY_QUEUE_TIMEOUT,
            "r4_agent_join_timeout": _pa.R4_AGENT_JOIN_TIMEOUT,
            "subagent_run_timeout": _pa.SUBAGENT_RUN_TIMEOUT,
            "subagent_join_timeout": _pa.SUBAGENT_JOIN_TIMEOUT,
            "convention_max_rounds": _pag.CONVENTION_MAX_ROUNDS,
            "convention_timeout": _pag.CONVENTION_TIMEOUT,
        },
    )

    # ── agent_configs.yaml sections (consumed only) ──
    register("skill_dirs", [".praxis/skills", "skills", ".skills"])
    register(
        "shell_aliases",
        {
            "rf": "read_file",
            "wf": "write_file",
            "ls": "list_directory",
            "g": "grep",
            "glob": "glob",
            "cat": "read_file",
            "h": "help",
            "q": "exit",
            "st": "status",
            "tl": "tools",
            "clr": "clear",
            "hist": "history",
        },
    )

    # Register tool timeout defaults (params → get_config fallback)
    # Covers every key consumed via get_tool_config() so praxis.yaml/discovery
    # overrides actually take effect instead of silently falling back.
    register(
        "tool",
        {
            "pip_install_timeout": _pt.TOOL_PIP_INSTALL_TIMEOUT,
            "npm_timeout": _pt.TOOL_NPM_TIMEOUT,
            "pyright_timeout": _pt.TOOL_PYRIGHT_TIMEOUT,
            "compile_check_timeout": _pt.TOOL_COMPILE_CHECK_TIMEOUT,
            "package_manager_timeout": _pt.TOOL_PACKAGE_MANAGER_TIMEOUT,
            "handler_timeout": _pt.TOOL_HANDLER_TIMEOUT,
            "web_timeout": _pt.TOOL_WEB_TIMEOUT,
            "search_timeout": _pt.TOOL_SEARCH_TIMEOUT,
            "terminal_timeout": _pt.TOOL_TERMINAL_TIMEOUT,
            "git_timeout": _pt.TOOL_GIT_TIMEOUT,
            "build_timeout": _pt.TOOL_BUILD_TIMEOUT,
            "grep_timeout": _pt.TOOL_GREP_TIMEOUT,
            "exec_timeout": _ps.SANDBOX_EXEC_TIMEOUT,
            "exec_token_budget": _pt.TOOL_EXEC_TOKEN_BUDGET,
            "harness_mode": _pt.HARNESS_MODE_DEFAULT,
            "loop.auto_test": _pt.AUTO_TEST_DEFAULT_MODE,
            "format_auto": _pt.TOOL_FORMAT_AUTO,
        },
    )

    # Register persistence defaults (params → get_config fallback)
    register(
        "persistence",
        {
            "interval": _ps.PERSIST_INTERVAL,
            "card_registry": _ps.CARD_REGISTRY_AUTO_SAVE,
            "card_gate": _ps.CARD_GATE_AUTO_SAVE,
            "pending_queue": _ps.PENDING_QUEUE_AUTO_SAVE,
            "issue_table": _ps.ISSUE_TABLE_AUTO_SAVE,
            "approval_gate": _ps.APPROVAL_GATE_AUTO_SAVE,
            "sandbox_state": _ps.SANDBOX_STATE_AUTO_SAVE,
            "todo_table": _ps.TODO_TABLE_AUTO_SAVE,
            "transaction_area": _ps.TRANSACTION_AREA_AUTO_SAVE,
            "statecharts": _ps.STATECHARTS_AUTO_SAVE,
            "execution_results": _ps.EXECUTION_RESULTS_AUTO_SAVE,
            "dialogue_session": _ps.DIALOGUE_SESSION_AUTO_SAVE,
        },
    )

    # Register service runtime limits (params → get_config fallback).
    # Declared declaratively in config/discovery/service_limits.yaml; consumers
    # read via get_config("service_limits", {}).get(key, params_default).
    register(
        "service_limits",
        {
            "execution_step_timeout": _ps.EXECUTION_STEP_TIMEOUT,
            "dialogue_max_turns": _ps.DIALOGUE_MAX_TURNS,
            "dialogue_max_context_tokens": _ps.DIALOGUE_MAX_CONTEXT_TOKENS,
            "dialogue_persist_every": _ps.DIALOGUE_PERSIST_EVERY,
            "transaction_area_max_queue": _ps.TRANSACTION_AREA_MAX_QUEUE,
            "monitor_bus_max_queued": _ps.MONITOR_BUS_MAX_QUEUED,
            "error_bus_query_limit": _ps.ERROR_BUS_QUERY_LIMIT,
            "record_center_default_limit": _ps.RECORD_CENTER_DEFAULT_LIMIT,
            "record_center_retention_days": _ps.RECORD_CENTER_RETENTION_DAYS,
            "memory_ring_score_char_weight": _ps.MEMORY_RING_SCORE_CHAR_WEIGHT,
            "memory_ring_score_tag_weight": _ps.MEMORY_RING_SCORE_TAG_WEIGHT,
            "memory_ring_score_high_importance": _ps.MEMORY_RING_SCORE_HIGH_IMPORTANCE,
            "memory_ring_score_moderate_importance": _ps.MEMORY_RING_SCORE_MODERATE_IMPORTANCE,
            "memory_ring_score_long_tokens": _ps.MEMORY_RING_SCORE_LONG_TOKENS,
            "memory_ring_score_medium_tokens": _ps.MEMORY_RING_SCORE_MEDIUM_TOKENS,
            "memory_ring_score_good_threshold": _ps.MEMORY_RING_SCORE_GOOD_THRESHOLD,
            "memory_ring_score_average_threshold": _ps.MEMORY_RING_SCORE_AVERAGE_THRESHOLD,
            # ── L4 key modules (config-driven via get_service_limit) ──
            "channel_ring_capacity": _pa.CHANNEL_RING_CAPACITY,
            "api_middleware_timeout": _pa.API_MIDDLEWARE_TIMEOUT,
            "lsp_cache_ttl": _pa.LSP_CACHE_TTL,
            "search_cache_max": _ps.SEARCH_CACHE_MAX,
            "ops_console_interval": _ps.OPS_CONSOLE_INTERVAL,
            "memory_recall_page_limit": _ps.MEMORY_RECALL_PAGE_LIMIT,
        },
    )

    # Register discovery directory
    from pathlib import Path as _Path

    dd = _Path(__file__).resolve().parent.parent.parent.parent / "config" / "discovery"
    register_discovery_dir(str(dd))

    # Run discovery (scans YAML → merges on top of defaults)
    n = discover()
    logger.info("discovery: loaded %d config snippet(s) from %s", n, dd)
    return {"success": True, "loaded": n}


def _load_config() -> dict:
    """Load praxis.yaml config and apply to system settings.

    Returns success=True even on config-not-found so first-boot is not blocked,
    but adds ``_non_fatal`` flag so boot reporting can distinguish."""
    try:
        from l3.config.config_loader import load_and_apply

        r = load_and_apply()
        if r.get("success"):
            return {"success": True, "applied": r.get("applied", {})}
        return {"success": True, "_non_fatal": True, "note": r.get("error", "config load failed")}
    except Exception as e:
        logger.error("config load error: %s", e)
        return {"success": True, "_non_fatal": True, "note": str(e)}


def _init_kernel_and_vfs() -> dict:
    """Init kernel core services + VFS + config + devices."""
    from l1.kernel import get_event_bus
    from l1.kernel.allocator import get_allocator
    from l1.kernel.constitution import get_constitution
    from l1.kernel.device import get_device_manager
    from l1.kernel.gatechain import get_gatechain, register_stagnation_callback
    from l1.kernel.swapper import get_swapper
    from l1.kernel.vfs import MountType, get_vfs

    # Wire the stagnation break_loop callback into GateChain G5 (L3 -> L1)
    try:
        from l3.agent.stagnation import get_detector as _get_detector

        register_stagnation_callback(_get_detector().break_loop)
    except Exception as e:
        logger.warning("boot: stagnation callback wiring failed: %s", e)

    results: dict[str, Any] = {}
    for name, fn in [
        ("constitution", get_constitution),
        ("event_bus", get_event_bus),
        ("allocator", get_allocator),
        ("gatechain", get_gatechain),
        ("swapper", lambda: get_swapper(interval=SWAPPER_BOOT_INTERVAL)),
    ]:
        try:
            fn()
            results[name] = "ok"
        except Exception as e:
            results[name] = f"error: {e}"

    vfs = get_vfs()
    for path, mtype, ro in [
        ("/project", MountType.PROJECT, False),
        ("/proc", MountType.SYSTEM, True),
        ("/tmp", MountType.TEMP, False),
    ]:
        vfs.mount(path, mtype, min_ring=1, read_only=ro, description=path.strip("/"))
    for path, mtype, ro in [
        ("/sys", MountType.VIRTUAL, True),
        ("/dev", MountType.VIRTUAL, True),
        ("/skills", MountType.VIRTUAL, True),
    ]:
        vfs.mount(path, mtype, min_ring=1, read_only=ro, description=path.strip("/"))

    # Config was already applied by the load_config boot step (handlers with
    # side effects: start_api, device registration, MCP import). Here we only
    # re-load + flatten into SettingsCenter L2 so this step stays pure and
    # the apply side effects run exactly once per boot.
    from l3.config.config_loader import load as _cfg_load
    from l3.config.settings_center import SettingsCenter, get_center

    try:
        _cfg_r = _cfg_load()
        if _cfg_r.get("success") and _cfg_r.get("data"):
            get_center().load_l2(SettingsCenter._flatten(_cfg_r["data"]))
    except Exception as e:
        logger.warning("boot config: %s", e)

    dm = get_device_manager()
    # Device registration is completed by the load_config step (cfg_devices,
    # praxis.yaml devices: section); nothing is hardcoded here because
    # re-registration is silently rejected by device_manager.
    dm.start_health_checks()
    return {"success": True, "results": results}


def _load_tools() -> dict:
    """Load tool definitions from tools.yaml into TOOL_REGISTRY."""
    try:
        from l3.tool_system.tool_config import ToolConfig

        n = ToolConfig.load()
        return {"success": True, "tools": n}
    except Exception as e:
        logger.warning("tool_config load failed: %s", e)
        return {"success": False, "error": str(e)}


def _init_record_center() -> dict:
    """Init RecordCenter and bridge to StatsCenter."""
    try:
        from l3.services.record_center import get_record_center

        rc = get_record_center()
        rc.bridge_stats()
        logger.info("record_center: initialized, export_dir=%s", rc._export_dir)
        return {"success": True}
    except Exception as e:
        logger.warning("record_center init: %s", e)
        return {"success": False, "error": str(e)}


def _init_skills_and_network() -> dict:
    """Init skills, network kernel, HTN planner, capability detector."""
    results: dict[str, Any] = {}
    from l1.kernel.skill import get_skill_manager

    n = get_skill_manager().load_builtin()
    if n > 0:
        logger.info("loaded %d skills", n)
    try:
        from l1.kernel.net import get_net

        get_net().start()
        results["network"] = "ok"
    except Exception as e:
        results["network"] = f"skip: {e}"
    try:
        from l3.bus.htn_planner import get_service as get_htn

        get_htn()
        results["htn_planner"] = "ok"
    except Exception as e:
        results["htn_planner"] = f"error: {e}"
    # Warm capability detector — async probe all registered providers
    try:
        from l1.kernel.model_registry import get_registry
        from l3.services.model_strategy import get_detector

        det = get_detector()
        n_probed = det.probe_all_registered(get_registry())
        results["capability_detector"] = f"{n_probed} providers submitted"
    except Exception as e:
        results["capability_detector"] = f"skip: {e}"
    return results


def _init_memory_and_archive() -> dict:
    """Init MemoryManager, Archive, R4Agent, IssueTable, CredentialVault."""
    results: dict[str, Any] = {}
    try:
        from l3.memory.memory import get_memory

        mem = get_memory()
        mem.set_persist_dir("memories")
        mr = mem.restore()
        results["memory_restore"] = f"{mr.get('restored', 0)} entries"
        # Wire swapper to memory service
        try:
            from l1.kernel.swapper import get_swapper

            swp = get_swapper()
            swp.set_memory(mem)
            results["swapper_wired"] = "ok"
        except Exception as e:
            results["swapper_wired"] = f"skip: {e}"
    except Exception as e:
        results["memory_restore"] = f"skip: {e}"
    try:
        from l3.tools._archive import init_archive

        init_archive()
        results["archive_init"] = "ok"
    except Exception as e:
        logger.warning("archive init failed: %s", e)
        results["archive_init"] = f"skip: {e}"
    try:
        from l3.memory.archive_orchestrator import ring3_from_archive

        n = ring3_from_archive(get_memory())
        results["archive_restore"] = f"{n} entries"
    except Exception as e:
        results["archive_restore"] = f"skip: {e}"
    try:
        from l3.memory.r4_agent import get_r4_agent, start_r4_agent

        r4 = get_r4_agent()
        try:
            from l3.cell import get_cell

            cell = get_cell("default")
            if cell and getattr(cell, "_pmu", None):
                r4.set_pmu(cell._pmu)
        except Exception as e:
            logger.debug("r4 pmu wire skipped: %s", e)
        start_r4_agent()
        results["r4_agent"] = "started"
    except Exception as e:
        results["r4_agent"] = f"error: {e}"
    try:
        from l3.cell.peers.l3a import start_l3a_daemon

        start_l3a_daemon()
        results["l3a_daemon"] = "started"
    except Exception as e:
        results["l3a_daemon"] = f"error: {e}"
    for mod, module_path, name in [
        ("issue", "l3.card.issue", "get_table"),
        ("cache_doc", "l3.memory.cache_doc", "get_store"),
        ("credential_vault", "l4.vault.credential_vault", "init_vault"),
        ("tool_mode", "l3.tool_system.tool_mode", "init_tool_mode"),
        ("central_security", "l3.services.central_security", "get_center"),
        ("central_memory", "l3.memory.central_memory", "get_center"),
        ("central_plugin", "l3.services.central_plugin", "get_center"),
        ("auth_service", "l4.vault.auth", "get_service"),
    ]:
        try:
            import importlib

            m = importlib.import_module(module_path)
            getattr(m, name)()
            results[mod] = "ok"
        except Exception as e:
            results[mod] = f"skip: {e}"
    return results


def _init_system_bus() -> dict:
    """Initialize SystemBus root with global service components.

    Registers EventBus, StatsCenter, RecordCenter, CentralController
    so they participate in the unified lifecycle and event routing.
    """
    results: dict[str, Any] = {}
    try:
        from l1.kernel.bus import get_root_bus

        root = get_root_bus()

        # Mount sub-buses
        gs = root.mount("global")

        # Register global components
        from l3.services.global_components import (
            CentralControllerComponent,
            EventBusComponent,
            RecordCenterComponent,
            StatsCenterComponent,
        )

        gs.register(StatsCenterComponent())
        gs.register(RecordCenterComponent())
        gs.register(EventBusComponent())
        gs.register(CentralControllerComponent())

        # The Cell bus will be mounted by _create_cell later

        gs.install()
        results["system_bus"] = "ok"
        results["components"] = [c.meta.name for c in gs.list()]
    except Exception as e:
        logger.warning("system_bus init: %s", e)
        results["system_bus"] = f"skip: {e}"
    return results


def _init_services() -> dict:
    """Initialize all kernel services."""
    results: dict[str, Any] = {}
    for sub_fn in [_init_kernel_and_vfs, _init_skills_and_network, _init_memory_and_archive]:
        try:
            r = sub_fn()
            results.update(r)
        except Exception as e:
            logger.error("boot sub-init failed: %s", e)
    # Initialize MonitorBus + MessageGate
    try:
        from l3.bus.monitor_bus import get_bus

        get_bus()  # warm singleton
        results["monitor_bus"] = "ok"
    except Exception as e:
        logger.warning("monitor_bus init: %s", e)
    try:
        from l3.bus.monitor_bus import MonitorEvent
        from l3.bus.monitor_bus import get_bus as _mb

        _mb().emit(MonitorEvent(type="system.boot", source="boot", severity="info", message="System booted"))
    except Exception:
        logger.debug("boot: boot event emit failed")
    # Initialize ResourceBuffer (crash recovery + background flush)
    try:
        from l3.resource_buffer.manager import get_manager

        get_manager()  # warm singleton, triggers recover()
        results["resource_buffer"] = "ok"
    except Exception as e:
        logger.warning("resource_buffer init: %s", e)

    # Register the code auto-format post-execute hook (config-gated in praxis.yaml)
    try:
        from l3.services.code_format import auto_format_hook
        from l3.tool_system.tool_pipeline import get_pipeline

        get_pipeline().register_post_execute_hook(auto_format_hook)
        results["code_format"] = "ok"
    except Exception as e:
        logger.warning("code_format hook register: %s", e)

    # Install LogService logging bridge (catches all logger.* calls)
    try:
        from l3.bus.log import get_service as _ls

        _ls().install_handler()
        results["log_handler"] = "ok"
    except Exception as e:
        logger.warning("log handler install: %s", e)

    # Register the card-triggered CI review daemon (config-gated in praxis.yaml)
    try:
        from l4.ci_review import get_service as _get_ci_review

        _get_ci_review().register_card_trigger()
        results["ci_review"] = "ok"
    except Exception as e:
        logger.warning("ci_review trigger register: %s", e)

    # Surface real failures (values starting with "error:") instead of hiding them
    failed = [k for k, v in results.items() if isinstance(v, str) and v.startswith("error")]
    if failed:
        logger.error("boot services with errors: %s", ", ".join(failed))
    return {"success": True, "services": list(results.keys()), "results": results, "failed": failed}


def _create_cell(agent_config: list[tuple[str, str, list[str]]] | None = None) -> dict:
    """Create Cell with configured agents + Scout pool."""
    from l1.kernel import register_process
    from l1.kernel.params.agent import AGENT_PRIORITY
    from l1.kernel.vfs import MountType, get_vfs
    from l3.agent.scout import get_pool as get_scout_pool
    from l3.cell import get_cell
    from l3.scheduler.scheduler import get_time_scheduler
    from l3.services.fault_tolerance import get_service as get_ft

    cell = get_cell(DEFAULT_CELL_ID)
    get_ft().start()

    # ── Skill binding from config (回灌到 Cell) — optional; missing → global pool ──
    try:
        from l3.config.settings_center import get_center as _gc

        cell_skills = _gc().get("cell.skills", {})
        if isinstance(cell_skills, dict):
            names = cell_skills.get(DEFAULT_CELL_ID) or cell_skills.get("*")
            if names:
                r = cell.bind_skills(names)
                logger.info("boot: bound %d skills to cell %s", r.get("bound", 0), DEFAULT_CELL_ID)
    except Exception as e:
        logger.debug("boot: skill binding skipped: %s", e)

    registered = []
    for agent_id, role, territory in agent_config or []:
        cell.add_agent(agent_id, role=role, territory=territory, auto_boot=True)
        pid = register_process(agent_id, role=role, ring=1)
        get_time_scheduler().register(agent_id, priority=AGENT_PRIORITY.get(role, 5))
        get_ft().heartbeat(agent_id)
        registered.append({"agent": agent_id, "pid": pid})
        for t in territory:
            get_vfs().mount(f"/{agent_id}/{t.lstrip('/')}", MountType.PROJECT, min_ring=1, read_only=False)

    get_scout_pool()

    # Register Cell with CardRegistry dispatcher + PendingQueue callback
    try:
        from l3.card.card_registry import get_registry

        reg = get_registry()
        reg.register_cell(DEFAULT_CELL_ID, cell.territory)
        reg.set_cell_resolver(lambda cid: get_cell(cid))
        reg.start_dispatcher()
        # Wire PendingQueue approve → CardRegistry.restore_card
        from l3.card.pending_queue import get_queue

        pq = get_queue()
        pq.set_on_approve(lambda cid: reg.restore_card(cid))
    except Exception as e:
        logger.warning("card registry setup: %s", e)

    return {
        "success": True,
        "cell_id": DEFAULT_CELL_ID,
        "agents": [a[0] for a in agent_config] if agent_config else [],
        "registered": registered,
    }


def _default_constitution() -> str:
    return """# NOMOS Constitution (default)
G1: workspace_fingerprint
G2: identity_verification
G3: permission_check
G4: compliance_scan
G5: report_decision
"""


def _post_boot_health_check() -> dict:
    """Verify core subsystems are operational after boot. Does not block."""
    checks: dict[str, Any] = {}
    try:
        from l3.memory.memory import get_memory

        m = get_memory()
        checks["memory"] = "ok" if m is not None else "unavailable"
    except Exception as e:
        checks["memory"] = f"error: {e}"
    try:
        from l3.card.card_registry import get_registry

        r = get_registry()
        checks["card_registry"] = "ok" if r is not None else "unavailable"
    except Exception as e:
        checks["card_registry"] = f"error: {e}"
    try:
        from l3.scheduler.scheduler import get_time_scheduler

        s = get_time_scheduler()
        checks["scheduler"] = "ok" if s is not None else "unavailable"
    except Exception as e:
        checks["scheduler"] = f"error: {e}"
    try:
        from l1.kernel.device import get_device_manager

        d = get_device_manager()
        devs = d.list()
        checks["devices"] = f"{len(devs)} registered"
    except Exception as e:
        checks["devices"] = f"error: {e}"
    try:
        from l3.agent_terminal import get_terminals

        terms = get_terminals()
        checks["terminals"] = f"{len(terms)} active"
    except Exception as e:
        checks["terminals"] = f"error: {e}"
    all_ok = all(v.startswith("ok") or v.endswith("registered") or "active" in v for v in checks.values())
    checks["_all_ok"] = all_ok
    return checks
