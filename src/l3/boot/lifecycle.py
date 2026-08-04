"""Lifecycle — unified shutdown path and system lifecycle management.

Replaces the old factory_reset() and shutdown_to_memories() split.
Provides a single shutdown() entry point with proper ordering:

  1. Stop accepting new work
  2. Persist all in-memory state
  3. Archive Ring 3 → Archive SQLite
  4. Stop background daemons (R4Agent, L3A)
  5. Reset all singletons (L4 → L3 → L1)
  6. (Optional) Wipe disk state
  7. Record lifecycle state
  8. (Optional) Cold boot
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Any

from l1.kernel.lifecycle import LifecycleState, get_lifecycle, transition

logger = logging.getLogger(__name__)


def _has_error(value: Any) -> bool:
    """Recursively detect error markers ('error: ...') inside nested shutdown results."""
    if isinstance(value, str):
        return value.startswith("error")
    if isinstance(value, dict):
        return any(_has_error(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_error(v) for v in value)
    return False


_SHUTDOWN_IN_PROGRESS = False


# ── Unified shutdown ──


def shutdown(wipe: bool = False, cold_boot: bool = False) -> dict:
    """Unified shutdown — persist, archive, stop daemons, reset.

    Idempotent: subsequent calls are no-ops while DRAINING.
    """
    global _SHUTDOWN_IN_PROGRESS
    if _SHUTDOWN_IN_PROGRESS:
        return {"success": True, "note": "already shutting down"}
    _SHUTDOWN_IN_PROGRESS = True

    t0 = time.time()
    results: dict[str, Any] = {}

    if not transition(LifecycleState.DRAINING):
        _SHUTDOWN_IN_PROGRESS = False
        return {"success": False, "error": "cannot enter DRAINING state"}

    # 1. Persist MemoryManager rings
    try:
        from l3.memory.memory_init import persist_all
        results["persist"] = persist_all()
    except Exception as e:
        results["persist"] = f"error: {e}"

    # 2. Archive Ring 3 high-importance entries
    try:
        from l3.memory.memory_init import archive_ring3
        n = archive_ring3()
        results["archive"] = f"{n} entries"
    except Exception as e:
        results["archive"] = f"error: {e}"

    # 3. Snapshot cells + agents
    try:
        from l3.memory.memory_init import snapshot_cells
        results["snapshot"] = snapshot_cells()
    except Exception as e:
        results["snapshot"] = f"error: {e}"

    # 4. Save kernel state
    try:
        from l1.kernel.persist import save
        save()
        results["kernel_state"] = "ok"
    except Exception as e:
        results["kernel_state"] = f"error: {e}"

    # 5. Stop background daemons
    try:
        from l3.memory.r4_agent import stop_r4_agent
        results["r4_agent"] = stop_r4_agent().get("archived", "stopped")
    except Exception as e:
        results["r4_agent"] = f"error: {e}"
    try:
        from l3.cell.peers.l3a import stop_l3a_daemon
        r = stop_l3a_daemon()
        results["l3a_daemon"] = "ok" if r.get("success") else f"error: {r.get('error', 'stop failed')}"
    except Exception as e:
        results["l3a_daemon"] = f"error: {e}"

    # 6. Reset all singletons
    try:
        results["singletons"] = reset_all_singletons()
    except Exception as e:
        results["singletons"] = f"error: {e}"

    # 7. Wipe disk (optional)
    if wipe:
        try:
            results["wipe"] = wipe_disk_state()
        except Exception as e:
            results["wipe"] = f"error: {e}"

    # 8. Record lifecycle
    clean = not any(_has_error(v) for v in results.values())
    try:
        lc = get_lifecycle()
        lc.record_shutdown(clean=clean)
    except Exception as e:
        logger.warning("lifecycle: shutdown record failed: %s", e)
    transition(LifecycleState.HALTED)

    elapsed = round(time.time() - t0, 2)
    logger.info("shutdown complete in %.2fs (clean=%s)", elapsed, clean)

    # 9. Cold boot (optional)
    if cold_boot:
        try:
            from .boot import boot
            results["cold_boot"] = boot()
        except Exception as e:
            results["cold_boot"] = f"error: {e}"

    _SHUTDOWN_IN_PROGRESS = False
    return {"success": True, "results": results, "elapsed": elapsed, "clean": clean}


# ── Signal handler (replaces memory_init.register_shutdown_handler) ──


def register_shutdown_handler() -> None:
    """Register atexit + SIGTERM/SIGINT handlers that call shutdown()."""
    import atexit

    def _graceful_shutdown() -> None:
        if _SHUTDOWN_IN_PROGRESS:
            return
        r = shutdown()
        status = "OK" if r.get("clean") else "ISSUES"
        print(f"\nShutdown {status} in {r.get('elapsed', '?')}s")

    def _signal_handler(signum: int, _frame: Any) -> None:
        _graceful_shutdown()
        sys.exit(128 + signum)

    atexit.register(_graceful_shutdown)
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, AttributeError):
        pass  # Signals not available on all platforms (Windows threads)


# ── Singleton reset (from old lifecycle.py) ──


def reset_all_singletons() -> dict[str, str]:
    """Reset all module-level singletons in L4 → L3 → L1 order."""
    results: dict[str, str] = {}
    for table in (_RESET_L4, _RESET_L3, _RESET_L1):
        _reset_layer(results, table)
    return results


def _reset_layer(results: dict[str, str], imports: list[tuple[str, str]]) -> None:
    for mod_name, func_name in imports:
        try:
            mod = __import__(mod_name, fromlist=[func_name])
            fn = getattr(mod, func_name, None)
            if fn:
                fn()
                results[mod_name] = "ok"
            else:
                results[mod_name] = "skip: no such function"
        except Exception as e:
            results[mod_name] = f"skip: {e}"


def wipe_disk_state(wipe_config: bool = False) -> dict[str, str]:
    """Delete runtime persistent state files. Returns {path: status}."""
    import glob as _glob
    import os as _os
    import shutil as _shutil

    from l1.kernel.paths import get_paths as _gp

    results: dict[str, str] = {}
    patterns = [
        f"{_gp().memories_dir}/*",
        f"{_gp().data_dir}/archive.db",
        f"{_gp().data_dir}/praxis_state*",
        f"{_gp().data_dir}/sandbox_state.json",
        f"{_gp().data_dir}/skills/evolved/*",
        f"{_gp().data_dir}/skills/lean/*",
        f"{_gp().data_dir}/l3a_outputs/*",
        f"{_gp().data_dir}/cache/*",
        ".praxis_state.db",
        ".praxis_settings.json",
        ".praxis/lifecycle.json",
        ".praxis/memory*",
        ".praxis/l3a_outputs/*",
    ]
    for pattern in patterns:
        for path in _glob.glob(pattern):
            try:
                if _os.path.isdir(path):
                    _shutil.rmtree(path, ignore_errors=True)
                else:
                    _os.remove(path)
                results[path] = "deleted"
            except Exception as e:
                results[path] = f"error: {e}"
    if wipe_config:
        config_path = _gp().config_file if hasattr(_gp(), 'config_file') else "config/praxis.yaml"
        try:
            _os.remove(config_path)
            results[config_path] = "deleted"
        except Exception as e:
            results[config_path] = f"error: {e}"
    return results


# ── Reset tables (from old lifecycle.py) ──

_RESET_L4: list[tuple[str, str]] = [
    ("l4.llm.llm", "reset_engine"),
    ("l4.mcp_bridge", "reset_bridge"),
    ("l4.sandbox", "reset_manager"),
    ("l4.supervisor", "reset_supervisor"),
    ("l4.ops_console", "reset_ops"),
    ("l4.cron_scheduler", "reset_scheduler"),
    ("l4.lsp.lsp_manager", "reset_manager"),
    ("l4.lsp.lsp", "reset_lsp"),
    ("l4.notify", "reset_service"),
    ("l4.user_session", "reset_service"),
    ("l4.vault.auth", "reset_service"),
    ("l4.ci", "reset_service"),
]

_RESET_L3: list[tuple[str, str]] = [
    ("l3.agent.subagent", "reset_dispatcher"),
    ("l3.agent.subagent_dispatcher", "reset_dispatcher"),
    ("l3.agent.subagent_framework", "reset_framework"),
    ("l3.agent.subagent_pool", "reset_pool"),
    ("l3.agent.subagent_gate", "reset_gate"),
    ("l3.agent.subagent_task", "reset_tasks"),
    ("l3.agent.subagent_merger", "reset_merger"),
    ("l3.agent.subagent_spec", "reset_specs"),
    ("l3.agent.scout", "reset_pool"),
    ("l3.agent.ai", "reset_instance"),
    ("l3.agent.pal_router", "reset_router"),
    ("l3.agent.stagnation", "reset_detector"),
    ("l3.agent_terminal", "reset_terminals"),
    ("l3.cell", "reset_cells"),
    ("l3.cell.peers.l3", "reset_coordinator"),
    ("l3.cell.components.cell_monitor", "reset_monitor"),
    ("l3.card.card_gate", "reset_gate"),
    ("l3.card.card_pool", "reset_pool"),
    ("l3.card.card_registry", "reset_registry"),
    ("l3.card.card_decomposer", "reset_decomposer"),
    ("l3.card.execution_engine", "reset_engine"),
    ("l3.card.issue", "reset_table"),
    ("l3.card.pending_queue", "reset_queue"),
    ("l3.card.transaction_area", "reset_area"),
    ("l3.memory.memory", "reset_memory"),
    ("l3.memory.memory_quality", "reset_quality"),
    ("l3.memory.context_pool", "reset_pool"),
    ("l3.memory.r4_agent", "reset_r4"),
    ("l3.memory.archive_orchestrator", "reset_orchestrator"),
    ("l3.memory.cache_doc", "reset_store"),
    ("l3.memory.reference_channel", "reset_channel"),
    ("l3.scheduler.think_registry", "reset_registry"),
    ("l3.scheduler.time_scheduler", "reset_scheduler"),
    ("l3.bus.monitor_bus", "reset_bus"),
    ("l3.bus.l3b_bus", "reset_bus"),
    ("l3.bus.l3b_message_pool", "reset_pool"),
    ("l3.bus.reference_channel", "reset_channel"),
    ("l3.bus.observability_bus", "reset_bus"),
    ("l3.bus.task_bus", "reset_bus"),
    ("l3.bus.cron_scheduler", "reset_scheduler"),
    ("l3.config.settings_center", "reset_center"),
    ("l3.config.config_loader", "reset_loader"),
    ("l3.discussion.issue_orchestrator", "reset_orchestrator"),
    ("l3.discussion.cell_answer_repo", "reset_repo"),
    ("l3.discussion.answer_session", "reset_session"),
    ("l3.discussion.answer_aggregator", "reset_aggregator"),
    ("l3.discussion.convention", "reset_convention"),
    ("l3.tool_system.tool_registry", "reset_registry"),
    ("l3.tool_system.tool_pipeline", "reset_pipeline"),
    ("l3.tools._archive", "reset_archive"),
    ("l3.error_bus", "reset_bus"),
    ("l3.resource_buffer.manager", "reset_manager"),
    ("l3.boot.wiring", "reset_wiring"),
    ("l3.discussion.discussion", "reset_discussion"),
    ("l3.services.counter", "reset_center"),
    ("l3.services.identity", "reset_identity"),
    ("l3.services.model_service", "reset_service"),
    ("l3.services.stats_center", "reset_center"),
    ("l3.services.service_manager", "reset_manager"),
]

_RESET_L1: list[tuple[str, str]] = [
    ("l1.kernel.swapper", "reset"),
    ("l1.kernel.allocator", "reset"),
    ("l1.kernel.gatechain", "reset"),
    ("l1.kernel.constitution", "reset"),
    ("l1.kernel.device", "reset_manager"),
    ("l1.kernel.vfs", "reset_vfs"),
    ("l1.kernel.process", "reset_table"),
    ("l1.kernel.event", "reset_bus"),
    ("l1.kernel.bus", "reset_bus"),
    ("l1.kernel.ipc", "reset_bus"),
    ("l1.kernel.tool_chain", "reset_chain"),
    ("l1.kernel.reputation", "reset_reputation"),
    ("l1.kernel.resource", "reset_profiles"),
    ("l1.kernel.skill", "reset_manager"),
    ("l1.kernel.settings", "reset_settings"),
    ("l1.kernel.model_registry", "reset_registry"),
    ("l1.kernel.commands", "reset_registry"),
    ("l1.kernel.paths", "reset_paths"),
    ("l1.kernel.ports", "reset_bus"),
    ("l1.kernel.net", "reset_net"),
    ("l1.kernel.os", "reset_os"),
    ("l1.kernel.lifecycle", "reset_lifecycle"),
]
