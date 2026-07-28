"""Lifecycle management — factory reset, singleton reset, disk wipe.

Provides system-level lifecycle operations beyond boot():
  - factory_reset():   full teardown + wipe + cold boot
  - reset_all_singletons():  reset all module-level singletons in dependency order
  - wipe_disk_state(): delete persistent state files
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from typing import Any

logger = logging.getLogger(__name__)


def reset_all_singletons() -> dict[str, str]:
    """Reset all known module-level singletons in L4 -> L3 -> L1 order.

    Relies on the existing reset_*() functions in each module.
    Returns a dict of {module_name: status}.
    """
    results: dict[str, str] = {}
    _reset_layer(results, _RESET_L4)
    _reset_layer(results, _RESET_L3)
    _reset_layer(results, _RESET_L1)
    return results


# ── Reset import tables (data-driven, one tuple per module) ──
# Format: (module_name, reset_function_name)

_RESET_L4: list[tuple[str, str]] = [
    ("l4.llm.llm", "reset_engine"),
    ("l4.mcp_bridge", "reset_bridge"),
    ("l4.sandbox", "reset_manager"),
    ("l4.supervisor", "reset_supervisor"),
    ("l4.ops_console", "reset_ops"),
    ("l4.cron_scheduler", "reset_scheduler"),
    ("l4.lsp.lsp_manager", "reset_manager"),
    ("l4.lsp.lsp", "reset_lsp"),
    ("l4.network", "reset_service"),
    ("l4.notify", "reset_service"),
    ("l4.user_session", "reset_service"),
    ("l4.vault.auth", "reset_service"),
    ("l4.ci", "reset_service"),
]

_RESET_L3: list[tuple[str, str]] = [
    ("l3.agent.scout", "reset_pool"),
    ("l3.agent.ai", "reset_service"),
    ("l3.agent.pal_router", "reset_router"),
    ("l3.agent.stagnation", "reset_detector"),
    ("l3.agent_terminal", "reset_terminals"),
    ("l3.cell", "reset_cells"),
    ("l3.cell.peers.l3", "reset_coordinator"),
    ("l3.cell.components.cell_monitor", "reset_cell_monitor"),
    ("l3.card.approval_gate", "reset_gate"),
    ("l3.card.card_gate", "reset_gate"),
    ("l3.card.card_pool", "reset_pool"),
    ("l3.card.card_registry", "reset_registry"),
    ("l3.card.decomposer", "reset_decomposer"),
    ("l3.card.execution_engine", "reset_service"),
    ("l3.card.issue", "reset_table"),
    ("l3.card.pending_queue", "reset_queue"),
    ("l3.card.transaction_area", "reset_service"),
    ("l3.memory.memory", "reset_memory"),
    ("l3.memory.result_store", "reset_result_store"),
    ("l3.memory.cache_doc", "reset_store"),
    ("l3.memory.cache", "reset_caches"),
    ("l3.memory.pager", "reset_service"),
    ("l3.memory.context", "reset_context"),
    ("l3.memory.pager_bridge", "reset_pager_bridge"),
    ("l3.memory.central_memory", "reset_center"),
    ("l3.scheduler.scheduler", "reset_scheduler"),
    ("l3.scheduler.scheduler_time", "reset_time_scheduler"),
    ("l3.scheduler.scheduler_rate", "reset_rate_scheduler"),
    ("l3.scheduler.scheduler_scope", "reset_scope_scheduler"),
    ("l3.scheduler.acb", "reset_service"),
    ("l3.scheduler.think_registry", "reset_think_registry"),
    ("l3.bus.ipc", "reset_bus"),
    ("l3.bus.htn_planner", "reset_service"),
    ("l3.bus.htn_a", "reset_htn_a"),
    ("l3.bus.comm_monitor", "reset_monitor"),
    ("l3.bus.l3b_bus", "reset_bus"),
    ("l3.bus.log", "reset_service"),
    ("l3.bus.message_gate", "reset_gate"),
    ("l3.bus.monitor_bus", "reset_bus"),
    ("l3.bus.observability_bus", "reset_obs_bus"),
    ("l3.bus.reference_channel", "reset_rc"),
    ("l3.bus.task_bus", "reset_task_bus"),
    ("l3.config.settings_center", "reset_center"),
    ("l3.config.settings_adapter", "reset_settings"),
    ("l3.config.config", "reset_service"),
    ("l3.discussion.report_service", "reset_service"),
    ("l3.discussion.issue_orchestrator", "reset_orchestrator"),
    ("l3.tool_system.tool_registry", "reset_registry"),
    ("l3.tool_system.tool_pipeline", "reset_pipeline"),
    ("l3.error_bus", "reset_bus"),
    ("l3.resource_buffer.manager", "reset_manager"),
    ("l3.boot.wiring", "reset_all"),
    ("l3.services.assembly", "reset_assembly"),
    ("l3.services.central_plugin", "reset_center"),
    ("l3.services.central_security", "reset_center"),
    ("l3.services.content_trust", "reset_trust"),
    ("l3.services.counter", "reset_counter"),
    ("l3.services.fault_tolerance", "reset_service"),
    ("l3.services.identity", "reset_service"),
    ("l3.services.model_service", "reset_service"),
    ("l3.services.package_manager", "reset_service"),
    ("l3.services.process", "reset_manager"),
    ("l3.services.record_center", "reset_record_center"),
    ("l3.services.service_manager", "reset_service"),
    ("l3.services.stats_center", "reset_center"),
    ("l3.services.template", "reset_service"),
    ("l3.services.vspace", "reset_manager"),
]

_RESET_L1: list[tuple[str, str]] = [
    ("l1.kernel.swapper", "reset_swapper"),
    ("l1.kernel.allocator", "reset_allocator"),
    ("l1.kernel.gatechain", "reset_gatechain"),
    ("l1.kernel.constitution", "reset_constitution"),
    ("l1.kernel.device", "reset_device_manager"),
    ("l1.kernel.vfs", "reset_vfs"),
    ("l1.kernel.process", "reset_table"),
    ("l1.kernel.event", "reset_bus"),
    ("l1.kernel.bus", "reset_root_bus"),
    ("l1.kernel.ipc", "reset_lock_bus"),
    ("l1.kernel.tool_chain", "reset_tool_chain"),
    ("l1.kernel.reputation", "reset_reputation"),
    ("l1.kernel.resource", "reset_limiter"),
    ("l1.kernel.skill", "reset_skill_manager"),
    ("l1.kernel.settings", "reset_settings"),
    ("l1.kernel.model_registry", "reset_registry"),
    ("l1.kernel.commands", "reset_registry"),
    ("l1.kernel.paths", "reset_paths"),
    ("l1.kernel.ports", "reset_ports"),
    ("l1.kernel.net", "reset_net"),
    ("l1.kernel.os", "reset_os"),
]


def _reset_layer(results: dict[str, str], imports: list[tuple[str, str]]) -> None:
    """Reset all singletons in a given import list, recording results."""
    for mod_name, func_name in imports:
        try:
            mod = __import__(mod_name, fromlist=[func_name])
            fn = getattr(mod, func_name, None)
            if fn:
                fn()
                results[mod_name] = "ok"
        except Exception as e:
            results[mod_name] = f"skip: {e}"


def wipe_disk_state(wipe_config: bool = False) -> dict[str, str]:
    """Delete all persistent runtime state files and directories.

    Args:
        wipe_config: If True, also delete config/praxis.yaml.

    Returns: dict of {path: status}
    """
    results: dict[str, str] = {}

    # Runtime state files (from .gitignore patterns)
    patterns = [
        "memories/",
        ".praxis_state.db",
        ".praxis_events.db",
        ".praxis_card_registry.json",
        ".praxis_pending_queue.json",
        ".praxis_approval_gate.json",
        ".praxis_todo_table.json",
        ".praxis_execution_results.json",
        ".praxis_dialogue_session.json",
        ".praxis_settings.json",
        ".praxis_settings.json.bak",
        ".praxis_sandbox_state.json",
        "*.chain_key",
        ".chain_key",
        ".praxis/*.json",
        ".praxis/.praxis_reference_channel.jsonl",
        ".praxis_monitor.jsonl",
        ".praxis_seq_monitor_*.json",
        "*.state.json",
        "*.snapshot.json",
        "events.db",
        "archive.db",
        "*.log",
    ]

    cwd = os.getcwd()
    for pattern in patterns:
        import glob
        for path in glob.glob(os.path.join(cwd, pattern), recursive=True):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
                results[path] = "deleted"
            except Exception as e:
                results[path] = f"error: {e}"

    # Optional: config wipe
    if wipe_config:
        config_path = os.path.join(cwd, "config", "praxis.yaml")
        if os.path.exists(config_path):
            try:
                os.remove(config_path)
                results[config_path] = "deleted"
            except Exception as e:
                results[config_path] = f"error: {e}"

    return results


def factory_reset(wipe_config: bool = False) -> dict[str, Any]:
    """Full factory reset: shutdown -> reset singletons -> wipe disk -> boot.

    Args:
        wipe_config: If True, also delete config/praxis.yaml so next
                     boot triggers the first-boot bootstrap wizard.

    Returns: dict with reset status and boot result.
    """
    start = time.time()
    results: dict[str, Any] = {}

    # Phase 1: Graceful shutdown
    try:
        from l1.kernel.os import get_os
        osys = get_os()
        if osys.state.name in ("RUNNING", "STARTING"):
            sd = osys.shutdown()
            results["shutdown"] = "ok" if sd.get("success") else sd.get("error", "?")
        else:
            results["shutdown"] = "not running"
    except Exception as e:
        results["shutdown"] = f"error: {e}"

    # Phase 2: Stop R4 agent
    try:
        from l3.memory.r4_agent import stop_r4_agent
        stop_r4_agent()
        results["r4_agent"] = "stopped"
    except Exception:
        results["r4_agent"] = "skip"

    # Phase 3: Reset all singletons
    try:
        results["singletons"] = reset_all_singletons()
    except Exception as e:
        results["singletons"] = f"error: {e}"

    # Phase 4: Wipe disk state
    try:
        results["wipe"] = wipe_disk_state(wipe_config=wipe_config)
    except Exception as e:
        results["wipe"] = f"error: {e}"

    results["elapsed"] = round(time.time() - start, 3)

    # Phase 5: Cold boot
    try:
        from .boot import boot
        br = boot()
        results["boot"] = br
    except Exception as e:
        results["boot"] = {"success": False, "error": str(e)}

    results["total_elapsed"] = round(time.time() - start, 3)
    return results
